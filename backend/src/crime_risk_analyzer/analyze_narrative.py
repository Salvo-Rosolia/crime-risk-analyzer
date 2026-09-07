"""Fase 1+2 di ``/analyze`` senza bloccare sulla narrativa (#259).

Modulo fratello di :mod:`~crime_risk_analyzer.poi_narrative` (#197): stesso
schema — chiama ``retrieve``/``ground`` direttamente, non tocca il corpo di
``orchestrator.run_analysis`` — applicato al livello di zona invece che al
singolo POI. ``run_analysis_fast`` sostituisce ``run_analysis`` sulla rotta
``POST /analyze``: stesso retrieve+ground+warm della cache, ma nessuna
chiamata LLM — la risposta ha ``narrativa=None`` (#259 fase 1). La narrativa
arriva con ``run_zone_narrative``, che legge il contesto (caldo o
ricostruito, stesso schema di ``run_poi_narrative``) e genera.
"""

from __future__ import annotations

import logging
import time

from pydantic import BaseModel, Field

from crime_risk_analyzer import zone_context_cache
from crime_risk_analyzer.context_fingerprint import fingerprint
from crime_risk_analyzer.llm.client import LLMError
from crime_risk_analyzer.orchestrator import (
    AnalyzeResponse,
    PoiSource,
    RiskProfiler,
    _build_poi_list,  # pyright: ignore[reportPrivateUsage]
    _elapsed_ms,  # pyright: ignore[reportPrivateUsage]
    _LLMClientLike,  # pyright: ignore[reportPrivateUsage]
    _structured_response,  # pyright: ignore[reportPrivateUsage]
)
from crime_risk_analyzer.poi_narrative import ContextMismatchError
from crime_risk_analyzer.rag.generation import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_REQUEST_TOKEN_BUDGET,
    Repro,
    SourceProse,
    generate_analysis,
    parse_source_prose,
)
from crime_risk_analyzer.rag.grounding import ground
from crime_risk_analyzer.rag.retrieval import GeoSource, retrieve
from crime_risk_analyzer.zone_context_cache import ZoneContext

logger = logging.getLogger(__name__)

__all__ = [
    "ZoneNarrativeRequest",
    "ZoneNarrativeResponse",
    "run_analysis_fast",
    "run_zone_narrative",
]


async def run_analysis_fast(
    citta: str,
    zona: str,
    *,
    executor: RiskProfiler,
    poi_source: PoiSource | None = None,
    geo_source: GeoSource | None = None,
) -> AnalyzeResponse:
    """Fase 1 (#259): dati strutturati subito, ``narrativa=None``.

    Stesso ``retrieve`` -> ``ground`` -> warm di ``zone_context_cache`` di
    :func:`~crime_risk_analyzer.orchestrator.run_analysis`: la narrativa vera
    arriva con :func:`run_zone_narrative`, che rilegge questa stessa cache.
    """
    start = time.perf_counter()
    retrieval_ctx = await retrieve(
        citta, zona, executor=executor, poi_source=poi_source, geo_source=geo_source
    )
    grounded = ground(retrieval_ctx)
    zone_context_cache.put(
        citta, zona, ZoneContext(retrieval=retrieval_ctx, grounded=grounded)
    )
    contesto_hash = fingerprint(retrieval_ctx["pois"])
    poi_out = _build_poi_list(retrieval_ctx, grounded)
    return _structured_response(
        citta,
        zona,
        poi_out,
        grounded,
        latenza_ms=_elapsed_ms(start),
        fallback=False,
        contesto_hash=contesto_hash,
        narrativa=None,
    )


class ZoneNarrativeRequest(BaseModel):
    """Body di ``POST /analyze/narrative`` (#259)."""

    citta: str = Field(
        max_length=100, description="Città dell'analisi in corso (stessa di /analyze)."
    )
    zona: str = Field(
        max_length=200, description="Zona dell'analisi in corso (stessa di /analyze)."
    )
    domanda: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Domanda libera (opzionale), stessa semantica di "
            "AnalyzeRequest.domanda (#119)."
        ),
    )
    contesto_hash: str = Field(
        max_length=64,
        description=(
            "Impronta del contesto ricevuta dalla fase 1 di /analyze (#242), "
            "rimandata verbatim. Confrontata, mai usata per costruire il prompt."
        ),
    )


class ZoneNarrativeResponse(BaseModel):
    """Narrativa di zona generata in fase 2 (#259): solo testo + provenienza."""

    narrativa: str
    narrativa_fonti: SourceProse
    tokens_input: int = Field(ge=0)
    tokens_output: int = Field(ge=0)
    latenza_ms: int = Field(ge=0)
    repro: Repro
    fallback: bool = Field(
        default=False,
        description="True se l'LLM è caduto: response con narrativa vuota.",
    )


async def run_zone_narrative(
    citta: str,
    zona: str,
    *,
    contesto_hash: str,
    executor: RiskProfiler,
    llm_client: _LLMClientLike,
    domanda: str | None = None,
    poi_source: PoiSource | None = None,
    geo_source: GeoSource | None = None,
    request_token_budget: int = DEFAULT_REQUEST_TOKEN_BUDGET,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> ZoneNarrativeResponse:
    """Fase 2 (#259): genera la narrativa sul contesto già scaldato da
    :func:`run_analysis_fast`, a cache fredda lo ricostruisce.

    Solleva :class:`~crime_risk_analyzer.poi_narrative.ContextMismatchError`
    (-> 409, stesso registro di ``errors.py`` già usato da ``/analyze/poi``)
    se ``contesto_hash`` non identifica il contesto che si userebbe. Su
    :class:`LLMError` ritorna narrativa vuota con ``fallback=True``, come il
    percorso POI. ``request_token_budget``/``max_tokens`` (#210): stessi
    parametri di :func:`~crime_risk_analyzer.orchestrator.run_analysis`,
    propagati da ``Settings`` dalla rotta — questa è ormai l'unica chiamata a
    ``generate_analysis`` che può sforare il TPM del provider, quindi deve
    rispettare lo stesso budget configurabile, non i default hardcoded.
    """
    start = time.perf_counter()
    cached = zone_context_cache.get(citta, zona)
    ricostruito = cached is None
    if cached is None:
        retrieval_ctx = await retrieve(
            citta, zona, executor=executor, poi_source=poi_source, geo_source=geo_source
        )
        grounded = ground(retrieval_ctx)
        cached = ZoneContext(retrieval=retrieval_ctx, grounded=grounded)

    if fingerprint(cached["retrieval"]["pois"]) != contesto_hash:
        raise ContextMismatchError(
            f"il contesto di {citta}/{zona} non e' quello dell'analisi che hai "
            "davanti: rilancia l'analisi di zona"
        )
    if ricostruito:
        zone_context_cache.put(citta, zona, cached)

    try:
        gen = await generate_analysis(
            dict(cached["grounded"]),
            llm_client,
            domanda=domanda,
            request_token_budget=request_token_budget,
            max_tokens=max_tokens,
        )
    except LLMError as exc:
        logger.warning(
            "Generazione narrativa di zona fallita per %s/%s: fallback strutturato "
            "(narrativa vuota). Causa: %s",
            citta,
            zona,
            exc,
        )
        return ZoneNarrativeResponse(
            narrativa="",
            narrativa_fonti=SourceProse(),
            tokens_input=0,
            tokens_output=0,
            latenza_ms=_elapsed_ms(start),
            repro=Repro(temperature=0.0, seed=0, prompt_hash=""),
            fallback=True,
        )

    return ZoneNarrativeResponse(
        narrativa=gen.narrativa,
        narrativa_fonti=parse_source_prose(gen.narrativa),
        tokens_input=gen.tokens_input,
        tokens_output=gen.tokens_output,
        latenza_ms=_elapsed_ms(start),
        repro=gen.repro,
        fallback=False,
    )
