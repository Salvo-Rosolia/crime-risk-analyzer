"""Test del generation layer RAG (#23).

Lo step di generation costruisce il prompt (system fisso + contesto variabile)
a partire dal context validato dal grounding, chiama il client LLM (#20) e
produce l'output JSON strutturato (narrativa, risk_models, confidence_summary,
metadati di riproducibilita'). Nessuna chiamata di rete: il client LLM e' un
doppio asincrono e il context_dict e' mockato (lo step e' indipendente
dall'ontologia).
"""

from __future__ import annotations

from typing import Any

from crime_risk_analyzer.llm.client import LLMResponse
from crime_risk_analyzer.rag.generation import (
    SYSTEM_PROMPT,
    GenerationResult,
    build_context_str,
    generate_analysis,
)

# --- doppio del LLMClient (riproduce solo .generate e .model) ---


class _FakeLLMClient:
    """Doppio asincrono del LLMClient: registra le chiamate e ritorna una
    LLMResponse predefinita."""

    def __init__(self, response: LLMResponse) -> None:
        self._response = response
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        self.calls.append((system_prompt, user_content))
        return self._response


def _llm_response(**overrides: Any) -> LLMResponse:
    base: dict[str, Any] = {
        "text": (
            "Colosseo: rischio [ONTOLOGIA] MassTouristTargeting (Confermato).\n"
            "Sintesi: zona ad alta affluenza turistica."
        ),
        "llm_used": "claude-sonnet-4-6",
        "tokens_input": 820,
        "tokens_output": 410,
        "cache_hit": False,
        "temperature": 0.2,
        "seed": 42,
        "prompt_hash": "abc123",
    }
    base.update(overrides)
    return LLMResponse(**base)


def _context_dict(**overrides: Any) -> dict[str, Any]:
    """Context validato dal grounding (shape di grounding.md unito a retrieval)."""
    base: dict[str, Any] = {
        "zona": "Colosseo",
        "validated_risks": [
            {
                "poi": "Colosseo",
                "terminus_class": "HeritageAttractionSite",
                "risks": [
                    {
                        "hazard": "MassTouristTargeting",
                        "tag": "ONTOLOGIA",
                        "confidence": "Confermato",
                        "source": "Heritage -> hasHazard -> MassTouristTargeting",
                    },
                    {
                        "hazard": "PickPocketing",
                        "tag": "ONTOLOGIA",
                        "confidence": "Plausibile",
                        "source": "Heritage -> hasHazard -> PickPocketing",
                    },
                ],
                "vulnerabilities": ["CrowdDensity"],
                "sparql_path": "Heritage -> hasHazard -> MassTouristTargeting",
            }
        ],
        "confidence_summary": {"confermato": 1, "plausibile": 1, "speculativo": 0},
    }
    base.update(overrides)
    return base


# --- build_context_str: assembla la parte variabile del prompt ---


def test_build_context_str_includes_zona_and_poi_fields() -> None:
    ctx = _context_dict()

    out = build_context_str(ctx)

    assert "Colosseo" in out
    assert "HeritageAttractionSite" in out
    assert "MassTouristTargeting" in out
    assert "PickPocketing" in out
    # tag e confidence vanno forniti al modello per il citation layer
    assert "ONTOLOGIA" in out
    assert "Confermato" in out
    # path ontologico citato
    assert "hasHazard" in out


def test_build_context_str_lists_vulnerabilities() -> None:
    ctx = _context_dict()

    out = build_context_str(ctx)

    assert "CrowdDensity" in out


def test_build_context_str_handles_poi_without_risks() -> None:
    ctx = _context_dict(
        validated_risks=[
            {
                "poi": "Bar Roma",
                "terminus_class": "GenericUrbanPOI",
                "risks": [],
                "vulnerabilities": [],
                "sparql_path": None,
            }
        ],
        confidence_summary={"confermato": 0, "plausibile": 0, "speculativo": 0},
    )

    out = build_context_str(ctx)

    assert "Bar Roma" in out


# --- generate_analysis: orchestrazione prompt -> LLM -> JSON ---


async def test_generate_analysis_returns_structured_result() -> None:
    client = _FakeLLMClient(_llm_response())
    ctx = _context_dict()

    result = await generate_analysis(ctx, client)

    assert isinstance(result, GenerationResult)
    assert result.narrativa.startswith("Colosseo:")
    assert result.llm_used == "claude-sonnet-4-6"
    assert result.tokens_input == 820
    assert result.tokens_output == 410
    assert result.cache_hit is False


async def test_generate_analysis_passes_system_prompt_and_context() -> None:
    client = _FakeLLMClient(_llm_response())
    ctx = _context_dict()

    await generate_analysis(ctx, client)

    assert len(client.calls) == 1
    system, user = client.calls[0]
    assert system == SYSTEM_PROMPT
    assert user == build_context_str(ctx)


async def test_generate_analysis_carries_confidence_summary_from_context() -> None:
    client = _FakeLLMClient(_llm_response())
    ctx = _context_dict()

    result = await generate_analysis(ctx, client)

    assert result.confidence_summary == {
        "confermato": 1,
        "plausibile": 1,
        "speculativo": 0,
    }


async def test_generate_analysis_builds_risk_models_from_context() -> None:
    client = _FakeLLMClient(_llm_response())
    ctx = _context_dict()

    result = await generate_analysis(ctx, client)

    assert len(result.risk_models) == 1
    rm = result.risk_models[0]
    assert rm.poi == "Colosseo"
    assert len(rm.risks) == 2
    first = rm.risks[0]
    assert first.hazard == "MassTouristTargeting"
    assert first.confidence == "Confermato"
    assert first.tag == "ONTOLOGIA"


async def test_generate_analysis_exposes_repro_block() -> None:
    client = _FakeLLMClient(
        _llm_response(temperature=0.2, seed=42, prompt_hash="deadbeef")
    )
    ctx = _context_dict()

    result = await generate_analysis(ctx, client)

    assert result.repro.temperature == 0.2
    assert result.repro.seed == 42
    assert result.repro.prompt_hash == "deadbeef"


async def test_generate_analysis_records_non_negative_latency() -> None:
    client = _FakeLLMClient(_llm_response())
    ctx = _context_dict()

    result = await generate_analysis(ctx, client)

    assert result.latenza_ms >= 0


async def test_generate_analysis_cache_hit_propagated() -> None:
    client = _FakeLLMClient(_llm_response(cache_hit=True))
    ctx = _context_dict()

    result = await generate_analysis(ctx, client)

    assert result.cache_hit is True


# --- il system prompt e' la parte fissa cachata: contiene le regole di grounding ---


def test_system_prompt_contains_citation_rules() -> None:
    assert "[ONTOLOGIA]" in SYSTEM_PROMPT
    assert "[CONTESTO]" in SYSTEM_PROMPT
    assert "[SPECULATIVO]" in SYSTEM_PROMPT
    # niente scoring numerico: non deve istruire a produrre percentuali
    assert "italiano" in SYSTEM_PROMPT.lower()


# --- model_dump produce lo shape JSON atteso dall'orchestrator/frontend ---


async def test_generation_result_json_shape() -> None:
    client = _FakeLLMClient(_llm_response())
    ctx = _context_dict()

    result = await generate_analysis(ctx, client)
    payload = result.model_dump()

    assert set(payload).issuperset(
        {
            "narrativa",
            "risk_models",
            "confidence_summary",
            "llm_used",
            "tokens_input",
            "tokens_output",
            "latenza_ms",
            "cache_hit",
            "repro",
        }
    )
    assert payload["repro"] == {
        "temperature": 0.2,
        "seed": 42,
        "prompt_hash": "abc123",
    }
