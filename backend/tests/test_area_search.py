"""Tests for the area resolvers: drawn circle and citta + zona pair."""

from __future__ import annotations

import pytest

from crime_risk_analyzer import area_search
from crime_risk_analyzer.geocoding import GeoResult, ZoneNotFoundError
from crime_risk_analyzer.models.geo import Bbox, bbox_from_circle


@pytest.mark.asyncio
async def test_resolve_circle_returns_label_and_geo_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_circle returns (citta, zona, geo_source).

    The geo_source ignores the arguments and always returns the same GeoResult.
    """

    def _fake_reverse_geocode(lat: float, lon: float) -> tuple[str, str]:
        return ("Roma", "Trastevere")

    monkeypatch.setattr(area_search, "reverse_geocode_label", _fake_reverse_geocode)
    citta, zona, geo_source = await area_search.resolve_circle(41.89, 12.47, 500.0)
    assert citta == "Roma"
    assert zona == "Trastevere"

    # geo_source ignores the arguments and always returns the same GeoResult
    geo = await geo_source("qualsiasi", "cosa")
    assert geo["lat"] == 41.89
    assert geo["lon"] == 12.47
    assert geo["bbox"] == bbox_from_circle(41.89, 12.47, 500.0)


def _fake_geocode_zone(zona: str, citta: str) -> GeoResult:
    return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))


@pytest.mark.asyncio
async def test_resolve_zone_returns_label_and_geo_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The citta + zona mode produces the same contract as the circle.

    The two search modes coexist and the user uses one or the other: downstream
    the rest of the pipeline must not know which one was used, so both return
    (citta, zona, geo_source). Here the bbox comes from Nominatim
    (`geocode_zone`), not from the center+radius computation.
    """
    calls: list[tuple[str, str]] = []

    def _recording_geocode_zone(zona: str, citta: str) -> GeoResult:
        calls.append((zona, citta))
        return _fake_geocode_zone(zona, citta)

    monkeypatch.setattr(area_search, "geocode_zone", _recording_geocode_zone)

    _, _, geo_source = await area_search.resolve_zone("Roma", "Colosseo")

    assert calls == [("Colosseo", "Roma")]
    geo = await geo_source("qualsiasi", "cosa")
    assert geo["bbox"] == (41.88, 12.48, 41.90, 12.50)
    assert geo["lat"] == 41.89
    assert geo["lon"] == 12.49


@pytest.mark.asyncio
async def test_resolve_zone_labels_are_the_typed_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The labels are the typed (citta, zona), and no reverse geocode starts.

    The phase 2 routes (``/analyze/narrativa``, ``/analyze/poi``) rebuild the
    expired context by redoing ``geocode_zone`` on the labels: only the typed text
    leads back to the SAME area. A label from the reverse geocode would give a
    different area, hence a 409.
    """

    def _forbidden_reverse(lat: float, lon: float) -> tuple[str, str]:
        raise AssertionError("zone mode must not call the reverse geocoder")

    monkeypatch.setattr(area_search, "geocode_zone", _fake_geocode_zone)
    monkeypatch.setattr(area_search, "reverse_geocode_label", _forbidden_reverse)

    citta, zona, _ = await area_search.resolve_zone("Roma", "Colosseo")

    assert (citta, zona) == ("Roma", "Colosseo")


@pytest.mark.asyncio
async def test_resolve_zone_propagates_the_zone_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A nonexistent zone stays an error, not a fallback area.

    Intended asymmetry with the circle: there the reverse geocode is cosmetic and
    never blocks, here the geocode DETERMINES the analyzed area -- failing silently
    would mean analyzing a random place.
    """

    def _raise(zona: str, citta: str) -> GeoResult:
        raise ZoneNotFoundError(f"Zona non trovata: {zona!r} in {citta!r}")

    monkeypatch.setattr(area_search, "geocode_zone", _raise)

    with pytest.raises(ZoneNotFoundError):
        await area_search.resolve_zone("Roma", "Atlantide")
