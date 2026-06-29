"""Test endpoint POST /analyze/baseline (#90)."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer.geocoding import ZoneNotFoundError
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
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
    assert [p["confidence"] for p in body["poi"]] == ["confermato", "speculativo"]
    assert body["risk_models"][0]["poi"] == "Banca A"


def test_baseline_city_not_supported() -> None:
    resp = cast(
        httpx.Response,
        _client().post("/analyze/baseline", json={"citta": "Atlantide", "zona": "X"}),  # pyright: ignore[reportUnknownMemberType]
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["errore"] == "citta_non_supportata"


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
        "confermato": 0,
        "plausibile": 0,
        "speculativo": 0,
    }
    assert body["narrativa"] == ""
    assert body["fallback"] is False


def test_baseline_accepts_tipo_poi(monkeypatch: pytest.MonkeyPatch) -> None:
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
    # tipo_poi e' IGNORATO server-side: stesso identico set di POI (incluso il
    # GenericUrbanPOI), non solo "accettato".
    assert filtered.json()["poi"] == base.json()["poi"]
    classes = [p["terminus_class"] for p in filtered.json()["poi"]]
    assert classes == ["Bank", "GenericUrbanPOI"]
