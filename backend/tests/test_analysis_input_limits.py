"""Input checks of the analysis routes and area cap in city/zone mode (#497)."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from crime_risk_analyzer import area_search, geocoding
from crime_risk_analyzer.analyze_narrative import ZoneNarrativeRequest
from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.errors import register_exception_handlers
from crime_risk_analyzer.geocoding import (
    AreaTooLargeError,
    GeoResult,
    check_area_size,
    geocode_zone,
)
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.models.geo import Bbox, bbox_from_circle, bbox_side_m
from crime_risk_analyzer.poi_narrative import PoiNarrativeRequest
from tests.test_geocoding import (
    _FakeGeocoder,  # pyright: ignore[reportPrivateUsage]
    _FakeLocation,  # pyright: ignore[reportPrivateUsage]
    _patch_geocoder,  # pyright: ignore[reportPrivateUsage]
)

_HASH = "0" * 64


@pytest.fixture(autouse=True)
def _fresh_state() -> None:  # pyright: ignore[reportUnusedFunction]
    get_settings.cache_clear()
    geocoding._CACHE.clear()  # pyright: ignore[reportPrivateUsage]
    geocoding._get_rate_limited_call.cache_clear()  # pyright: ignore[reportPrivateUsage]


# --- strip + non-empty on the narrative requests ---


def test_zone_narrative_request_strips_city_and_zone() -> None:
    req = ZoneNarrativeRequest(
        citta="  Roma ", zona="\tColosseo\n", contesto_hash=_HASH
    )
    assert (req.citta, req.zona) == ("Roma", "Colosseo")


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_zone_narrative_request_rejects_blank_city_or_zone(blank: str) -> None:
    with pytest.raises(ValidationError):
        ZoneNarrativeRequest(citta=blank, zona="Colosseo", contesto_hash=_HASH)
    with pytest.raises(ValidationError):
        ZoneNarrativeRequest(citta="Roma", zona=blank, contesto_hash=_HASH)


def test_zone_narrative_request_cap_is_measured_after_strip() -> None:
    req = ZoneNarrativeRequest(
        citta=" " * 50 + "Roma", zona="z" * 200, contesto_hash=_HASH
    )
    assert req.citta == "Roma"
    with pytest.raises(ValidationError):
        ZoneNarrativeRequest(citta="c" * 101, zona="z", contesto_hash=_HASH)


def test_poi_narrative_request_strips_and_rejects_blank() -> None:
    req = PoiNarrativeRequest(
        citta=" Roma ", zona=" Colosseo ", poi_id="node/1", contesto_hash=_HASH
    )
    assert (req.citta, req.zona) == ("Roma", "Colosseo")
    for field in ("citta", "zona"):
        data = {"citta": "Roma", "zona": "Colosseo", "poi_id": "node/1"}
        data[field] = "   "
        with pytest.raises(ValidationError):
            PoiNarrativeRequest(**data, contesto_hash=_HASH)


@pytest.mark.parametrize("route", ["/analyze/narrativa", "/analyze/poi"])
def test_blank_city_is_422_before_any_geocoding(
    monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    def _forbidden(*_a: object, **_k: object) -> None:
        raise AssertionError("geocoding must not run on a blank input")

    monkeypatch.setattr(geocoding, "geocode_zone", _forbidden)
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _forbidden)
    body: dict[str, str] = {"citta": "  ", "zona": "Colosseo", "contesto_hash": _HASH}
    if route == "/analyze/poi":
        body["poi_id"] = "node/1"
    client = TestClient(create_app(), raise_server_exceptions=False)
    response = cast(httpx.Response, client.post(route, json=body))  # pyright: ignore[reportUnknownMemberType]
    assert response.status_code == 422


# --- area cap in city/zone mode ---


def _huge_city(monkeypatch: pytest.MonkeyPatch) -> None:
    # ~0.5 x 0.5 degrees (~55 km): a whole city, well above the circle cap.
    fake = _FakeGeocoder(
        _FakeLocation(41.9, 12.5, ["41.65", "42.15", "12.25", "12.75"])
    )
    _patch_geocoder(monkeypatch, fake)


def test_bbox_side_m_matches_circle_diameter() -> None:
    bbox = bbox_from_circle(41.9, 12.5, 3000.0)
    height, width = bbox_side_m(bbox)
    assert height == pytest.approx(6000.0, rel=1e-3)
    assert width == pytest.approx(6000.0, rel=1e-3)


def test_check_area_size_rejects_area_above_the_circle_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _huge_city(monkeypatch)
    with pytest.raises(AreaTooLargeError):
        check_area_size(geocode_zone("Roma", "Roma"), "Roma")


def test_check_area_size_accepts_area_within_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeGeocoder(
        _FakeLocation(41.8902, 12.4922, ["41.88", "41.90", "12.48", "12.50"])
    )
    _patch_geocoder(monkeypatch, fake)
    result = geocode_zone("Colosseo", "Roma")
    assert check_area_size(result, "Colosseo") is result


def test_check_area_size_follows_the_configured_radius_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEARCH_RADIUS_MAX_M", "100000")
    get_settings.cache_clear()
    _huge_city(monkeypatch)
    check_area_size(geocode_zone("Roma", "Roma"), "Roma")


def test_geocode_zone_itself_has_no_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """The eval harness calls it directly: unchanged."""
    _huge_city(monkeypatch)
    assert geocode_zone("Roma", "Roma")["bbox"].max_lat == pytest.approx(42.15)


async def test_resolve_zone_applies_the_circle_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _huge_city(monkeypatch)
    with pytest.raises(AreaTooLargeError):
        await area_search.resolve_zone("Roma", "Roma")


def test_area_too_large_is_422_with_its_own_code() -> None:
    from fastapi import FastAPI

    app = FastAPI()
    register_exception_handlers(app)

    async def _boom() -> None:
        raise AreaTooLargeError("area troppo estesa")

    app.add_api_route("/boom", _boom)
    response = cast(
        httpx.Response,
        TestClient(app, raise_server_exceptions=False).get("/boom"),  # pyright: ignore[reportUnknownMemberType]
    )
    assert response.status_code == 422
    assert response.json()["detail"]["errore"] == "area_troppo_estesa"


def test_analyze_zone_mode_too_large_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _huge_city(monkeypatch)
    client = TestClient(create_app(), raise_server_exceptions=False)
    response = cast(
        httpx.Response,
        client.post("/analyze", json={"citta": "Roma", "zona": "Roma"}),  # pyright: ignore[reportUnknownMemberType]
    )
    assert response.status_code == 422
    assert response.json()["detail"]["errore"] == "area_troppo_estesa"


async def test_capped_geo_source_applies_the_same_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _huge_city(monkeypatch)
    with pytest.raises(AreaTooLargeError):
        await area_search.capped_zone_geo_source("Roma", "Roma")


@pytest.mark.parametrize("route", ["/analyze/narrativa", "/analyze/poi"])
def test_cold_cache_rebuild_on_a_huge_area_is_409_without_overpass(
    monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    from crime_risk_analyzer import zone_context_cache
    from crime_risk_analyzer.rag import retrieval

    async def _forbidden(*_a: object, **_k: object) -> None:
        raise AssertionError("Overpass must not be queried")

    monkeypatch.setattr(retrieval, "fetch_pois", _forbidden)
    zone_context_cache.clear()
    _huge_city(monkeypatch)
    body: dict[str, str] = {"citta": "Roma", "zona": "Roma", "contesto_hash": _HASH}
    if route == "/analyze/poi":
        body["poi_id"] = "node/1"
    client = TestClient(create_app(), raise_server_exceptions=False)
    response = cast(httpx.Response, client.post(route, json=body))  # pyright: ignore[reportUnknownMemberType]
    assert response.status_code == 409


def test_bbox_side_m_handles_the_antimeridian() -> None:
    # 179.0 -> -179.0 is 2 degrees of longitude, not -358.
    _, width = bbox_side_m(Bbox(-0.5, 179.0, 0.5, -179.0))
    assert width == pytest.approx(2 * 111_195, rel=1e-2)


def test_check_area_size_rejects_a_huge_bbox_across_the_antimeridian() -> None:
    wide = GeoResult(lat=0.0, lon=180.0, bbox=Bbox(-0.5, 170.0, 0.5, -170.0))
    with pytest.raises(AreaTooLargeError):
        check_area_size(wide, "Fiji")
    narrow = GeoResult(lat=0.0, lon=180.0, bbox=Bbox(-0.01, 179.99, 0.01, -179.99))
    assert check_area_size(narrow, "Fiji") is narrow
