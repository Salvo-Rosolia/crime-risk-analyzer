"""End to end: the LLM prompts of the narrative routes use the active set labels (#442).

With a custom source session (``X-Session-Id``) the prompt really sent to the model
by ``POST /analyze/poi`` and ``POST /analyze/narrativa`` must carry the labels of the
set, not the TERMINUS ones. Without a session the text stays the TERMINUS one.
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
from crime_risk_analyzer.istat.data import IstatData, istat_data
from crime_risk_analyzer.llm.client import LLMResponse, get_llm_client
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.rag import retrieval
from crime_risk_analyzer.sources import routes
from crime_risk_analyzer.sources.context import current_executor, default_set
from crime_risk_analyzer.sources.model import IstatSource, SourceSet
from crime_risk_analyzer.sources.session import SessionStore
from tests.eval._doubles import FakeProfiler, make_poi

SID = "abcdefghij" * 3 + "kl"
_POI_ID = "node/1"

_CLASS = "Bank"
_HAZARD = "Bank_robbery"
_VULN = "Area_away_from_the_town"
_NEIGHBOUR_CLASS = "School"

_TERMINUS_CLASS_IT = "Banca"
_TERMINUS_HAZARD_IT = "Rapina in banca"
_TERMINUS_VULN_IT = "Area lontana dal centro abitato"
_TERMINUS_NEIGHBOUR_IT = "Scuola"

# Deliberately different from TERMINUS; none contains a TERMINUS label.
_SET_CLASS_IT = "Istituto di credito"
_SET_HAZARD_IT = "Assalto allo sportello"
_SET_VULN_IT = "Zona poco sorvegliata"
_SET_NEIGHBOUR_IT = "Plesso scolastico"

_BANK = PoiRiskProfile(
    ontology_class=_CLASS,
    hazards=[_HAZARD],
    vulnerabilities=[_VULN],
    sparql_paths=[f"{_CLASS} → havingHazard → {_HAZARD}"],
)


class _CapturingLLM:
    """Records the prompts the route actually sends to the model."""

    def __init__(self) -> None:
        self.user_contents: list[str] = []

    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        self.user_contents.append(user_content)
        return LLMResponse(
            text="Sintesi.\n\n[ONTOLOGIA]\nRischio rapina.\n",
            llm_used="claude-sonnet-4-6",
            tokens_input=5,
            tokens_output=8,
            cache_hit=False,
            temperature=0.2,
            seed=42,
            prompt_hash="h",
        )


def _pois(city: str) -> list[Poi]:
    # The POI names contain no TERMINUS label ("Banca"/"Bank"/"Scuola"/"School").
    # The second POI, of another class, is the neighbour of the first one: it feeds
    # the VICINATO section of the single-POI prompt.
    return [
        make_poi(
            id=_POI_ID,
            name="Sportello Centrale",
            lon=12.4920,
            ontology_class=_CLASS,
            citta=city,
        ),
        make_poi(
            id="node/2",
            name="Liceo Nord",
            lat=41.8905,
            lon=12.4925,
            osm_tags="amenity=school",
            ontology_class=_NEIGHBOUR_CLASS,
            citta=city,
        ),
    ]


def _istat_with_bank_robberies_above_threshold() -> IstatData:
    """Copy of the real ISTAT data where Rome/BANKROB reaches the block threshold.

    With the real figures the item is below ``TREND_THRESHOLD``, so the DATI ISTAT
    block (and its "Collegata a: <hazard label>" line) would never reach the prompt.
    """
    real = istat_data()
    values = {
        k: {v: dict(a) for v, a in items.items()}
        for k, items in real.delitti.valori.items()
    }
    year = str(real.delitti.anno)
    base = values["058091"]["BANKROB"][year]
    assert base is not None
    values["058091"]["BANKROB"][year] = base.model_copy(update={"delitti": 30})
    crimes = real.delitti.model_copy(update={"valori": values})
    return IstatData(delitti=crimes, luoghi=real.luoghi)


def _custom_set() -> SourceSet:
    active = default_set()
    return dataclasses.replace(
        active,
        id="custom-labels",
        kind="custom",
        labels={
            _CLASS: (_SET_CLASS_IT, "Credit institution"),
            _NEIGHBOUR_CLASS: (_SET_NEIGHBOUR_IT, "Educational site"),
            _HAZARD: (_SET_HAZARD_IT, "Counter assault"),
            _VULN: (_SET_VULN_IT, "Poorly monitored area"),
        },
        istat=IstatSource(
            dati=_istat_with_bank_robberies_above_threshold(),
            mappatura=active.istat.mappatura,
            voci_rottura=active.istat.voci_rottura,
            versione="v-custom",
        ),
    )


@pytest.fixture
def llm() -> _CapturingLLM:
    return _CapturingLLM()


@pytest.fixture
def client(llm: _CapturingLLM, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    zone_context_cache.clear()

    def _reverse(lat: float, lon: float) -> tuple[str, str]:
        return ("Roma", "Colosseo")

    async def _fetch(
        bbox: object, city: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois(city)

    def _geocode(zona: str, citta: str) -> GeoResult:
        # Cold-cache path of /analyze/*: never reach the real Nominatim.
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    monkeypatch.setattr(area_search, "reverse_geocode_label", _reverse)
    monkeypatch.setattr(retrieval, "geocode_zone", _geocode)
    monkeypatch.setattr(retrieval, "fetch_pois", _fetch)

    store = SessionStore(ttl_seconds=100, max_sessions=4)
    store.activate(SID, _custom_set(), [])
    app = create_app()
    app.dependency_overrides[routes.get_sessions] = lambda: store
    app.dependency_overrides[current_executor] = lambda: FakeProfiler({_CLASS: _BANK})
    app.dependency_overrides[get_llm_client] = lambda: llm
    yield TestClient(app, raise_server_exceptions=False)
    zone_context_cache.clear()


def _post(
    client: TestClient, path: str, body: dict[str, object], session: bool
) -> httpx.Response:
    headers = {"X-Session-Id": SID} if session else {}
    return cast(
        httpx.Response,
        client.post(path, json=body, headers=headers),  # pyright: ignore[reportUnknownMemberType]
    )


def _analyze(client: TestClient, session: bool) -> str:
    resp = _post(
        client,
        "/analyze",
        {"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        session,
    )
    assert resp.status_code == 200
    return str(resp.json()["contesto_hash"])


def _poi_prompt(client: TestClient, llm: _CapturingLLM, session: bool) -> str:
    context_hash = _analyze(client, session)
    resp = _post(
        client,
        "/analyze/poi",
        {
            "citta": "Roma",
            "zona": "Colosseo",
            "poi_id": _POI_ID,
            "contesto_hash": context_hash,
        },
        session,
    )
    assert resp.status_code == 200
    assert resp.json()["fallback"] is False
    assert len(llm.user_contents) == 1
    return llm.user_contents[0]


def _zone_prompt(client: TestClient, llm: _CapturingLLM, session: bool) -> str:
    context_hash = _analyze(client, session)
    resp = _post(
        client,
        "/analyze/narrativa",
        {"citta": "Roma", "zona": "Colosseo", "contesto_hash": context_hash},
        session,
    )
    assert resp.status_code == 200
    assert resp.json()["fallback"] is False
    assert len(llm.user_contents) == 1
    return llm.user_contents[0]


def test_poi_route_prompt_uses_session_set_labels(
    client: TestClient, llm: _CapturingLLM
) -> None:
    prompt = _poi_prompt(client, llm, session=True)
    assert f"(classe: {_SET_CLASS_IT})" in prompt
    assert f"{_HAZARD} / {_SET_HAZARD_IT}" in prompt
    assert f"{_VULN} / {_SET_VULN_IT}" in prompt
    # VICINATO: the neighbour's class and COMPOSIZIONE DELLA ZONA, set labels.
    assert f"Liceo Nord ({_SET_NEIGHBOUR_IT}), " in prompt
    assert (
        f"classi piu' frequenti fra questi: {_SET_CLASS_IT} (1), "
        f"{_SET_NEIGHBOUR_IT} (1)." in prompt
    )
    # DATI ISTAT block: the linked hazard is shown with the set label.
    assert "DATI ISTAT" in prompt
    assert f"Collegata a: {_SET_HAZARD_IT}" in prompt
    for terminus in (
        _TERMINUS_CLASS_IT,
        _TERMINUS_HAZARD_IT,
        _TERMINUS_VULN_IT,
        _TERMINUS_NEIGHBOUR_IT,
    ):
        assert terminus not in prompt


def test_poi_route_prompt_without_session_uses_terminus_labels(
    client: TestClient, llm: _CapturingLLM
) -> None:
    prompt = _poi_prompt(client, llm, session=False)
    assert f"(classe: {_TERMINUS_CLASS_IT})" in prompt
    assert f"{_HAZARD} / {_TERMINUS_HAZARD_IT}" in prompt
    assert f"{_VULN} / {_TERMINUS_VULN_IT}" in prompt
    assert f"Liceo Nord ({_TERMINUS_NEIGHBOUR_IT}), " in prompt
    for label in (_SET_CLASS_IT, _SET_HAZARD_IT, _SET_VULN_IT, _SET_NEIGHBOUR_IT):
        assert label not in prompt


def test_zone_route_prompt_uses_session_set_labels(
    client: TestClient, llm: _CapturingLLM
) -> None:
    prompt = _zone_prompt(client, llm, session=True)
    assert f"{_CLASS} / {_SET_CLASS_IT}" in prompt
    assert f"Collegata a: {_SET_HAZARD_IT}" in prompt
    assert f"{_HAZARD} / {_SET_HAZARD_IT}" in prompt
    assert f"{_VULN} / {_SET_VULN_IT}" in prompt
    for terminus in (
        _TERMINUS_CLASS_IT,
        _TERMINUS_HAZARD_IT,
        _TERMINUS_VULN_IT,
        _TERMINUS_NEIGHBOUR_IT,
    ):
        assert terminus not in prompt


def test_zone_route_prompt_without_session_uses_terminus_labels(
    client: TestClient, llm: _CapturingLLM
) -> None:
    prompt = _zone_prompt(client, llm, session=False)
    assert f"{_CLASS} / {_TERMINUS_CLASS_IT}" in prompt
    assert f"{_HAZARD} / {_TERMINUS_HAZARD_IT}" in prompt
    assert f"{_VULN} / {_TERMINUS_VULN_IT}" in prompt
    for label in (_SET_CLASS_IT, _SET_HAZARD_IT, _SET_VULN_IT, _SET_NEIGHBOUR_IT):
        assert label not in prompt
