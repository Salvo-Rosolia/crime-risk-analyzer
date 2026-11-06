"""Resolves the analysis AREA into an injectable GeoSource, in both modes.

The two search modes COEXIST and the user picks one or the other:

* :func:`resolve_circle` — the circle drawn on the map (centre+radius, #318),
  bbox computed purely, no network call in that computation;
* :func:`resolve_zone` — the two fields citta + zona, bbox from Nominatim with the
  already-tuned minimum floor (:func:`~crime_risk_analyzer.geocoding.geocode_zone`).

Both return the SAME contract ``(citta, zona, geo_source)``, so the rest of the
pipeline does not know which mode was used. It is the ``geo_source`` extension
point that :mod:`crime_risk_analyzer.rag.retrieval` already exposes for the replay
in ``eval/`` (#169) that makes this symmetry possible: adding a search mode
touches neither ``retrieve`` nor the evaluation harness.

Two deliberate asymmetries between the modes:

* labels — the circle has no text, so it takes them from the reverse geocode of
  the centre; with citta + zona the typed text IS the area, and stays the label;
* errors — in the circle the reverse geocode is COSMETIC and never blocks; with
  citta + zona the geocode DETERMINES the analysed area, so a zone not found
  is a real error and does not degrade to a fallback area.
"""

from __future__ import annotations

from fastapi.concurrency import run_in_threadpool

from crime_risk_analyzer.geocoding import (
    GeoResult,
    check_area_size,
    geocode_zone,
    reverse_geocode_label,
)
from crime_risk_analyzer.models.geo import bbox_from_circle
from crime_risk_analyzer.rag.retrieval import GeoSource

__all__ = ["capped_zone_geo_source", "resolve_circle", "resolve_zone"]


async def resolve_circle(
    lat: float, lon: float, radius_m: float
) -> tuple[str, str, GeoSource]:
    """(citta, zona) best-effort from reverse geocode + a GeoSource for the circle.

    Args:
        lat: Latitude of the circle centre.
        lon: Longitude of the circle centre.
        radius_m: Circle radius in metres.

    Returns:
        Tuple (citta, zona, geo_source) where geo_source is a callable that ignores
        its arguments (citta, zona) and always returns the same GeoResult.
    """
    citta, zona = await run_in_threadpool(reverse_geocode_label, lat, lon)
    bbox = bbox_from_circle(lat, lon, radius_m)

    async def _geo_source(_city: str, _zone: str) -> GeoResult:
        return GeoResult(lat=lat, lon=lon, bbox=bbox)

    return citta, zona, _geo_source


async def resolve_zone(citta: str, zona: str) -> tuple[str, str, GeoSource]:
    """(citta, zona) + a GeoSource for the pair of text fields.

    The area is the bounding box that Nominatim returns for "zona, citta", with the
    minimum floor of :func:`~crime_risk_analyzer.geocoding.geocode_zone` — not
    the current radius around the geocoded point: it is the historical behaviour
    of text search, already tuned, and not a new behaviour.

    Labels: they are (citta, zona) AS TYPED (already cleaned by the contract), not
    the reverse geocode of the point as in the circle. The reason is context
    reconstruction: when ``zone_context_cache`` has expired or evicted it,
    ``/analyze/narrativa`` and ``/analyze/poi`` rebuild it by redoing
    ``geocode_zone`` on the labels received from the client. With the typed text
    you get back to the SAME area, deterministically; with a reverse-geocode
    label you would end up on a different area (or none), hence a 409. In the
    circle that path does not exist anyway — there is no text to search — and
    the label stays cosmetic.

    It does not reopen the untrusted surface: lengths are bounded by the
    contract, ``zona`` is normalised as external data before the zone prompt
    (:func:`~crime_risk_analyzer.rag.generation.build_context_str`) and ``citta``
    is in the per-POI prompt. And no second call to Nominatim.

    Args:
        citta: City typed by the user (e.g. ``"Roma"``).
        zona: Zone/neighbourhood typed by the user (e.g. ``"Colosseo"``).

    Returns:
        Tuple (citta, zona, geo_source), same contract as :func:`resolve_circle`.

    Raises:
        ZoneNotFoundError: zone not found in the city or without a bounding box.
        AreaTooLargeError: the area exceeds the same cap as the circle (#497).
        GeocodingError: Nominatim unreachable.
    """
    geo = await run_in_threadpool(geocode_zone, zona, citta)
    check_area_size(geo, zona)

    async def _geo_source(_city: str, _zone: str) -> GeoResult:
        return geo

    return citta, zona, _geo_source


async def capped_zone_geo_source(citta: str, zona: str) -> GeoResult:
    """``GeoSource`` for the cold-cache rebuild of the narrative routes (#497).

    Same geocode and same area cap as :func:`resolve_zone`: without it a narrative
    request on a cold cache would query Overpass on an area that ``/analyze``
    would have refused. Kept out of ``retrieve`` so the evaluation harness, which
    geocodes fixed zones, is not capped.
    """
    geo = await run_in_threadpool(geocode_zone, zona, citta)
    return check_area_size(geo, zona)
