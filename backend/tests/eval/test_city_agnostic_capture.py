from __future__ import annotations

from pathlib import Path

import pytest
from geopy.exc import GeocoderServiceError  # pyright: ignore[reportMissingTypeStubs]

from crime_risk_analyzer.eval import city_agnostic as ca
from crime_risk_analyzer.eval.geometry import CityBoundary
from crime_risk_analyzer.geocoding import GeocodingError, ZoneNotFoundError
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.overpass_client import OverpassError, Poi

_BOUNDARY = CityBoundary(
    polygons=[[[(11.0, 40.0), (13.0, 40.0), (13.0, 42.0), (11.0, 42.0)]]]
)


def _poi() -> Poi:
    return {
        "id": "1",
        "name": "Banca",
        "lat": 41.0,
        "lon": 12.0,
        "osm_tags": "amenity=bank",
        "terminus_class": "Bank",
        "citta": "Roma",
    }


def _fake_boundary(citta: str) -> CityBoundary:
    return _BOUNDARY


class _FakeLocation:
    """Doppio minimale di ``geopy.location.Location`` per i test di boundary."""

    def __init__(self, raw: dict[str, object]) -> None:
        self.raw = raw


class _FakeGeolocator:
    """Doppio minimale di ``Nominatim`` per i test di ``fetch_city_boundary``."""

    def __init__(
        self,
        result: _FakeLocation | None = None,
        *,
        raise_service_error: bool = False,
    ) -> None:
        self._result = result
        self._raise_service_error = raise_service_error

    def geocode(self, query: str, geometry: str = "geojson") -> _FakeLocation | None:
        if self._raise_service_error:
            raise GeocoderServiceError("nominatim non raggiungibile")
        return self._result


def _capture(pois: list[Poi] | None = None) -> ca.CityCapture:
    return ca.CityCapture(
        citta="Roma",
        zona="Colosseo",
        lat=41.89,
        lon=12.49,
        bbox=(41.0, 12.0, 41.5, 12.5),
        switch_ms=900,
        pois=pois or [_poi()],
        boundary=_BOUNDARY,
    )


def test_city_slug_normalises() -> None:
    assert ca.city_slug("Piazza Garibaldi") == "piazza-garibaldi"


def test_capture_path_under_snapshots(tmp_path: Path) -> None:
    p = ca.capture_path(tmp_path, "Roma")
    assert p == tmp_path / "city_agnostic" / "snapshots" / "roma.json"


def test_save_and_load_outcome_roundtrip(tmp_path: Path) -> None:
    outcome = ca.CaptureOutcome(
        status="ok", citta="Roma", zona="Colosseo", capture=_capture()
    )
    path = ca.capture_path(tmp_path, "Roma")
    ca.save_outcome(path, outcome)
    assert ca.load_outcome(path) == outcome


async def test_capture_city_times_and_fetches_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        return {"lat": 41.89, "lon": 12.49, "bbox": Bbox(41.0, 12.0, 41.5, 12.5)}

    monkeypatch.setattr(ca, "geocode_zone", _fake_geocode)

    async def _fake_source(bbox: Bbox, citta: str) -> list[Poi]:
        return [_poi()]

    capture = await ca.capture_city(
        "Roma", "Colosseo", poi_source=_fake_source, boundary_source=_fake_boundary
    )
    assert capture.citta == "Roma"
    assert capture.bbox == (41.0, 12.0, 41.5, 12.5)
    assert capture.pois == [_poi()]
    assert capture.switch_ms >= 0
    assert capture.boundary == _BOUNDARY


def test_fetch_city_boundary_returns_boundary_for_valid_polygon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    geojson = {
        "type": "Polygon",
        "coordinates": [
            [[11.0, 40.0], [13.0, 40.0], [13.0, 42.0], [11.0, 42.0], [11.0, 40.0]]
        ],
    }
    location = _FakeLocation({"geojson": geojson})
    monkeypatch.setattr(ca, "_boundary_geolocator", lambda: _FakeGeolocator(location))

    boundary = ca.fetch_city_boundary("Roma")

    assert boundary.polygons


def test_fetch_city_boundary_raises_zone_not_found_when_location_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ca, "_boundary_geolocator", lambda: _FakeGeolocator(None))

    with pytest.raises(ZoneNotFoundError):
        ca.fetch_city_boundary("Atlantide")


def test_fetch_city_boundary_raises_geocoding_error_on_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ca, "_boundary_geolocator", lambda: _FakeGeolocator(raise_service_error=True)
    )

    with pytest.raises(GeocodingError):
        ca.fetch_city_boundary("Roma")


def test_fetch_city_boundary_raises_zone_not_found_when_geojson_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location = _FakeLocation({})
    monkeypatch.setattr(ca, "_boundary_geolocator", lambda: _FakeGeolocator(location))

    with pytest.raises(ZoneNotFoundError):
        ca.fetch_city_boundary("Roma")


def test_fetch_city_boundary_raises_zone_not_found_for_non_polygon_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    geojson = {"type": "Point", "coordinates": [12.0, 41.0]}
    location = _FakeLocation({"geojson": geojson})
    monkeypatch.setattr(ca, "_boundary_geolocator", lambda: _FakeGeolocator(location))

    with pytest.raises(ZoneNotFoundError):
        ca.fetch_city_boundary("Torino")


async def test_capture_roster_isolates_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        if citta == "Napoli":
            raise ZoneNotFoundError("zona non trovata")
        return {"lat": 41.0, "lon": 12.0, "bbox": Bbox(41.0, 12.0, 41.5, 12.5)}

    monkeypatch.setattr(ca, "geocode_zone", _fake_geocode)

    async def _fake_source(bbox: Bbox, citta: str) -> list[Poi]:
        return [_poi()]

    roster = (ca.RosterCity("Roma", "Colosseo"), ca.RosterCity("Napoli", "Garibaldi"))
    await ca.capture_roster(
        roster, tmp_path, poi_source=_fake_source, boundary_source=_fake_boundary
    )

    roma = ca.load_outcome(ca.capture_path(tmp_path, "Roma"))
    napoli = ca.load_outcome(ca.capture_path(tmp_path, "Napoli"))
    assert roma.status == "ok"
    assert roma.capture is not None
    assert napoli.status == "failed"
    assert napoli.error_type == "ZoneNotFoundError"
    assert napoli.capture is None


async def test_capture_roster_continues_after_failure_precedes_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """M3: una città che fallisce non deve far sparire quella successiva."""

    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        if citta == "Napoli":
            raise ZoneNotFoundError("zona non trovata")
        return {"lat": 41.0, "lon": 12.0, "bbox": Bbox(41.0, 12.0, 41.5, 12.5)}

    monkeypatch.setattr(ca, "geocode_zone", _fake_geocode)

    async def _fake_source(bbox: Bbox, citta: str) -> list[Poi]:
        return [_poi()]

    roster = (ca.RosterCity("Napoli", "Garibaldi"), ca.RosterCity("Roma", "Colosseo"))
    await ca.capture_roster(
        roster, tmp_path, poi_source=_fake_source, boundary_source=_fake_boundary
    )

    napoli = ca.load_outcome(ca.capture_path(tmp_path, "Napoli"))
    roma = ca.load_outcome(ca.capture_path(tmp_path, "Roma"))
    assert napoli.status == "failed"
    assert roma.status == "ok"
    assert roma.capture is not None


async def test_capture_roster_isolates_overpass_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        return {"lat": 41.0, "lon": 12.0, "bbox": Bbox(41.0, 12.0, 41.5, 12.5)}

    monkeypatch.setattr(ca, "geocode_zone", _fake_geocode)

    async def _boom(bbox: Bbox, citta: str) -> list[Poi]:
        raise OverpassError("overpass giù")

    await ca.capture_roster(
        (ca.RosterCity("Roma", "Colosseo"),), tmp_path,
        poi_source=_boom, boundary_source=_fake_boundary,
    )
    roma = ca.load_outcome(ca.capture_path(tmp_path, "Roma"))
    assert roma.status == "failed"
    assert roma.error_type == "OverpassError"


@pytest.mark.integration
async def test_capture_city_live_roma() -> None:
    """Capture live reale su una città garantita (skip default; -m integration)."""
    capture = await ca.capture_city("Roma", "Colosseo")
    assert capture.pois
    assert ca.bbox_valid(capture.bbox)
    assert capture.boundary.polygons
