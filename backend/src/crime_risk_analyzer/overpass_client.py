"""Client Overpass API -> POI on-demand (#16).

Interroga Overpass nel bounding box di una citta' per una lista di chiavi OSM e
restituisce i POI nel contratto di RETRIEVAL: ogni POI espone ``id``, ``name``,
``lat``, ``lon``, ``osm_tags``, ``terminus_class`` e ``citta``. I campi
``confidence`` e ``sparql_path`` NON sono aggiunti qui: li produce il layer
grounding/SPARQL a valle.

Vincoli (orchestrator.md): massimo :data:`MAX_POIS` POI per richiesta; in caso di
timeout **o** di status ritentabile (429/5xx) un solo retry (breve pausa di
cortesia + timeout esteso), poi :class:`OverpassError` (mappata a 503
dall'orchestrator). Le chiamate sono async (``httpx.AsyncClient``): nessun
I/O bloccante.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from typing import TypedDict, cast

import httpx

from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.sparql_module.osm_mapping import (
    ORDINE_FAMIGLIE,
    OSM_SELECTORS,
    OSM_TO_TERMINUS,
    map_to_terminus,
)

__all__ = ["Bbox", "MAX_POIS", "OverpassError", "PER_SELECTOR_CAP", "Poi", "fetch_pois"]

#: Endpoint Overpass di default (override possibile via parametro).
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

#: Numero massimo di POI restituiti per richiesta (orchestrator.md / retrieval.md).
MAX_POIS = 50

#: Cap di elementi restituiti da Overpass PER selettore: evita che selettori densi
#: (es. highway=bus_stop, amenity=place_of_worship) monopolizzino il budget affamando
#: le classi rare. La curatela finale/bilanciata e' dell'orchestrator (#79).
PER_SELECTOR_CAP = 5

#: Timeout (secondi) del primo tentativo e del retry esteso.
_TIMEOUT_S = 30.0
_RETRY_TIMEOUT_S = 60.0

#: Status HTTP ritentabili: 429 (rate limit) e 5xx di gateway/overload. Una
#: risposta con questi status non e' un errore definitivo ma una condizione
#: transitoria di Overpass -> merita l'unico retry come un timeout.
_RETRYABLE_STATUS = frozenset({429, 502, 503, 504})

#: Breve pausa di cortesia (secondi) prima del retry: utile soprattutto sul 429,
#: dove ripartire subito verrebbe di nuovo throttlato. Non bloccante (async).
_RETRY_PAUSE_S = 1.0

#: User-agent esplicito richiesto dall'endpoint pubblico Overpass: senza di esso
#: (default httpx ``python-httpx/...``) overpass-api.de risponde 406.
_USER_AGENT = "crime-risk-analyzer"


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


def _build_query(bbox: Bbox, osm_selectors: Sequence[str]) -> str:
    """Costruisce la query Overpass QL per i selettori ``key=value`` dentro ``bbox``.

    Ogni selettore ``k=v`` emette un blocco unione node+way seguito da un
    ``out center PER_SELECTOR_CAP`` locale: cosi' nessun selettore denso satura il
    risultato. Bbox nell'ordine ``(south, west, north, east)``.
    """
    lat_min, lon_min, lat_max, lon_max = bbox
    bbox_str = f"{lat_min},{lon_min},{lat_max},{lon_max}"
    blocks: list[str] = []
    for selector in osm_selectors:
        key, _, value = selector.partition("=")
        blocks.append(
            f'(\n  node["{key}"="{value}"]({bbox_str});\n'
            f'  way["{key}"="{value}"]({bbox_str});\n);\n'
            f"out center {PER_SELECTOR_CAP};"
        )
    return "[out:json][timeout:25];\n" + "\n".join(blocks)


def _extract_osm_tag(tags: Mapping[str, object]) -> str:
    """Estrae il selettore rappresentativo ``chiave=valore`` da ``tags`` OSM.

    Itera le famiglie in :data:`ORDINE_FAMIGLIE` (priorita') e ritorna il PRIMO
    ``key=value`` che esiste nel binding :data:`OSM_TO_TERMINUS`. Cosi' un POI
    multi-tag e' classificato dal tag effettivamente mappato e non da un tag spurio
    a priorita' piu' alta. Ritorna stringa vuota se nessun tag noto e' presente.
    """
    for family in ORDINE_FAMIGLIE:
        value = tags.get(family)
        if isinstance(value, str):
            selector = f"{family}={value}"
            if selector in OSM_TO_TERMINUS:
                return selector
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


async def _try_post(
    client: httpx.AsyncClient, url: str, query: str, timeout: float
) -> httpx.Response | None:
    """Esegue un tentativo di POST a Overpass col timeout indicato.

    Ritorna la :class:`httpx.Response` (qualunque status), oppure ``None`` se il
    tentativo scade in timeout (segnale ritentabile). Un errore di trasporto
    non-timeout (``httpx.HTTPError``, es. connessione rifiutata) e' definitivo:
    viene rilanciato subito come :class:`OverpassError`.
    """
    try:
        return await client.post(url, content=query, timeout=timeout)
    except httpx.TimeoutException:
        return None
    except httpx.HTTPError as exc:
        raise OverpassError(f"Errore di rete verso Overpass: {exc}") from exc


async def fetch_pois(
    bbox: Bbox,
    citta: str,
    osm_selectors: Iterable[str] = OSM_SELECTORS,
    *,
    overpass_url: str = DEFAULT_OVERPASS_URL,
) -> list[Poi]:
    """Recupera i POI dentro ``bbox`` per i selettori OSM ``osm_selectors``.

    Default: l'intero binding canonico :data:`OSM_SELECTORS`. Arricchisce ogni POI
    con ``terminus_class`` (#13). Un solo retry (con breve pausa di cortesia e
    timeout esteso) se il primo tentativo scade in timeout **o** risponde con uno
    status ritentabile (:data:`_RETRYABLE_STATUS`, 429/5xx); poi
    :class:`OverpassError`.
    """
    selectors = list(osm_selectors)
    query = _build_query(bbox, selectors)

    async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}) as client:
        response = await _try_post(client, overpass_url, query, _TIMEOUT_S)
        # Un SOLO retry: scatta sia sul timeout (response None) sia su uno status
        # transitorio (429/5xx). Uno status non-2xx NON ritentabile (400/403/404)
        # cade fuori e fallisce subito piu' sotto.
        if response is None or response.status_code in _RETRYABLE_STATUS:
            await asyncio.sleep(_RETRY_PAUSE_S)
            response = await _try_post(client, overpass_url, query, _RETRY_TIMEOUT_S)

    if response is None:
        raise OverpassError("Overpass timeout dopo retry con timeout esteso")
    if not response.is_success:
        raise OverpassError(f"Overpass ha risposto {response.status_code}")

    try:
        payload: object = response.json()
    except ValueError as exc:
        raise OverpassError("Risposta Overpass non e' JSON valido") from exc

    return _parse_elements(payload, citta)
