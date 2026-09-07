"""Fase 1 (#259): risposta strutturata veloce, narrativa non ancora generata."""

from __future__ import annotations

import pytest

from crime_risk_analyzer import zone_context_cache
from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.llm.client import LLMError, LLMResponse
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.poi_narrative import ContextMismatchError

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


def _pois(citta: str) -> list[Poi]:
    return [
        {
            "id": "node/1",
            "name": "Banca A",
            "lat": 41.8900,
            "lon": 12.4920,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": citta,
        },
    ]


async def _geo_source(citta: str, zona: str) -> GeoResult:
    return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))


async def _poi_source(bbox: Bbox, citta: str) -> list[Poi]:
    return _pois(citta)


async def test_fast_response_has_no_narrativa_yet() -> None:
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast

    out = await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    assert out.narrativa is None
    assert out.fallback is False
    assert len(out.poi) == 1
    assert out.poi[0].id == "node/1"


async def test_fast_response_warms_the_zone_context_cache() -> None:
    """Stesso side-effect di `run_analysis()`: /analyze/narrative non deve
    rifare Overpass (#232)."""
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast

    await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    assert zone_context_cache.get("Roma", "Colosseo") is not None


async def test_fast_response_contesto_hash_matches_the_cached_context() -> None:
    """L'impronta restituita è quella che /analyze/narrative dovrà ricevere
    indietro per passare la verifica (#242)."""
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast
    from crime_risk_analyzer.context_fingerprint import fingerprint

    out = await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    cached = zone_context_cache.get("Roma", "Colosseo")
    assert cached is not None
    assert out.contesto_hash == fingerprint(cached["retrieval"]["pois"])


class _FakeLLMClient:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        return LLMResponse(
            text=(
                "Sintesi.\n\n[ONTOLOGIA]\nRischio rapina.\n\n"
                "[CONTESTO]\nZona centrale.\n"
            ),
            llm_used="test-model",
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


async def _prime_cache() -> str:
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast

    zone_context_cache.clear()
    resp = await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    assert resp.contesto_hash is not None
    return resp.contesto_hash


async def test_zone_narrative_returns_text_for_the_cached_zone() -> None:
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    contesto_hash = await _prime_cache()
    out = await run_zone_narrative(
        "Roma",
        "Colosseo",
        contesto_hash=contesto_hash,
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
    )
    assert out.narrativa != ""
    assert out.fallback is False


async def test_zone_narrative_cache_hit_does_not_touch_overpass() -> None:
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    contesto_hash = await _prime_cache()

    async def _exploding(bbox: Bbox, citta: str) -> list[Poi]:
        raise AssertionError("Overpass non deve essere chiamato su cache hit")

    out = await run_zone_narrative(
        "Roma",
        "Colosseo",
        contesto_hash=contesto_hash,
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_exploding,
    )
    assert out.narrativa != ""


async def test_zone_narrative_context_mismatch_raises() -> None:
    """Zona ri-analizzata fra le due chiamate (#242): stessa guardia di /analyze/poi."""
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    await _prime_cache()
    with pytest.raises(ContextMismatchError):
        await run_zone_narrative(
            "Roma",
            "Colosseo",
            contesto_hash="hash-vecchio-non-valido",
            executor=_FakeProfiler(),
            llm_client=_FakeLLMClient(),
        )


async def test_zone_narrative_llm_error_falls_back_without_raising() -> None:
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    contesto_hash = await _prime_cache()
    out = await run_zone_narrative(
        "Roma",
        "Colosseo",
        contesto_hash=contesto_hash,
        executor=_FakeProfiler(),
        llm_client=_RaisingLLMClient(),
    )
    assert out.fallback is True
    assert out.narrativa == ""


def test_zone_narrative_response_has_no_numeric_danger_scoring_field() -> None:
    """Stesso vincolo di `PoiNarrativeResponse` (_project.md §Vincoli): l'insieme
    esatto impedisce di intrufolare un punteggio numerico di pericolosità."""
    from crime_risk_analyzer.analyze_narrative import ZoneNarrativeResponse

    assert set(ZoneNarrativeResponse.model_fields) == {
        "narrativa",
        "narrativa_fonti",
        "tokens_input",
        "tokens_output",
        "latenza_ms",
        "repro",
        "fallback",
    }
