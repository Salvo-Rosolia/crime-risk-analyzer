"""The context fingerprint covers the ISTAT data version (#354), offline.

With the switch on the prompt depends on the ISTAT data too: if the data is
updated between phase 1 and the click, ``/analyze/poi`` and
``/analyze/narrativa`` must refuse (409) as for a change of the POIs. Off, the
fingerprint stays the previous one. The "updated" data is simulated by replacing
the version read from :mod:`~crime_risk_analyzer.context_fingerprint`, the only
point from which computation and comparison take it.
"""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer import area_search, context_fingerprint, zone_context_cache
from crime_risk_analyzer.config import Settings, get_settings
from crime_risk_analyzer.context_fingerprint import fingerprint, istat_version_for
from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.istat.data import data_version
from crime_risk_analyzer.llm.client import LLMResponse, get_llm_client
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.orchestrator import run_analysis, run_no_ontology_prompt
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.rag import retrieval
from crime_risk_analyzer.sources.context import current_executor
from tests.eval._doubles import FakeProfiler, make_poi

_POI_ID = "node/1"


class _LLM:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        return LLMResponse(
            text="Sintesi.\n\n[ONTOLOGIA]\nRischio rapina.\n\n[CONTESTO]\nUna banca.\n",
            llm_used="claude-sonnet-4-6",
            tokens_input=5,
            tokens_output=8,
            cache_hit=False,
            temperature=0.2,
            seed=42,
            prompt_hash="h",
        )


def _pois(citta: str) -> list[Poi]:
    return [
        make_poi(id=_POI_ID, lat=41.8900, lon=12.4920, citta=citta),
        make_poi(
            id="node/2",
            name="Liceo Cavour",
            lat=41.8901,
            lon=12.4921,
            osm_tags="amenity=school",
            ontology_class="School",
            citta=citta,
        ),
    ]


async def _geo_source(citta: str, zona: str) -> GeoResult:
    return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))


async def _poi_source(bbox: Bbox, citta: str) -> list[Poi]:
    return _pois(citta)


def _client(monkeypatch: pytest.MonkeyPatch, *, enabled: bool) -> TestClient:
    zone_context_cache.clear()

    def _fake_label(lat: float, lon: float) -> tuple[str, str]:
        return ("Roma", "Colosseo")

    monkeypatch.setattr(area_search, "reverse_geocode_label", _fake_label)

    async def _fetch(bbox: object, citta: str, *a: object, **k: object) -> list[Poi]:
        return _pois(citta)

    monkeypatch.setattr(retrieval, "fetch_pois", _fetch)
    custom_settings = Settings(istat_context_enabled=enabled)
    app = create_app()
    app.dependency_overrides[current_executor] = lambda: FakeProfiler()
    app.dependency_overrides[get_llm_client] = lambda: _LLM()
    app.dependency_overrides[get_settings] = lambda: custom_settings
    return TestClient(app, raise_server_exceptions=False)


def _phase_1(client: TestClient) -> str:
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 200
    return str(resp.json()["contesto_hash"])


def _click(client: TestClient, route: str, contesto_hash: str) -> httpx.Response:
    body: dict[str, str] = {
        "citta": "Roma",
        "zona": "Colosseo",
        "contesto_hash": contesto_hash,
    }
    if route == "/analyze/poi":
        body["poi_id"] = _POI_ID
    return cast(
        httpx.Response,
        client.post(route, json=body),  # pyright: ignore[reportUnknownMemberType]
    )


def _updated_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulates an update of the ISTAT data after phase 1."""
    monkeypatch.setattr(
        context_fingerprint, "istat_data_version", lambda: "2025@2027-01-01"
    )


def test_the_data_version_exists_in_the_repo() -> None:
    """Precondition: without data the version would be ``None`` and the tests with
    the switch on would not distinguish anything."""
    assert data_version() is not None


def test_istat_version_for_follows_the_switch() -> None:
    assert istat_version_for(False) is None
    assert istat_version_for(True) == data_version()


def test_phase_1_off_has_the_previous_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch, enabled=False)
    assert _phase_1(client) == fingerprint(_pois("Roma"))


def test_phase_1_on_carries_the_data_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch, enabled=True)
    contesto_hash = _phase_1(client)
    assert contesto_hash == fingerprint(_pois("Roma"), istat_version=data_version())
    assert contesto_hash != fingerprint(_pois("Roma"))


@pytest.mark.parametrize("route", ["/analyze/poi", "/analyze/narrativa"])
def test_data_updated_between_phase_1_and_click_gives_409(
    route: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(monkeypatch, enabled=True)
    contesto_hash = _phase_1(client)
    _updated_data(monkeypatch)
    resp = _click(client, route, contesto_hash)
    assert resp.status_code == 409
    assert resp.json()["detail"]["errore"] == "contesto_disallineato"


@pytest.mark.parametrize("route", ["/analyze/poi", "/analyze/narrativa"])
@pytest.mark.parametrize("enabled", [True, False], ids=["istat-acceso", "istat-spento"])
def test_same_version_no_409(
    route: str, enabled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(monkeypatch, enabled=enabled)
    resp = _click(client, route, _phase_1(client))
    assert resp.status_code == 200


@pytest.mark.parametrize("route", ["/analyze/poi", "/analyze/narrativa"])
def test_switch_off_ignores_the_data_version(
    route: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off, the ISTAT data does not enter the prompt: an update of it must not
    invalidate the analysis on screen."""
    client = _client(monkeypatch, enabled=False)
    contesto_hash = _phase_1(client)
    _updated_data(monkeypatch)
    assert _click(client, route, contesto_hash).status_code == 200


# --- Evaluation paths: run switch ---


@pytest.mark.parametrize("enabled", [True, False], ids=["istat-acceso", "istat-spento"])
async def test_run_analysis_uses_the_run_switch(enabled: bool) -> None:
    resp = await run_analysis(
        "Roma",
        "Colosseo",
        executor=FakeProfiler(),
        llm_client=_LLM(),
        poi_source=_poi_source,
        geo_source=_geo_source,
        istat_context_enabled=enabled,
    )
    expected = data_version() if enabled else None
    assert resp.contesto_hash == fingerprint(_pois("Roma"), istat_version=expected)


@pytest.mark.parametrize("enabled", [True, False], ids=["istat-acceso", "istat-spento"])
async def test_no_ontology_arm_uses_the_run_switch(
    enabled: bool,
) -> None:
    resp = await run_no_ontology_prompt(
        "Roma",
        "Colosseo",
        executor=FakeProfiler(),
        llm_client=_LLM(),
        poi_source=_poi_source,
        geo_source=_geo_source,
        istat_context_enabled=enabled,
    )
    expected = data_version() if enabled else None
    assert resp.contesto_hash == fingerprint(_pois("Roma"), istat_version=expected)
