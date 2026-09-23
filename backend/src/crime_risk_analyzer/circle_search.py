"""Risolve un cerchio (centro+raggio) in un GeoSource iniettabile (#318).

Riusa il punto di estensione ``geo_source`` che :mod:`crime_risk_analyzer.rag.retrieval`
espone gia' per il replay in ``eval/`` (#169): il cerchio disegnato dall'utente
diventa un ``geo_source`` che ignora gli argomenti ``(citta, zona)`` e ritorna
sempre lo stesso :class:`~crime_risk_analyzer.geocoding.GeoResult`, calcolato
puramente da centro e raggio (nessun bbox Nominatim in gioco per il prodotto).
"""

from __future__ import annotations

from fastapi.concurrency import run_in_threadpool

from crime_risk_analyzer.geocoding import GeoResult, reverse_geocode_label
from crime_risk_analyzer.models.geo import bbox_from_circle
from crime_risk_analyzer.rag.retrieval import GeoSource

__all__ = ["resolve_circle"]


async def resolve_circle(
    lat: float, lon: float, radius_m: float
) -> tuple[str, str, GeoSource]:
    """(citta, zona) best-effort da reverse geocode + un GeoSource per il cerchio.

    Args:
        lat: Latitudine del centro del cerchio.
        lon: Longitudine del centro del cerchio.
        radius_m: Raggio del cerchio in metri.

    Returns:
        Tupla (citta, zona, geo_source) dove geo_source e' un callable che ignora
        gli argomenti (citta, zona) e ritorna sempre lo stesso GeoResult.
    """
    citta, zona = await run_in_threadpool(reverse_geocode_label, lat, lon)
    bbox = bbox_from_circle(lat, lon, radius_m)

    async def _geo_source(_citta: str, _zona: str) -> GeoResult:
        return GeoResult(lat=lat, lon=lon, bbox=bbox)

    return citta, zona, _geo_source
