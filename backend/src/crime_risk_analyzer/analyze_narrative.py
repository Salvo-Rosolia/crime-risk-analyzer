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

import time

from crime_risk_analyzer import zone_context_cache
from crime_risk_analyzer.context_fingerprint import fingerprint
from crime_risk_analyzer.orchestrator import (
    AnalyzeResponse,
    PoiSource,
    RiskProfiler,
    _build_poi_list,  # pyright: ignore[reportPrivateUsage]
    _elapsed_ms,  # pyright: ignore[reportPrivateUsage]
    _structured_response,  # pyright: ignore[reportPrivateUsage]
)
from crime_risk_analyzer.rag.grounding import ground
from crime_risk_analyzer.rag.retrieval import GeoSource, retrieve
from crime_risk_analyzer.zone_context_cache import ZoneContext

__all__ = ["run_analysis_fast"]


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
