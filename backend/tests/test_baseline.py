"""Test endpoint POST /analyze/baseline (#90)."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer.geocoding import GeoResult, ZoneNotFoundError
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.orchestrator import run_baseline
from crime_risk_analyzer.overpass_client import OverpassError, Poi
from crime_risk_analyzer.rag import retrieval
from crime_risk_analyzer.sparql_module.query_executor import get_executor

_BANK = PoiRiskProfile(
    terminus_class="Bank",
    hazards=["Bank_robbery"],
    sparql_paths=["Bank → havingHazard → Bank_robbery"],
)


class _FakeProfiler:
    def profile(self, terminus_class: str) -> PoiRiskProfile:
        return {"Bank": _BANK}.get(
            terminus_class, PoiRiskProfile(terminus_class=terminus_class)
        )


def _pois(citta: str) -> list[Poi]:
    return [
        {
            "id": "1",
            "name": "Banca A",
            "lat": 41.89,
            "lon": 12.49,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": citta,
        },
        {
            "id": "2",
            "name": "Bar Roma",
            "lat": 41.90,
            "lon": 12.50,
            "osm_tags": "amenity=bar",
            "terminus_class": "GenericUrbanPOI",
            "citta": citta,
        },
    ]


def _patch_io(monkeypatch: pytest.MonkeyPatch) -> None:
    geo: dict[str, object] = {
        "lat": 41.89,
        "lon": 12.49,
        "bbox": Bbox(41.88, 12.48, 41.90, 12.50),
    }

    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        return geo

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois(citta)

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode)
    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_executor] = lambda: _FakeProfiler()
    return TestClient(app, raise_server_exceptions=False)


def test_baseline_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post("/analyze/baseline", json={"citta": "Roma", "zona": "Centro"}),  # pyright: ignore[reportUnknownMemberType]
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["narrativa"] == ""
    assert body["llm_used"] == ""
    assert body["fallback"] is False
    assert [p["confidence"] for p in body["poi"]] == ["verificato", "ipotesi"]
    assert body["risk_models"][0]["poi"] == "Banca A"


def test_baseline_accepts_non_allowlisted_city(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#191: baseline non applica piu' l'allowlist; una citta' fuori lista -> 200."""
    seen: list[tuple[str, str]] = []

    def _recording_geocode(zona: str, citta: str) -> dict[str, object]:
        seen.append((zona, citta))
        return {
            "lat": 37.61,
            "lon": 15.16,
            "bbox": Bbox(37.60, 15.15, 37.62, 15.17),
        }

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois(citta)

    monkeypatch.setattr(retrieval, "geocode_zone", _recording_geocode)
    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline", json={"citta": "Acireale", "zona": "Centro"}
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["citta"] == "Acireale"
    assert seen == [("Centro", "Acireale")]


def test_baseline_rejects_overlong_citta(monkeypatch: pytest.MonkeyPatch) -> None:
    """#191: citta' oltre max_length=100 -> 422 (validazione Pydantic, pre-I/O)."""
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline", json={"citta": "A" * 101, "zona": "Centro"}
        ),
    )
    assert resp.status_code == 422


def test_baseline_zone_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(zona: str, citta: str) -> dict[str, object]:
        raise ZoneNotFoundError("zona ignota")

    monkeypatch.setattr(retrieval, "geocode_zone", _raise)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline", json={"citta": "Roma", "zona": "Nessundove"}
        ),
    )
    assert resp.status_code == 422


def test_baseline_overpass_down(monkeypatch: pytest.MonkeyPatch) -> None:
    geo: dict[str, object] = {
        "lat": 41.89,
        "lon": 12.49,
        "bbox": Bbox(41.88, 12.48, 41.90, 12.50),
    }

    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        return geo

    async def _raise_fetch(*args: object, **kwargs: object) -> list[Poi]:
        raise OverpassError("overpass giu'")

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode)
    monkeypatch.setattr(retrieval, "fetch_pois", _raise_fetch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline", json={"citta": "Roma", "zona": "Centro"}
        ),
    )
    assert resp.status_code == 503


def test_baseline_zero_pois(monkeypatch: pytest.MonkeyPatch) -> None:
    geo: dict[str, object] = {
        "lat": 41.89,
        "lon": 12.49,
        "bbox": Bbox(41.88, 12.48, 41.90, 12.50),
    }

    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        return geo

    async def _fake_fetch_empty(*args: object, **kwargs: object) -> list[Poi]:
        return []

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode)
    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch_empty)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline", json={"citta": "Roma", "zona": "Centro"}
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["poi"] == []
    assert body["risk_models"] == []
    assert body["confidence_summary"] == {
        "verificato": 0,
        "da_confermare": 0,
        "ipotesi": 0,
    }
    assert body["narrativa"] == ""
    assert body["fallback"] is False


def test_baseline_filters_by_tipo_poi(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    client = _client()
    base = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline", json={"citta": "Roma", "zona": "Centro"}
        ),
    )
    filtered = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline",
            json={"citta": "Roma", "zona": "Centro", "tipo_poi": "Bank"},
        ),
    )
    assert base.status_code == 200
    assert filtered.status_code == 200
    # tipo_poi e' ora CABLATO server-side (#119): senza filtro entrambe le classi,
    # con tipo_poi=Bank solo i POI di classe TERMINUS "Bank" (niente GenericUrbanPOI).
    assert [p["terminus_class"] for p in base.json()["poi"]] == [
        "Bank",
        "GenericUrbanPOI",
    ]
    assert [p["terminus_class"] for p in filtered.json()["poi"]] == ["Bank"]
    assert [p["name"] for p in filtered.json()["poi"]] == ["Banca A"]
    assert [m["poi"] for m in filtered.json()["risk_models"]] == ["Banca A"]


async def test_run_baseline_threads_geo_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#169: geo_source passato a run_baseline raggiunge retrieve (nessun geocode)."""

    def _boom_geocode(zona: str, citta: str) -> GeoResult:
        raise AssertionError("geocode_zone non deve essere chiamato con geo_source")

    monkeypatch.setattr(retrieval, "geocode_zone", _boom_geocode)
    seen: list[tuple[str, str]] = []

    async def _geo(citta: str, zona: str) -> GeoResult:
        seen.append((citta, zona))
        return GeoResult(lat=0.0, lon=0.0, bbox=Bbox(0.0, 0.0, 0.0, 0.0))

    async def _pois(bbox: Bbox, citta: str) -> list[Poi]:
        return []

    await run_baseline(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_pois,
        geo_source=_geo,
    )
    assert seen == [("Roma", "Colosseo")]
