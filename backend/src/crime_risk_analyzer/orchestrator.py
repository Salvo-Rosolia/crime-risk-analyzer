"""Orchestratore dell'endpoint ``POST /analyze`` (#18).

Cabla i tre layer RAG gia' pronti (retrieval #22 -> grounding #24 ->
generation #23) e serializza lo schema canonico di ``/analyze``
(backend/orchestrator.md). Contiene la funzione pura :func:`run_analysis`
(testabile senza HTTP) e i modelli del contratto; la rotta FastAPI vive in
``main.py``.
"""

from __future__ import annotations

import time
from typing import Protocol

from pydantic import BaseModel, Field

from crime_risk_analyzer.llm.client import LLMError, LLMResponse
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.models.vocab import Confidence, ConfidenceSummary
from crime_risk_analyzer.rag.generation import (
    Repro,
    RiskItem,
    RiskModel,
    generate_analysis,
)
from crime_risk_analyzer.rag.grounding import GroundedContext, ground
from crime_risk_analyzer.rag.retrieval import RetrievalContext, retrieve


class AnalyzeRequest(BaseModel):
    """Body di ``POST /analyze`` (naming ASCII)."""

    citta: str = Field(description="Citta' tra quelle supportate.")
    zona: str = Field(description="Zona/quartiere da analizzare.")
    domanda: str | None = Field(
        default=None,
        description=(
            "Domanda libera (opzionale). Accettata ma non cablata all'LLM (#18)."
        ),
    )


class PoiOut(BaseModel):
    """POI nello schema canonico ``/analyze`` (coords + confidence + path)."""

    id: str
    name: str
    terminus_class: str
    lat: float
    lon: float
    confidence: Confidence = Field(
        description="confermato se il POI ha rischi ontologici, altrimenti speculativo."
    )
    sparql_path: str | None = None


class AnalyzeResponse(BaseModel):
    """Schema canonico di ``/analyze`` (backend/orchestrator.md)."""

    citta: str
    zona_normalizzata: str
    poi: list[PoiOut]
    risk_models: list[RiskModel]
    narrativa: str
    confidence_summary: ConfidenceSummary
    llm_used: str
    latenza_ms: int = Field(ge=0)
    repro: Repro
    cache_hit: bool
    fallback: bool = Field(
        default=False,
        description="True se l'LLM e' caduto: response con soli dati strutturati.",
    )


def _build_poi_list(
    retrieval_ctx: RetrievalContext, grounded: GroundedContext
) -> list[PoiOut]:
    """Unisce coords (da retrieval) e confidence/path (da grounding) per POI.

    Invariante: ``grounded["validated_risks"]`` ha stesso ordine e lunghezza di
    ``retrieval_ctx["pois"]``. ``strict=True`` esplicita l'errore se si rompe.
    """
    out: list[PoiOut] = []
    for poi, vr in zip(retrieval_ctx["pois"], grounded["validated_risks"], strict=True):
        confidence: Confidence = "confermato" if vr["risks"] else "speculativo"
        out.append(
            PoiOut(
                id=poi["id"],
                name=poi["name"],
                terminus_class=poi["terminus_class"],
                lat=poi["lat"],
                lon=poi["lon"],
                confidence=confidence,
                sparql_path=vr["sparql_path"],
            )
        )
    return out


def _risk_models_from_grounded(grounded: GroundedContext) -> list[RiskModel]:
    """Ricostruisce i risk_models dal context validato (fallback senza LLM)."""
    models: list[RiskModel] = []
    for vr in grounded["validated_risks"]:
        items = [
            RiskItem(hazard=r["hazard"], confidence=r["confidence"], tag=r["tag"])
            for r in vr["risks"]
        ]
        models.append(RiskModel(poi=vr["poi"], risks=items))
    return models


class RiskProfiler(Protocol):
    """Superficie minima dell'executor SPARQL usata dalla pipeline (DI)."""

    def profile(self, terminus_class: str) -> PoiRiskProfile: ...


class _LLMClientLike(Protocol):
    """Superficie minima del client LLM (DI; doppi nei test)."""

    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse: ...


async def run_analysis(
    citta: str,
    zona: str,
    *,
    executor: RiskProfiler,
    llm_client: _LLMClientLike,
) -> AnalyzeResponse:
    """Esegue la pipeline completa e assembla la response canonica.

    ``retrieve`` (async) -> ``ground`` (sync) -> ``generate_analysis`` (async).
    Su :class:`LLMError` ritorna i soli dati strutturati (``fallback=True``).
    ``latenza_ms`` e' end-to-end sull'intera pipeline.
    """
    start = time.perf_counter()
    retrieval_ctx = await retrieve(citta, zona, executor=executor)
    grounded = ground(retrieval_ctx)
    poi_out = _build_poi_list(retrieval_ctx, grounded)
    confidence_summary = ConfidenceSummary.model_validate(
        grounded["confidence_summary"]
    )

    try:
        gen = await generate_analysis(dict(grounded), llm_client)
        narrativa = gen.narrativa
        risk_models = gen.risk_models
        confidence_summary = gen.confidence_summary
        llm_used = gen.llm_used
        repro = gen.repro
        cache_hit = gen.cache_hit
        fallback = False
    except LLMError:
        narrativa = ""
        risk_models = _risk_models_from_grounded(grounded)
        llm_used = ""
        repro = Repro(temperature=0.0, seed=0, prompt_hash="")
        cache_hit = False
        fallback = True

    latenza_ms = int((time.perf_counter() - start) * 1000)
    return AnalyzeResponse(
        citta=citta,
        zona_normalizzata=zona,
        poi=poi_out,
        risk_models=risk_models,
        narrativa=narrativa,
        confidence_summary=confidence_summary,
        llm_used=llm_used,
        latenza_ms=latenza_ms,
        repro=repro,
        cache_hit=cache_hit,
        fallback=fallback,
    )
