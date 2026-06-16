"""Client Overpass API -> POI on-demand (#16).

Interroga Overpass nel bounding box di una citta' per una lista di chiavi OSM e
restituisce i POI nel contratto di RETRIEVAL: ogni POI espone ``id``, ``name``,
``lat``, ``lon``, ``osm_tags``, ``terminus_class`` e ``citta``. I campi
``confidence`` e ``sparql_path`` NON sono aggiunti qui: li produce il layer
grounding/SPARQL a valle.

Vincoli (orchestrator.md): massimo :data:`MAX_POIS` POI per richiesta; in caso di
timeout un solo retry con timeout esteso, poi :class:`OverpassError` (mappata a
503 dall'orchestrator). Le chiamate sono async (``httpx.AsyncClient``): nessun
I/O bloccante.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import TypedDict, cast

import httpx

from crime_risk_analyzer.sparql_module.osm_mapping import map_to_terminus

#: Endpoint Overpass di default (override possibile via parametro).
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

#: Numero massimo di POI restituiti per richiesta (orchestrator.md / retrieval.md).
MAX_POIS = 50

#: Timeout (secondi) del primo tentativo e del retry esteso.
_TIMEOUT_S = 30.0
_RETRY_TIMEOUT_S = 60.0

#: Bounding box: (lat_min, lon_min, lat_max, lon_max).
Bbox = tuple[float, float, float, float]


class Poi(TypedDict):
    """POI nel contratto di retrieval (pre-grounding)."""

    id: str
    name: str
    lat: float
    lon: float
    osm_tags: str
    terminus_class: str
    citta: str


class OverpassError(RuntimeError):
    """Overpass non raggiungibile o risposta non valida (mappabile a 503)."""


def _build_query(bbox: Bbox, osm_keys: Sequence[str]) -> str:
    """Costruisce la query Overpass QL per i ``osm_keys`` dentro ``bbox``.

    Overpass usa il bbox nell'ordine ``(south, west, north, east)`` ==
    ``(lat_min, lon_min, lat_max, lon_max)``. Si interrogano sia ``node`` che
    ``way`` (con ``out center`` per ottenere un centroide).
    """
    lat_min, lon_min, lat_max, lon_max = bbox
    bbox_str = f"{lat_min},{lon_min},{lat_max},{lon_max}"
    selectors = "\n".join(
        f'  node["{key}"]({bbox_str});\n  way["{key}"]({bbox_str});' for key in osm_keys
    )
    return f"[out:json][timeout:25];\n(\n{selectors}\n);\nout center {MAX_POIS};"


def _extract_osm_tag(tags: Mapping[str, object]) -> str:
    """Estrae il tag rappresentativo ``chiave=valore`` da ``tags`` OSM.

    Preferisce le chiavi che alimentano il mapping TERMINUS, nell'ordine di
    priorita' usato dalle spec. Ritorna stringa vuota se nessuna e' presente.
    """
    for key in ("amenity", "tourism", "railway", "aeroway", "shop"):
        value = tags.get(key)
        if isinstance(value, str):
            return f"{key}={value}"
    return ""


def _coords(element: Mapping[str, object]) -> tuple[float, float] | None:
    """Estrae ``(lat, lon)`` da un elemento, o ``None`` se non utilizzabili.

    I ``node`` hanno ``lat``/``lon`` diretti; i ``way`` espongono il centroide
    in ``center``.
    """
    lat = element.get("lat")
    lon = element.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        center = element.get("center")
        if not isinstance(center, Mapping):
            return None
        center_map = cast(Mapping[str, object], center)
        lat = center_map.get("lat")
        lon = center_map.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    return float(lat), float(lon)


def _to_poi(element: Mapping[str, object], citta: str) -> Poi | None:
    """Converte un elemento Overpass in :class:`Poi`, o ``None`` se inutilizzabile.

    Scarta gli elementi senza tag o senza coordinate.
    """
    tags = element.get("tags")
    if not isinstance(tags, Mapping):
        return None
    tags_map = cast(Mapping[str, object], tags)

    coords = _coords(element)
    if coords is None:
        return None
    lat, lon = coords

    osm_tag = _extract_osm_tag(tags_map)
    return Poi(
        id=str(element.get("id", "")),
        name=str(tags_map.get("name", "")),
        lat=lat,
        lon=lon,
        osm_tags=osm_tag,
        terminus_class=map_to_terminus(osm_tag),
        citta=citta,
    )


def _parse_elements(payload: object, citta: str) -> list[Poi]:
    """Mappa gli ``elements`` di una risposta Overpass in POI (cap a MAX_POIS)."""
    if not isinstance(payload, Mapping):
        raise OverpassError("Risposta Overpass non valida: payload non oggetto")
    payload_map = cast(Mapping[str, object], payload)
    elements = payload_map.get("elements")
    if not isinstance(elements, list):
        raise OverpassError("Risposta Overpass priva di 'elements'")
    elements_list = cast(list[object], elements)

    pois: list[Poi] = []
    for element in elements_list:
        if not isinstance(element, Mapping):
            continue
        poi = _to_poi(cast(Mapping[str, object], element), citta)
        if poi is not None:
            pois.append(poi)
        if len(pois) >= MAX_POIS:
            break
    return pois


async def _post_query(
    client: httpx.AsyncClient, url: str, query: str, timeout: float
) -> httpx.Response:
    """Esegue il POST della query a Overpass con il timeout indicato."""
    return await client.post(url, content=query, timeout=timeout)


async def fetch_pois(
    bbox: Bbox,
    citta: str,
    osm_keys: Iterable[str],
    *,
    overpass_url: str = DEFAULT_OVERPASS_URL,
) -> list[Poi]:
    """Recupera i POI dentro ``bbox`` per le chiavi OSM ``osm_keys``.

    Arricchisce ogni POI con ``terminus_class`` (#13). In caso di timeout esegue
    un solo retry con timeout esteso; se anche questo fallisce solleva
    :class:`OverpassError`. Risposte non-2xx -> :class:`OverpassError`.
    """
    keys = list(osm_keys)
    query = _build_query(bbox, keys)

    async with httpx.AsyncClient() as client:
        try:
            response = await _post_query(client, overpass_url, query, _TIMEOUT_S)
        except httpx.TimeoutException:
            try:
                response = await _post_query(
                    client, overpass_url, query, _RETRY_TIMEOUT_S
                )
            except httpx.TimeoutException as exc:
                raise OverpassError(
                    "Overpass timeout dopo retry con timeout esteso"
                ) from exc
        except httpx.HTTPError as exc:
            raise OverpassError(f"Errore di rete verso Overpass: {exc}") from exc

    if not response.is_success:
        raise OverpassError(f"Overpass ha risposto {response.status_code}")

    try:
        payload: object = response.json()
    except ValueError as exc:
        raise OverpassError("Risposta Overpass non e' JSON valido") from exc

    return _parse_elements(payload, citta)
