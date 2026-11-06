"""Phase 1+2 of ``/analyze`` without blocking on the narrative (#259).

Sibling module of :mod:`~crime_risk_analyzer.poi_narrative` (#197): same
pattern — it calls ``retrieve``/``ground`` directly, does not touch the body of
``orchestrator.run_analysis`` — applied at the zone level instead of the single
POI. ``run_analysis_fast`` has replaced ``run_analysis`` on the
``POST /analyze`` route: same retrieve+ground, no LLM call — the response has
``narrativa=None`` (#259 phase 1) — and it is the only place that warms
``zone_context_cache`` for the following clicks. The narrative arrives with
``run_zone_narrative`` (``POST /analyze/narrativa``), which reads the context
(warm or rebuilt, same pattern as ``run_poi_narrative``) and generates.
"""

from __future__ import annotations

import logging
import time

from pydantic import BaseModel, Field, field_validator

from crime_risk_analyzer import zone_context_cache
from crime_risk_analyzer.context_fingerprint import (
    ContextHash,
    active_sources_id,
    fingerprint,
    istat_version_for,
)
from crime_risk_analyzer.geocoding import ZoneNotFoundError
from crime_risk_analyzer.istat.response_fields import IstatResponseFields
from crime_risk_analyzer.llm.client import LLMError
from crime_risk_analyzer.orchestrator import (
    AnalyzeResponse,
    PoiSource,
    RiskProfiler,
    _build_poi_list,  # pyright: ignore[reportPrivateUsage]
    _elapsed_ms,  # pyright: ignore[reportPrivateUsage]
    _filter_pois_by_radius,  # pyright: ignore[reportPrivateUsage]
    _LLMClientLike,  # pyright: ignore[reportPrivateUsage]
    _structured_response,  # pyright: ignore[reportPrivateUsage]
    _zero_poi_message,  # pyright: ignore[reportPrivateUsage]
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
    radius_m: float | None = None,
    istat_context_enabled: bool = False,
) -> AnalyzeResponse:
    """Phase 1 (#259): structured data right away, ``narrativa=None``.

    ``retrieve`` -> ``ground`` -> warm ``zone_context_cache``: the real narrative
    arrives with :func:`run_zone_narrative`, which re-reads this same cache, and
    so does ``/analyze/poi`` at every click. Writing to the cache happens ONLY
    here (#292): the evaluation paths
    (:func:`~crime_risk_analyzer.orchestrator.run_analysis` and the ablated arm)
    do not write to it, because nobody re-reads that context there.

    ``radius_m`` (optional, #318) filters the POIs server-side within the radius
    from the geocoded centre (``_filter_pois_by_radius``), same pattern as
    ``run_baseline``: applied BEFORE grounding, so the zone cache is warmed with
    the context ALREADY filtered. ``None`` = no radius filter (behaviour
    unchanged).

    ``istat_context_enabled`` (#346): decides whether ``poi[].istat`` reaches the
    client (order of the risks in the cards). Writing to the cache does not depend
    on it: grounding always computes the ``IstatPoi``. When on, the version of
    the ISTAT data also enters ``contesto_hash`` (#354): phase 2 and
    ``/analyze/poi`` compare it with the same switch, and a data update in the
    meantime gives a 409.
    """
    start = time.perf_counter()
    retrieval_ctx = await retrieve(
        citta, zona, executor=executor, poi_source=poi_source, geo_source=geo_source
    )
    if radius_m is not None:
        lat, lon = retrieval_ctx["geo"]["lat"], retrieval_ctx["geo"]["lon"]
        retrieval_ctx = _filter_pois_by_radius(retrieval_ctx, lat, lon, radius_m)
    grounded = ground(retrieval_ctx)
    zone_context_cache.put(
        citta, zona, ZoneContext(retrieval=retrieval_ctx, grounded=grounded)
    )
    contesto_hash = fingerprint(
        retrieval_ctx["pois"],
        istat_version=istat_version_for(istat_context_enabled),
        sources_id=active_sources_id(),
    )
    poi_out = _build_poi_list(
        retrieval_ctx, grounded, istat_context_enabled=istat_context_enabled
    )
    return _structured_response(
        citta,
        zona,
        poi_out,
        grounded,
        latenza_ms=_elapsed_ms(start),
        fallback=False,
        contesto_hash=contesto_hash,
        geo=retrieval_ctx["geo"],
        narrativa=None,
    )


class ZoneNarrativeRequest(BaseModel):
    """Body of ``POST /analyze/narrativa`` (#259).

    It carries ``domanda`` but not ``tipo_poi``: the asymmetry with
    ``BaselineRequest`` (which carries ``tipo_poi`` but not ``domanda``) is
    accepted and documented (#263, closed), not closed up; the ``tipo_poi``
    contract is fixed by #143 (``GET /poi-types`` catalogue). See
    ``BaselineRequest`` in :mod:`~crime_risk_analyzer.orchestrator`.
    """

    citta: str = Field(
        min_length=1,
        max_length=100,
        description="Città dell'analisi in corso (stessa di /analyze).",
    )
    zona: str = Field(
        min_length=1,
        max_length=200,
        description="Zona dell'analisi in corso (stessa di /analyze).",
    )
    domanda: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Domanda libera (opzionale) iniettata come input NON fidato (fenced) "
            "nello user_content del prompt LLM (#119); None/vuota = prompt "
            "invariato. Unico posto in cui vive dopo lo split (#292): la fase 1 "
            "non chiama il modello. max_length=500: una domanda in linguaggio "
            "naturale di un operatore ci sta ampiamente, mentre il tetto limita "
            "token/costo/latenza e riduce la superficie di prompt-injection."
        ),
    )
    contesto_hash: ContextHash

    @field_validator("citta", "zona", mode="before")
    @classmethod
    def _strip_text(cls, v: object) -> object:
        """Edge spaces removed BEFORE ``min_length``/``max_length`` (#497).

        A blank value is rejected (422) before any geocoding, and the cap is
        measured on the value that would reach Nominatim, as in
        :class:`~crime_risk_analyzer.orchestrator.AnalyzeRequest`.
        """
        return v.strip() if isinstance(v, str) else v


class ZoneNarrativeResponse(IstatResponseFields):
    """Zone narrative generated in phase 2 (#259): only text + provenance.

    The three ``istat_*`` fields come from
    :class:`~crime_risk_analyzer.istat.response_fields.IstatResponseFields`, the
    base shared with ``AnalyzeResponse``/``PoiNarrativeResponse`` (#345).
    """

    narrativa: str
    narrativa_fonti: SourceProse
    llm_used: str = Field(
        description=(
            "Model id esatto che ha scritto la narrativa (stessa fonte del campo "
            "omonimo di AnalyzeResponse: il generation layer). Osservabilita' "
            "dello switch manuale Claude/Groq, che e' il perno del confronto fra "
            "i due modelli: dopo lo split (#292) la fase 1 non chiama il modello "
            "e senza questo campo nessuna delle due risposte direbbe chi ha "
            "scritto il testo. Vuoto nel fallback: nessun modello ha prodotto "
            "nulla. Identita' del modello, non una misura: nessuno scoring."
        )
    )
    tokens_input: int = Field(ge=0)
    tokens_output: int = Field(ge=0)
    latenza_ms: int = Field(ge=0)
    repro: Repro
    fallback: bool = Field(
        default=False,
        description="True se l'LLM è caduto: response con narrativa vuota.",
    )
    messaggio: str | None = Field(
        default=None,
        description=(
            "Messaggio esplicito quando la zona non ha POI E questa risposta "
            "non porta narrativa reale (#260). Ricalcolato qui, non ereditato "
            "dalla fase 1 (``AnalyzeResponse.messaggio``): solo questa risposta "
            "sa se la narrativa appena generata copre gia' il caso, quindi e' "
            "l'unico valore di cui un consumer si puo' fidare come piu' fresco."
        ),
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
    istat_context_enabled: bool = False,
    istat_scelta_modello: bool = False,
) -> ZoneNarrativeResponse:
    """Phase 2 (#259): generates the narrative on the context already warmed by
    :func:`run_analysis_fast`, rebuilding it on a cold cache.

    Raises :class:`~crime_risk_analyzer.poi_narrative.ContextMismatchError`
    (-> 409, same registry of ``errors.py`` already used by ``/analyze/poi``)
    if ``contesto_hash`` does not identify the context that would be used. On
    :class:`LLMError` it returns an empty narrative with ``fallback=True``, like
    the POI path. ``request_token_budget``/``max_tokens`` (#210): same
    parameters as :func:`~crime_risk_analyzer.orchestrator.run_analysis`,
    propagated from ``Settings`` by the route — this is now the only call to
    ``generate_analysis`` that can overrun the provider's TPM, so it must
    respect the same configurable budget, not the hardcoded defaults.

    On a cold cache without ``geo_source`` (the real case of the route: the
    client sends back only ``citta``/``zona``, never the original area) the
    rebuild goes through a FORWARD geocode
    (:func:`~crime_risk_analyzer.geocoding.geocode_zone`) of the labels. In the
    citta + zona mode they are the typed text (``area_search.resolve_zone``), so
    the rebuild finds the same area again. In the circle, instead, the label comes
    from a reverse geocode of the centre (#318): almost never a string that
    Nominatim finds again when searching forward, and always impossible in the
    fallback case (``"area lat,lon"``/``"zona non identificata"``, D9 of the
    design doc). The resulting
    :class:`~crime_risk_analyzer.geocoding.ZoneNotFoundError` becomes here the
    same :class:`ContextMismatchError` as the ``contesto_hash`` branch -> 409, not
    a 422 "zone not geocodable": the context is not badly written, it has simply
    expired/been evicted, and the way out is the same, re-run the zone analysis
    (which goes through ``resolve_circle``/``resolve_zone`` again). A generic
    :class:`~crime_risk_analyzer.geocoding.GeocodingError` (Nominatim
    unreachable) INSTEAD stays a 503 not caught here: it is a real service
    failure, not an unsearchable label, and re-running the analysis would not
    fix it.
    """
    start = time.perf_counter()
    cached = zone_context_cache.get(citta, zona)
    rebuilt = cached is None
    if cached is None:
        try:
            retrieval_ctx = await retrieve(
                citta,
                zona,
                executor=executor,
                poi_source=poi_source,
                geo_source=geo_source,
            )
        except ZoneNotFoundError as exc:
            raise ContextMismatchError(
                f"il contesto di {citta}/{zona} non e' piu' ricostruibile: rilancia "
                "l'analisi di zona"
            ) from exc
        grounded = ground(retrieval_ctx)
        cached = ZoneContext(retrieval=retrieval_ctx, grounded=grounded)

    current_hash = fingerprint(
        cached["retrieval"]["pois"],
        istat_version=istat_version_for(istat_context_enabled),
        sources_id=active_sources_id(),
    )
    if current_hash != contesto_hash:
        raise ContextMismatchError(
            f"il contesto di {citta}/{zona} non e' quello dell'analisi che hai "
            "davanti: rilancia l'analisi di zona"
        )
    if rebuilt:
        zone_context_cache.put(citta, zona, cached)

    n_poi = len(cached["retrieval"]["pois"])

    try:
        gen = await generate_analysis(
            dict(cached["grounded"]),
            llm_client,
            domanda=domanda,
            request_token_budget=request_token_budget,
            max_tokens=max_tokens,
            istat=istat_context_enabled,
            istat_scelta=istat_scelta_modello,
        )
    except LLMError as exc:
        logger.warning(
            "Zone narrative generation failed for %s/%s: structured fallback "
            "(empty narrative). Cause: %s",
            citta,
            zona,
            exc,
        )
        return ZoneNarrativeResponse(
            narrativa="",
            narrativa_fonti=SourceProse(),
            # No model wrote anything: same choice as ``_structured_response``
            # on the no-LLM branch, not an invented id.
            llm_used="",
            tokens_input=0,
            tokens_output=0,
            latenza_ms=_elapsed_ms(start),
            repro=Repro(temperature=0.0, seed=0, prompt_hash=""),
            fallback=True,
            messaggio=_zero_poi_message(n_poi, ""),
        )

    return ZoneNarrativeResponse(
        narrativa=gen.narrativa,
        narrativa_fonti=parse_source_prose(gen.narrativa),
        llm_used=gen.llm_used,
        tokens_input=gen.tokens_input,
        tokens_output=gen.tokens_output,
        latenza_ms=_elapsed_ms(start),
        repro=gen.repro,
        fallback=False,
        messaggio=_zero_poi_message(n_poi, gen.narrativa),
        istat_attivo=gen.istat_attivo,
        istat_versione_dati=gen.istat_versione_dati,
        istat_frasi_scartate=gen.istat_frasi_scartate,
    )
