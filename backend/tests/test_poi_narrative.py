"""Endpoint e orchestrazione della narrativa per POI (#197), offline."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer import zone_context_cache
from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.llm.client import LLMError, LLMResponse, get_llm_client
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.orchestrator import run_analysis
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.poi_narrative import (
    PoiNarrativeResponse,
    PoiNotFoundError,
    run_poi_narrative,
)
from crime_risk_analyzer.rag import retrieval
from crime_risk_analyzer.sparql_module.query_executor import get_executor

_POI_ID = "node/1"

_BANK = PoiRiskProfile(
    terminus_class="Bank",
    hazards=["Bank_robbery"],
    vulnerabilities=["Accesso non controllato"],
    sparql_paths=["Bank → havingHazard → Bank_robbery"],
)


class _FakeProfiler:
    def profile(self, terminus_class: str) -> PoiRiskProfile:
        return {"Bank": _BANK}.get(
            terminus_class, PoiRiskProfile(terminus_class=terminus_class)
        )


class _FakeLLMClient:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        return LLMResponse(
            text=(
                "Sintesi.\n\n"
                "[ONTOLOGIA]\nRischio rapina.\n\n"
                "[CONTESTO]\nVicino a una scuola.\n"
            ),
            llm_used="claude-sonnet-4-6",
            tokens_input=5,
            tokens_output=8,
            cache_hit=False,
            temperature=0.2,
            seed=42,
            prompt_hash="h",
        )


class _RaisingLLMClient:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        raise LLMError("provider giu'")


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


async def _prime_cache() -> None:
    """Popola la cache del contesto di zona eseguendo /analyze con i doppi."""
    zone_context_cache.clear()
    await run_analysis(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )


def _patch_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sostituisce geocoding e Overpass per i test dell'endpoint HTTP."""

    def _fake_geocode(zona: str, citta: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois(citta)

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode)
    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)


def _client(llm: object = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_executor] = lambda: _FakeProfiler()
    app.dependency_overrides[get_llm_client] = lambda: llm or _FakeLLMClient()
    return TestClient(app, raise_server_exceptions=False)


async def test_returns_narrative_for_a_poi_in_the_cached_zone() -> None:
    await _prime_cache()
    out = await run_poi_narrative(
        "Roma",
        "Colosseo",
        _POI_ID,
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
    )
    assert out.poi_id == _POI_ID
    assert out.narrativa != ""
    assert out.fallback is False
    assert [rm.poi for rm in out.risk_models] == ["Banca A"]


async def test_cache_hit_does_not_touch_overpass() -> None:
    """Su hit non si spende una chiamata a un servizio pubblico gratuito (#232)."""
    await _prime_cache()

    async def _exploding(bbox: Bbox, citta: str) -> list[Poi]:
        raise AssertionError("Overpass non deve essere chiamato su cache hit")

    out = await run_poi_narrative(
        "Roma",
        "Colosseo",
        _POI_ID,
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_exploding,
    )
    assert out.narrativa != ""


async def test_cold_cache_rebuilds_the_context() -> None:
    zone_context_cache.clear()
    out = await run_poi_narrative(
        "Roma",
        "Colosseo",
        _POI_ID,
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    assert out.narrativa != ""
    assert zone_context_cache.get("Roma", "Colosseo") is not None


async def test_narrative_context_carries_the_neighbourhood() -> None:
    """Il prompt del POI deve contenere il vicinato: e' cio' che lo distingue."""
    await _prime_cache()
    seen: list[str] = []

    class _Recording:
        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            seen.append(user_content)
            return LLMResponse(
                text="x",
                llm_used="fake",
                tokens_input=1,
                tokens_output=1,
                cache_hit=False,
                temperature=0.0,
                seed=0,
                prompt_hash="h",
            )

    await run_poi_narrative(
        "Roma",
        "Colosseo",
        _POI_ID,
        executor=_FakeProfiler(),
        llm_client=_Recording(),
    )
    assert "PUNTO SELEZIONATO: Banca A" in seen[0]
    assert "Liceo Cavour" in seen[0]
    assert "COMPOSIZIONE DELLA ZONA:" in seen[0]


async def test_unknown_poi_id_raises_poi_not_found() -> None:
    await _prime_cache()
    with pytest.raises(PoiNotFoundError):
        await run_poi_narrative(
            "Roma",
            "Colosseo",
            "non-esiste",
            executor=_FakeProfiler(),
            llm_client=_FakeLLMClient(),
        )


async def test_llm_error_falls_back_without_raising() -> None:
    """Stessa politica del percorso di zona: dati strutturati + fallback=True."""
    await _prime_cache()
    out = await run_poi_narrative(
        "Roma",
        "Colosseo",
        _POI_ID,
        executor=_FakeProfiler(),
        llm_client=_RaisingLLMClient(),
    )
    assert out.fallback is True
    assert out.narrativa == ""
    assert out.risk_models != []


def test_endpoint_returns_200_and_narrative(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    client = _client()
    client.post("/analyze", json={"citta": "Roma", "zona": "Colosseo"})  # pyright: ignore[reportUnknownMemberType]
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/poi",
            json={"citta": "Roma", "zona": "Colosseo", "poi_id": _POI_ID},
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["poi_id"] == _POI_ID
    assert body["narrativa_fonti"]["ontologia"] != ""
    assert body["fallback"] is False


def test_endpoint_returns_404_for_unknown_poi(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    client = _client()
    client.post("/analyze", json={"citta": "Roma", "zona": "Colosseo"})  # pyright: ignore[reportUnknownMemberType]
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/poi",
            json={"citta": "Roma", "zona": "Colosseo", "poi_id": "non-esiste"},
        ),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["errore"] == "poi_non_nel_contesto"


# --- #184: guardia anti-scoring estesa al contratto di ``/analyze/poi`` (#197) ---
# Stesso pattern exact-set di ``test_orchestrator``: il grep sul payload qui sotto
# intercetta solo nomi di campo gia' noti, mentre l'insieme esatto rende rosso
# QUALUNQUE campo nuovo, costringendo a una revisione cosciente del vincolo legale.


def test_poi_narrative_response_has_no_numeric_danger_scoring_field() -> None:
    """Contratto della risposta ``/analyze/poi``: nessuno scoring numerico di
    pericolosita' (_project.md §Vincoli). I campi numerici presenti
    (``tokens_*``/``latenza_ms``) misurano costo e performance, NON la magnitudo
    del pericolo. Un campo di rating aggiunto qui romperebbe l'insieme esatto."""
    assert set(PoiNarrativeResponse.model_fields) == {
        "poi_id",
        "narrativa",
        "narrativa_fonti",
        "risk_models",
        "tokens_input",
        "tokens_output",
        "latenza_ms",
        "repro",
        "fallback",
    }


def test_endpoint_response_never_contains_a_danger_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guardia anti-scoring estesa al nuovo endpoint (#184)."""
    _patch_io(monkeypatch)
    client = _client()
    client.post("/analyze", json={"citta": "Roma", "zona": "Colosseo"})  # pyright: ignore[reportUnknownMemberType]
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/poi",
            json={"citta": "Roma", "zona": "Colosseo", "poi_id": _POI_ID},
        ),
    )
    payload = resp.text.lower()
    for vietato in ("punteggio", "score", "livello di rischio", "pericolosit"):
        assert vietato not in payload
