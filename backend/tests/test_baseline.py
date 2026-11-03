"""Tests for the POST /analyze/baseline endpoint (#90)."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer import area_search
from crime_risk_analyzer.geocoding import GeoResult, ZoneNotFoundError
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.orchestrator import run_baseline
from crime_risk_analyzer.overpass_client import OverpassError, Poi
from crime_risk_analyzer.rag import retrieval
from crime_risk_analyzer.sources.context import current_executor

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
    """Patch only the I/O that the circle path (#318) really goes through.

    With the circle ``geocode_zone`` is not called (it is only called in the
    citta + zona mode): ``resolve_circle`` always passes its own ``geo_source``.
    The citta/zona label comes from ``area_search.reverse_geocode_label`` (reverse
    geocode of the center); the bbox comes from ``bbox_from_circle`` (pure, no
    I/O) -- so only the label has to be simulated here.
    """
    monkeypatch.setattr(area_search, "reverse_geocode_label", _fake_reverse_geocode)

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois(citta)

    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[current_executor] = lambda: _FakeProfiler()
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
    """#318: the ``citta`` in the response is the one from the reverse geocode of the
    center.

    There is no allowlist anymore (already removed by #191) nor a ``citta`` field
    in the request: it checks that ``center.lat``/``center.lon`` reach
    ``reverse_geocode_label`` and that the returned label ends up in the response.
    """
    seen: list[tuple[float, float]] = []

    def _recording_reverse(lat: float, lon: float) -> tuple[str, str]:
        seen.append((lat, lon))
        return ("Acireale", "Centro")

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois(citta)

    monkeypatch.setattr(area_search, "reverse_geocode_label", _recording_reverse)
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
    """radius_m outside [search_radius_min_m, search_radius_max_m] -> 422 (#318).

    Pydantic validation before any I/O, like the old ``max_length=100`` limit on
    ``citta`` (removed together with the field): a malformed body must reach
    neither the reverse geocode nor Overpass.
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


def _pois_by_radius(citta: str) -> list[Poi]:
    """One POI at the exact center of the request + one more than a km away (#318)."""
    return [
        {
            "id": "vicino",
            "name": "Banca A",
            "lat": 41.89,
            "lon": 12.49,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": citta,
        },
        {
            "id": "lontano",
            "name": "Bar Roma",
            "lat": 41.90,
            "lon": 12.50,
            "osm_tags": "amenity=bar",
            "terminus_class": "GenericUrbanPOI",
            "citta": citta,
        },
    ]


def test_baseline_radius_m_really_reaches_the_geospatial_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#318: proves at the HTTP boundary that ``radius_m`` filters the POIs, not just
    that it is validated by the ``field_validator`` (twin of
    ``test_analyze_radius_m_really_reaches_the_geospatial_filter``).

    Without ``radius_m=request.radius_m`` wired from ``main.py`` into
    ``run_baseline``, the whole suite would pass anyway. The center of the request
    coincides with ``Banca A`` (distance ~0 m) while ``Bar Roma`` is over a km
    away: a 150 m radius (the allowed minimum) must exclude the latter from the
    response.
    """
    monkeypatch.setattr(area_search, "reverse_geocode_label", _fake_reverse_geocode)

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois_by_radius(citta)

    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 150.0},
        ),
    )
    assert resp.status_code == 200
    assert [p["id"] for p in resp.json()["poi"]] == ["vicino"]


def test_baseline_zone_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """An error while resolving the label (reverse geocode) propagates as a 422.

    The real ``reverse_geocode_label`` never raises (cosmetic fallback, #318):
    this only checks that the central ``ZoneNotFoundError`` handler stays wired
    even behind the new ``resolve_circle``.
    """

    def _raise(lat: float, lon: float) -> tuple[str, str]:
        raise ZoneNotFoundError("zona ignota")

    monkeypatch.setattr(area_search, "reverse_geocode_label", _raise)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 422


def test_baseline_accepts_citta_and_zona(monkeypatch: pytest.MonkeyPatch) -> None:
    """The baseline accepts the same second mode as ``/analyze``.

    The two arms of the ablation must be able to analyze the same area chosen in
    the same way: the bbox comes from ``geocode_zone`` on (zona, citta).
    """
    calls: list[tuple[str, str]] = []

    def _fake_geocode_zone(zona: str, citta: str) -> GeoResult:
        calls.append((zona, citta))
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    monkeypatch.setattr(area_search, "geocode_zone", _fake_geocode_zone)
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline",
            json={"citta": "Roma", "zona": "Colosseo"},
        ),
    )
    assert resp.status_code == 200
    assert calls == [("Colosseo", "Roma")]
    assert resp.json()["citta"] == "Roma"


def test_baseline_overpass_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(area_search, "reverse_geocode_label", _fake_reverse_geocode)

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
    monkeypatch.setattr(area_search, "reverse_geocode_label", _fake_reverse_geocode)

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
    # tipo_poi is now WIRED server-side (#119): without a filter both classes, with
    # tipo_poi=Bank only the POIs of TERMINUS class "Bank" (no GenericUrbanPOI).
    assert [p["terminus_class"] for p in base.json()["poi"]] == [
        "Bank",
        "GenericUrbanPOI",
    ]
    assert [p["terminus_class"] for p in filtered.json()["poi"]] == ["Bank"]
    assert [p["name"] for p in filtered.json()["poi"]] == ["Banca A"]
    assert [m["poi"] for m in filtered.json()["risk_models"]] == ["Banca A"]


@pytest.mark.parametrize("tipo_poi", ["bank", "  BANK ", "Banca", "banca"])
def test_baseline_tipo_poi_is_normalized_to_canonical_class(
    monkeypatch: pytest.MonkeyPatch, tipo_poi: str
) -> None:
    """#143: the free-text field of the UI must not give a silent empty list.

    Uppercase, edge spaces and the IT label reach the filter as the canonical
    TERMINUS class.
    """
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline",
            json={
                "center": {"lat": 41.89, "lon": 12.49},
                "radius_m": 2000.0,
                "tipo_poi": tipo_poi,
            },
        ),
    )
    assert resp.status_code == 200
    assert [p["terminus_class"] for p in resp.json()["poi"]] == ["Bank"]


@pytest.mark.parametrize("tipo_poi", ["", "   "])
def test_baseline_blank_tipo_poi_is_no_filter(
    monkeypatch: pytest.MonkeyPatch, tipo_poi: str
) -> None:
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline",
            json={
                "center": {"lat": 41.89, "lon": 12.49},
                "radius_m": 2000.0,
                "tipo_poi": tipo_poi,
            },
        ),
    )
    assert resp.status_code == 200
    assert [p["terminus_class"] for p in resp.json()["poi"]] == [
        "Bank",
        "GenericUrbanPOI",
    ]


def test_baseline_unknown_tipo_poi_is_422_before_any_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#143: unknown type -> 422 in the domain error format, not [].

    The refusal arrives before geocoding and Overpass: an invalid input costs no
    network calls.
    """

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("nessun I/O atteso su tipo_poi invalido")

    monkeypatch.setattr(area_search, "reverse_geocode_label", _boom)
    monkeypatch.setattr(retrieval, "fetch_pois", _boom)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/baseline",
            json={
                "center": {"lat": 41.89, "lon": 12.49},
                "radius_m": 2000.0,
                "tipo_poi": " xyz ",
            },
        ),
    )
    assert resp.status_code == 422
    assert resp.json() == {
        "detail": {
            "errore": "tipo_poi_non_riconosciuto",
            "messaggio": "Tipo POI non riconosciuto: 'xyz'",
        }
    }


async def test_run_baseline_threads_geo_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#169: geo_source passed to run_baseline reaches retrieve (no geocode)."""

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
