"""Doppi di test condivisi tra test_orchestrator e test_harness (#34).

Non e' un file di test (nessuna funzione test_*): pytest non raccoglie nulla.
Estratto da test_orchestrator.py per evitare duplicazione.
"""

from __future__ import annotations

from crime_risk_analyzer.llm.client import LLMResponse
from crime_risk_analyzer.models.risk import PoiRiskProfile


class FakeProfiler:
    """Doppio di RiskProfiler per test senza SPARQL.

    Costruibile senza argomenti (harness test); accetta un dizionario opzionale
    per i test dell'orchestratore che iniettano profili specifici.
    """

    def __init__(self, profiles: dict[str, PoiRiskProfile] | None = None) -> None:
        self._profiles: dict[str, PoiRiskProfile] = profiles or {}

    def profile(self, terminus_class: str) -> PoiRiskProfile:
        return self._profiles.get(
            terminus_class, PoiRiskProfile(terminus_class=terminus_class)
        )


class FakeLLMClient:
    """Doppio di _LLMClientLike per test senza provider LLM reale.

    Costruibile senza argomenti (harness test); accetta una risposta opzionale
    per i test dell'orchestratore che controllano valori specifici.
    """

    def __init__(self, response: LLMResponse | None = None) -> None:
        self._response: LLMResponse = response or default_llm_response()

    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        return self._response


def default_llm_response() -> LLMResponse:
    """Risposta LLM di default usata da FakeLLMClient() senza argomenti."""
    return LLMResponse(
        text="Analisi: Banca A presenta rischio rapina.",
        llm_used="claude-sonnet-4-6",
        tokens_input=10,
        tokens_output=20,
        cache_hit=False,
        temperature=0.2,
        seed=42,
        prompt_hash="abc123",
    )
