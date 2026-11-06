"""Route level: the zone cache is per session (#495).

Two sessions share the example (or default) set id and get the SAME reverse-geocoded
label for two DIFFERENT circles. Each must still get its own narrative (no
cross-session 409 ``contesto_disallineato``), and a reset or expiry of one session
must not empty the cache of the other.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer import area_search, zone_context_cache
from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.llm.client import LLMResponse, get_llm_client
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.rag import retrieval
from crime_risk_analyzer.sources import routes
from crime_risk_analyzer.sources.context import current_executor, default_set
from crime_risk_analyzer.sources.session import SessionStore
from tests.eval._doubles import FakeProfiler, make_poi

SID_A = "session-a-0000000000"
SID_B = "session-b-0000000000"

_CIRCLE_A: dict[str, object] = {
    "center": {"lat": 41.89, "lon": 12.49},
    "radius_m": 2000.0,
}
_CIRCLE_B: dict[str, object] = {
    "center": {"lat": 45.46, "lon": 9.19},
    "radius_m": 2000.0,
}

_BANK = PoiRiskProfile(
    ontology_class="Bank",
    hazards=["Bank_robbery"],
    vulnerabilities=["Area_away_from_the_town"],
    sparql_paths=["Bank → havingHazard → Bank_robbery"],
)


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class _LLM:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        return LLMResponse(
            text="Sintesi.\n\n[ONTOLOGIA]\nRischio rapina.\n",
            llm_used="test-model",
            tokens_input=5,
            tokens_output=8,
            cache_hit=False,
            temperature=0.2,
            seed=42,
            prompt_hash="h",
        )


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def store(clock: _Clock) -> SessionStore:
    return SessionStore(ttl_seconds=100, max_sessions=4, clock=clock)


@pytest.fixture
def client(
    store: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    zone_context_cache.clear()

    def _reverse(lat: float, lon: float) -> tuple[str, str]:
        return ("Roma", "Colosseo")  # same label for both circles

    async def _fetch(
        bbox: Bbox, city: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        # Different POIs for the two circles: different fingerprints.
        tag = "b" if bbox.min_lat > 45 else "a"
        return [make_poi(id=f"node/{tag}", name=f"Sportello {tag}", citta=city)]

    def _geocode(zona: str, citta: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    monkeypatch.setattr(area_search, "reverse_geocode_label", _reverse)
    monkeypatch.setattr(retrieval, "geocode_zone", _geocode)
    monkeypatch.setattr(retrieval, "fetch_pois", _fetch)

    app = create_app()
    app.dependency_overrides[routes.get_sessions] = lambda: store
    app.dependency_overrides[current_executor] = lambda: FakeProfiler({"Bank": _BANK})
    app.dependency_overrides[get_llm_client] = lambda: _LLM()
    yield TestClient(app, raise_server_exceptions=False)
    zone_context_cache.clear()


def _use_shared_example_set(store: SessionStore) -> None:
    """Both sessions on the example set, which has ONE id shared by all sessions."""
    shared = dataclasses.replace(default_set(), id="example", kind="example")
    store.activate(SID_A, shared, [])
    store.activate(SID_B, shared, [])


def _analyze(client: TestClient, sid: str, circle: dict[str, object]) -> str:
    resp = cast(
        httpx.Response,
        client.post("/analyze", json=circle, headers={"X-Session-Id": sid}),  # pyright: ignore[reportUnknownMemberType]
    )
    assert resp.status_code == 200
    return str(resp.json()["contesto_hash"])


def _narrative(client: TestClient, sid: str, context_hash: str) -> httpx.Response:
    return cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/narrativa",
            json={"citta": "Roma", "zona": "Colosseo", "contesto_hash": context_hash},
            headers={"X-Session-Id": sid},
        ),
    )


@pytest.mark.parametrize("shared_set", ["example", "default"])
def test_two_sessions_same_label_different_circles_no_cross_409(
    client: TestClient, store: SessionStore, shared_set: str
) -> None:
    if shared_set == "example":
        _use_shared_example_set(store)
    hash_a = _analyze(client, SID_A, _CIRCLE_A)
    hash_b = _analyze(client, SID_B, _CIRCLE_B)
    assert hash_a != hash_b

    assert _narrative(client, SID_A, hash_a).status_code == 200
    assert _narrative(client, SID_B, hash_b).status_code == 200


def test_reset_of_one_session_keeps_the_cache_of_the_other(
    client: TestClient, store: SessionStore
) -> None:
    _use_shared_example_set(store)
    _analyze(client, SID_A, _CIRCLE_A)
    hash_b = _analyze(client, SID_B, _CIRCLE_B)

    reset = cast(
        httpx.Response,
        client.delete("/sources", headers={"X-Session-Id": SID_A}),  # pyright: ignore[reportUnknownMemberType]
    )
    assert reset.status_code == 200

    # Session B's slot survives: a purged slot would be rebuilt from the
    # (patched) circle-A geocode and fail with 409.
    assert _narrative(client, SID_B, hash_b).status_code == 200


def test_expiry_of_one_session_keeps_the_cache_of_the_other(
    client: TestClient, store: SessionStore, clock: _Clock
) -> None:
    _use_shared_example_set(store)
    _analyze(client, SID_A, _CIRCLE_A)
    clock.t = 60.0
    hash_b = _analyze(client, SID_B, _CIRCLE_B)  # renews B's TTL to 160

    clock.t = 120.0  # A (expires at 100) is gone, B is alive
    status = cast(
        httpx.Response,
        client.get("/sources", headers={"X-Session-Id": SID_A}),  # pyright: ignore[reportUnknownMemberType]
    )
    assert status.json()["stato"] == "scaduto"

    assert _narrative(client, SID_B, hash_b).status_code == 200
