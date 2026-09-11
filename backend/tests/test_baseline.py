"""Test endpoint POST /analyze/baseline (#90)."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer import circle_search
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


def _fake_reverse_geocode(lat: float, lon: float) -> tuple[str, str]:
    return ("Roma", "Trastevere")


def _patch_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patcha la sola I/O che il nuovo path a cerchio (#318) attraversa davvero.

    ``geocode_zone`` non e' piu' chiamato da ``/analyze``/``/analyze/baseline``:
    ``resolve_circle`` passa sempre un ``geo_source`` proprio. La label
    citta'/zona arriva da ``circle_search.reverse_geocode_label`` (reverse
    geocode del centro); il bbox da ``bbox_from_circle`` (puro, nessun I/O) —
    solo la label va quindi simulata qui.
    """
    monkeypatch.setattr(circle_search, "reverse_geocode_label", _fake_reverse_geocode)

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois(citta)

    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_executor] = lambda: _FakeProfiler()
    return TestClient(app, raise_server_exceptions=False)


def test_baseline_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["narrativa"] == ""
    assert body["llm_used"] == ""
    assert body["fallback"] is False
    assert [p["confidence"] for p in body["poi"]] == ["verificato", None]
    assert body["risk_models"][0]["poi"] == "Banca A"


def test_baseline_reports_reverse_geocoded_city(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#318: la ``citta'`` in risposta e' quella del reverse geocode del centro.

    Non c'e' piu' un'allowlist (gia' rimossa da #191) ne' un campo ``citta`` in
    richiesta: verifica che ``center.lat``/``center.lon`` raggiungano
    ``reverse_geocode_label`` e che l'etichetta restituita finisca in risposta.
    """
    seen: list[tuple[float, float]] = []

    def _recording_reverse(lat: float, lon: float) -> tuple[str, str]:
        seen.append((lat, lon))
        return ("Acireale", "Centro")

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois(citta)

    monkeypatch.setattr(circle_search, "reverse_geocode_label", _recording_reverse)
    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline",
            json={"center": {"lat": 37.61, "lon": 15.16}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["citta"] == "Acireale"
    assert seen == [(37.61, 15.16)]


def test_baseline_rejects_out_of_range_radius(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """radius_m fuori da [search_radius_min_m, search_radius_max_m] -> 422 (#318).

    Validazione Pydantic pre-I/O, come il vecchio limite ``max_length=100`` su
    ``citta'`` (rimosso insieme al campo): il body malformato non deve
    raggiungere ne' il reverse geocode ne' Overpass.
    """
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 50_000.0},
        ),
    )
    assert resp.status_code == 422


def test_baseline_zone_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un errore alla risoluzione dell'etichetta (reverse geocode) propaga a 422.

    ``reverse_geocode_label`` reale non solleva mai (fallback cosmetico, #318):
    questo verifica solo che l'handler centrale di ``ZoneNotFoundError`` resti
    cablato anche dietro il nuovo ``resolve_circle``.
    """

    def _raise(lat: float, lon: float) -> tuple[str, str]:
        raise ZoneNotFoundError("zona ignota")

    monkeypatch.setattr(circle_search, "reverse_geocode_label", _raise)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 422


def test_baseline_overpass_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(circle_search, "reverse_geocode_label", _fake_reverse_geocode)

    async def _raise_fetch(*args: object, **kwargs: object) -> list[Poi]:
        raise OverpassError("overpass giu'")

    monkeypatch.setattr(retrieval, "fetch_pois", _raise_fetch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 503


def test_baseline_zero_pois(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(circle_search, "reverse_geocode_label", _fake_reverse_geocode)

    async def _fake_fetch_empty(*args: object, **kwargs: object) -> list[Poi]:
        return []

    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch_empty)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["poi"] == []
    assert body["risk_models"] == []
    assert body["confidence_summary"] == {
        "verificato": 0,
        "da_confermare": 0,
    }
    assert body["narrativa"] == ""
    assert body["fallback"] is False


def test_baseline_filters_by_tipo_poi(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    client = _client()
    base = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    filtered = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline",
            json={
                "center": {"lat": 41.89, "lon": 12.49},
                "radius_m": 2000.0,
                "tipo_poi": "Bank",
            },
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
