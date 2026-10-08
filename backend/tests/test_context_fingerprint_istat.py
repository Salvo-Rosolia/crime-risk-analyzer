"""L'impronta del contesto copre la versione dei dati ISTAT (#354), offline.

Con l'interruttore acceso il prompt dipende anche dai dati ISTAT: se i dati si
aggiornano fra la fase 1 e il clic, ``/analyze/poi`` e ``/analyze/narrativa``
devono rifiutare (409) come per un cambio dei POI. Spento, l'impronta resta
quella di prima. I dati "aggiornati" sono simulati sostituendo la versione letta
da :mod:`~crime_risk_analyzer.context_fingerprint`, l'unico punto da cui calcolo
e confronto la prendono.
"""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer import area_search, context_fingerprint, zone_context_cache
from crime_risk_analyzer.config import Settings, get_settings
from crime_risk_analyzer.context_fingerprint import fingerprint, istat_versione_per
from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.istat.dati import versione_dati
from crime_risk_analyzer.llm.client import LLMResponse, get_llm_client
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.orchestrator import run_analysis, run_no_ontology_prompt
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.rag import retrieval
from crime_risk_analyzer.sparql_module.query_executor import get_executor

_POI_ID = "node/1"


class _Profiler:
    def profile(self, terminus_class: str) -> PoiRiskProfile:
        if terminus_class == "Bank":
            return PoiRiskProfile(
                terminus_class="Bank",
                hazards=["Bank_robbery"],
                sparql_paths=["Bank → havingHazard → Bank_robbery"],
            )
        return PoiRiskProfile(terminus_class=terminus_class)


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
        {
            "id": _POI_ID,
            "name": "Banca A",
            "lat": 41.8900,
            "lon": 12.4920,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": citta,
        },
        {
            "id": "node/2",
            "name": "Liceo Cavour",
            "lat": 41.8901,
            "lon": 12.4921,
            "osm_tags": "amenity=school",
            "terminus_class": "School",
            "citta": citta,
        },
    ]


async def _geo_source(citta: str, zona: str) -> GeoResult:
    return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))


async def _poi_source(bbox: Bbox, citta: str) -> list[Poi]:
    return _pois(citta)


def _client(monkeypatch: pytest.MonkeyPatch, *, acceso: bool) -> TestClient:
    zone_context_cache.clear()

    def _etichetta(lat: float, lon: float) -> tuple[str, str]:
        return ("Roma", "Colosseo")

    monkeypatch.setattr(area_search, "reverse_geocode_label", _etichetta)

    async def _fetch(bbox: object, citta: str, *a: object, **k: object) -> list[Poi]:
        return _pois(citta)

    monkeypatch.setattr(retrieval, "fetch_pois", _fetch)
    impostazioni = Settings(istat_context_enabled=acceso)
    app = create_app()
    app.dependency_overrides[get_executor] = lambda: _Profiler()
    app.dependency_overrides[get_llm_client] = lambda: _LLM()
    app.dependency_overrides[get_settings] = lambda: impostazioni
    return TestClient(app, raise_server_exceptions=False)


def _fase_1(client: TestClient) -> str:
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 200
    return str(resp.json()["contesto_hash"])


def _clic(client: TestClient, rotta: str, contesto_hash: str) -> httpx.Response:
    body: dict[str, str] = {
        "citta": "Roma",
        "zona": "Colosseo",
        "contesto_hash": contesto_hash,
    }
    if rotta == "/analyze/poi":
        body["poi_id"] = _POI_ID
    return cast(
        httpx.Response,
        client.post(rotta, json=body),  # pyright: ignore[reportUnknownMemberType]
    )


def _dati_aggiornati(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simula un aggiornamento dei dati ISTAT dopo la fase 1."""
    monkeypatch.setattr(context_fingerprint, "versione_dati", lambda: "2025@2027-01-01")


def test_la_versione_dei_dati_esiste_nel_repo() -> None:
    """Precondizione: senza dati la versione sarebbe ``None`` e i test con
    interruttore acceso non distinguerebbero nulla."""
    assert versione_dati() is not None


def test_istat_versione_per_segue_l_interruttore() -> None:
    assert istat_versione_per(False) is None
    assert istat_versione_per(True) == versione_dati()


def test_fase_1_spenta_ha_l_impronta_di_prima(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch, acceso=False)
    assert _fase_1(client) == fingerprint(_pois("Roma"))


def test_fase_1_accesa_porta_la_versione_dei_dati(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch, acceso=True)
    contesto_hash = _fase_1(client)
    assert contesto_hash == fingerprint(_pois("Roma"), istat_versione=versione_dati())
    assert contesto_hash != fingerprint(_pois("Roma"))


@pytest.mark.parametrize("rotta", ["/analyze/poi", "/analyze/narrativa"])
def test_dati_aggiornati_fra_fase_1_e_clic_danno_409(
    rotta: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(monkeypatch, acceso=True)
    contesto_hash = _fase_1(client)
    _dati_aggiornati(monkeypatch)
    resp = _clic(client, rotta, contesto_hash)
    assert resp.status_code == 409
    assert resp.json()["detail"]["errore"] == "contesto_disallineato"


@pytest.mark.parametrize("rotta", ["/analyze/poi", "/analyze/narrativa"])
@pytest.mark.parametrize("acceso", [True, False], ids=["istat-acceso", "istat-spento"])
def test_stessa_versione_nessun_409(
    rotta: str, acceso: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(monkeypatch, acceso=acceso)
    resp = _clic(client, rotta, _fase_1(client))
    assert resp.status_code == 200


@pytest.mark.parametrize("rotta", ["/analyze/poi", "/analyze/narrativa"])
def test_interruttore_spento_ignora_la_versione_dei_dati(
    rotta: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spento, i dati ISTAT non entrano nel prompt: un loro aggiornamento non
    deve invalidare l'analisi a schermo."""
    client = _client(monkeypatch, acceso=False)
    contesto_hash = _fase_1(client)
    _dati_aggiornati(monkeypatch)
    assert _clic(client, rotta, contesto_hash).status_code == 200


# --- Percorsi di valutazione: interruttore della run ---


@pytest.mark.parametrize("acceso", [True, False], ids=["istat-acceso", "istat-spento"])
async def test_run_analysis_usa_l_interruttore_della_run(acceso: bool) -> None:
    resp = await run_analysis(
        "Roma",
        "Colosseo",
        executor=_Profiler(),
        llm_client=_LLM(),
        poi_source=_poi_source,
        geo_source=_geo_source,
        istat_context_enabled=acceso,
    )
    attesa = versione_dati() if acceso else None
    assert resp.contesto_hash == fingerprint(_pois("Roma"), istat_versione=attesa)


@pytest.mark.parametrize("acceso", [True, False], ids=["istat-acceso", "istat-spento"])
async def test_braccio_senza_ontologia_usa_l_interruttore_della_run(
    acceso: bool,
) -> None:
    resp = await run_no_ontology_prompt(
        "Roma",
        "Colosseo",
        executor=_Profiler(),
        llm_client=_LLM(),
        poi_source=_poi_source,
        geo_source=_geo_source,
        istat_context_enabled=acceso,
    )
    attesa = versione_dati() if acceso else None
    assert resp.contesto_hash == fingerprint(_pois("Roma"), istat_versione=attesa)
