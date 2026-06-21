"""Geocoding zona -> bbox via Nominatim (#15).

Risolve una zona all'interno di una citta' in coordinate e bounding box, usando
``geopy.geocoders.Nominatim``. Il bbox e' la tupla ``(lat_min, lon_min, lat_max,
lon_max)`` consumata a valle dal client Overpass.

Le eccezioni di dominio (:class:`ZoneNotFoundError`, :class:`GeocodingError`)
sono progettate per essere mappate dall'orchestrator a risposte HTTP esplicite
(zona non geocodificabile -> 422, servizio non raggiungibile -> 503), alimentando
lo Stato Errore del frontend. Nominatim e' un servizio HTTP sincrono: l'unica
funzione pubblica e' percio' sincrona e va invocata via ``run_in_threadpool`` da
un handler async.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol, TypedDict, cast

from geopy.exc import GeocoderServiceError  # pyright: ignore[reportMissingTypeStubs]
from geopy.geocoders import (  # pyright: ignore[reportMissingTypeStubs]
    Nominatim,
)

from crime_risk_analyzer.models.geo import Bbox

__all__ = ["Bbox", "GeoResult", "GeocodingError", "ZoneNotFoundError", "geocode_zone"]

#: User-agent dedicato, richiesto dalla usage policy di Nominatim.
_USER_AGENT = "crime-risk-analyzer"


class _Location(Protocol):
    """Vista tipata minimale del ``geopy.location.Location`` (libreria senza stub)."""

    @property
    def latitude(self) -> float: ...

    @property
    def longitude(self) -> float: ...

    @property
    def raw(self) -> dict[str, object]: ...


class GeoResult(TypedDict):
    """Esito del geocoding: punto centrale + bounding box."""

    lat: float
    lon: float
    bbox: Bbox


class GeocodingError(RuntimeError):
    """Errore del servizio di geocoding (timeout, HTTP, parsing risposta)."""


class ZoneNotFoundError(GeocodingError):
    """La zona non e' geocodificabile nella citta' indicata."""


@lru_cache(maxsize=1)
def _get_geolocator() -> Nominatim:
    """Provider cached del geocoder Nominatim (un'istanza per processo)."""
    return Nominatim(user_agent=_USER_AGENT)


def _geocode(query: str) -> _Location | None:
    """Confina la chiamata a geopy (senza stub) restituendo un tipo noto."""
    geolocator = _get_geolocator()
    result: object = geolocator.geocode(query, addressdetails=False)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return cast("_Location | None", result)


def _parse_bbox(boundingbox: object) -> Bbox:
    """Converte il ``boundingbox`` Nominatim in :data:`Bbox`.

    Nominatim espone ``raw['boundingbox'] = [lat_min, lat_max, lon_min, lon_max]``
    come stringhe; qui si riordina in ``(lat_min, lon_min, lat_max, lon_max)``.
    Solleva ``(ValueError, TypeError)`` se il formato non e' utilizzabile: il
    chiamante lo traduce in :class:`ZoneNotFoundError`.
    """
    if not isinstance(boundingbox, (list, tuple)):
        raise ValueError("boundingbox assente o malformato")
    values: list[object] = list(cast("list[object] | tuple[object, ...]", boundingbox))
    if len(values) != 4:
        raise ValueError("boundingbox di lunghezza inattesa")
    lat_min, lat_max, lon_min, lon_max = (float(cast(str, v)) for v in values)
    return Bbox(min_lat=lat_min, min_lon=lon_min, max_lat=lat_max, max_lon=lon_max)


def geocode_zone(zona: str, citta: str) -> GeoResult:
    """Geocodifica ``zona`` dentro ``citta`` -> ``{lat, lon, bbox}``.

    Solleva :class:`ZoneNotFoundError` se la zona non e' trovata o e' priva di
    bounding box utilizzabile, e :class:`GeocodingError` se il servizio Nominatim
    non e' raggiungibile.
    """
    query = f"{zona}, {citta}"
    try:
        location = _geocode(query)
    except GeocoderServiceError as exc:
        raise GeocodingError(
            f"Servizio di geocoding non raggiungibile per {query!r}"
        ) from exc

    if location is None:
        raise ZoneNotFoundError(f"Zona non trovata: {zona!r} in {citta!r}")

    raw = location.raw
    try:
        bbox = _parse_bbox(raw.get("boundingbox"))
    except (ValueError, TypeError) as exc:
        raise ZoneNotFoundError(
            f"Zona priva di bounding box: {zona!r} in {citta!r}"
        ) from exc

    return GeoResult(lat=location.latitude, lon=location.longitude, bbox=bbox)
