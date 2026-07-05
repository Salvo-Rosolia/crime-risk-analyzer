from __future__ import annotations

from pathlib import Path

import pytest

from crime_risk_analyzer.eval import city_agnostic as ca
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.overpass_client import Poi


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


def test_city_slug_normalises() -> None:
    assert ca.city_slug("Piazza Garibaldi") == "piazza-garibaldi"


def test_capture_path_under_snapshots(tmp_path: Path) -> None:
    p = ca.capture_path(tmp_path, "Roma")
    assert p == tmp_path / "city_agnostic" / "snapshots" / "roma.json"


def test_save_and_load_capture_roundtrip(tmp_path: Path) -> None:
    capture = ca.CityCapture(
        citta="Roma",
        zona="Colosseo",
        lat=41.89,
        lon=12.49,
        bbox=(41.0, 12.0, 41.5, 12.5),
        switch_ms=900,
        pois=[_poi()],
    )
    path = ca.capture_path(tmp_path, "Roma")
    ca.save_capture(path, capture)
    loaded = ca.load_capture(path)
    assert loaded == capture


async def test_capture_city_times_and_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        return {
            "lat": 41.89,
            "lon": 12.49,
            "bbox": Bbox(41.0, 12.0, 41.5, 12.5),
        }

    monkeypatch.setattr(ca, "geocode_zone", _fake_geocode)

    async def _fake_source(bbox: Bbox, citta: str) -> list[Poi]:
        return [_poi()]

    capture = await ca.capture_city("Roma", "Colosseo", poi_source=_fake_source)
    assert capture.citta == "Roma"
    assert capture.zona == "Colosseo"
    assert capture.bbox == (41.0, 12.0, 41.5, 12.5)
    assert capture.pois == [_poi()]
    assert capture.switch_ms >= 0


@pytest.mark.integration
async def test_capture_city_live_roma() -> None:
    """Capture live reale su una città garantita (skip default; -m integration)."""
    capture = await ca.capture_city("Roma", "Colosseo")
    assert capture.pois
    assert ca.boundary_ok(capture.bbox)
