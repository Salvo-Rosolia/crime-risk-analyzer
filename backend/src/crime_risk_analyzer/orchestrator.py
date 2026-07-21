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

from pydantic import BaseModel, Field, model_validator

from crime_risk_analyzer.i18n.terminus_labels import label_en, label_it
from crime_risk_analyzer.llm.client import LLMError, LLMResponse
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.models.vocab import Confidence, ConfidenceSummary
from crime_risk_analyzer.rag.generation import (
    Repro,
    RiskItem,
    RiskModel,
    SourceProse,
    generate_analysis,
    parse_source_prose,
)
from crime_risk_analyzer.rag.grounding import (
    GroundedContext,
    confidence_from_poi_name,
    ground,
)
from crime_risk_analyzer.rag.retrieval import (
    GeoSource,
    PoiSource,
    RetrievalContext,
    RetrievalStats,
    retrieve,
)


class AnalyzeRequest(BaseModel):
    """Body di ``POST /analyze`` (naming ASCII)."""

    citta: str = Field(
        max_length=100,
        description=(
            "Citta' da analizzare. Autocomplete via GET /cities (suggerimenti, "
            "non un vincolo). max_length=100: un nome di comune ci sta ampiamente "
            "e chiude la superficie free-text verso Nominatim e la chiave di "
            "_CACHE (#170)."
        ),
    )
    zona: str = Field(
        max_length=200,
        description=(
            "Zona/quartiere da analizzare. max_length=200: un nome di "
            "zona/quartiere ci sta ampiamente, mentre il tetto chiude la "
            "superficie del free-text che finisce nella query Nominatim e nella "
            "chiave di _CACHE (#170)."
        ),
    )
    domanda: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Domanda libera (opzionale) iniettata come input NON fidato (fenced) "
            "nello user_content del prompt LLM (#119); None/vuota = prompt "
            "invariato. max_length=500: una domanda in linguaggio naturale di un "
            "operatore ci sta ampiamente, mentre il tetto limita token/costo/"
            "latenza e riduce la superficie di prompt-injection."
        ),
    )


class BaselineRequest(BaseModel):
    """Body di ``POST /analyze/baseline`` (ablation, senza LLM)."""

    citta: str = Field(
        max_length=100,
        description=(
            "Citta' da analizzare. Autocomplete via GET /cities (suggerimenti, "
            "non un vincolo). max_length=100: un nome di comune ci sta ampiamente "
            "e chiude la superficie free-text verso Nominatim e la chiave di "
            "_CACHE (#170)."
        ),
    )
    zona: str = Field(
        max_length=200,
        description=(
            "Zona/quartiere da analizzare. max_length=200: come in "
            "``AnalyzeRequest``, chiude la superficie del free-text verso "
            "Nominatim e la chiave di _CACHE (#170)."
        ),
    )
    tipo_poi: str | None = Field(
        default=None,
        description=(
            "Filtro server-side per classe TERMINUS del POI (opzionale, #119); "
            "None/vuoto = nessun filtro."
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
        description=(
            "speculativo se il POI e' fuori ontologia (nessun rischio); altrimenti "
            "confermato se ha un nome OSM o plausibile se e' anonimo (unificata coi "
            "livelli per-rischio, #202)."
        )
    )
    sparql_path: str | None = None
    terminus_label_it: str = Field(
        default="", description="Etichetta IT controllata della classe (display)."
    )
    terminus_label_en: str = Field(
        default="", description="Etichetta EN corretta della classe (display)."
    )

    @model_validator(mode="after")
    def _fill_labels(self) -> PoiOut:
        if not self.terminus_label_it:
            self.terminus_label_it = label_it(self.terminus_class)
        if not self.terminus_label_en:
            self.terminus_label_en = label_en(self.terminus_class)
        return self


class AnalyzeResponse(BaseModel):
    """Schema canonico di ``/analyze`` (backend/orchestrator.md)."""

    citta: str
    zona_normalizzata: str
    poi: list[PoiOut]
    risk_models: list[RiskModel]
    narrativa: str
    narrativa_fonti: SourceProse = Field(
        default_factory=SourceProse,
        description=(
            "Prosa della narrativa suddivisa per fonte (display, additivo). "
            "Vuoto in baseline/fallback."
        ),
    )
    confidence_summary: ConfidenceSummary
    llm_used: str
    latenza_ms: int = Field(ge=0)
    tokens_input: int = Field(
        default=0,
        ge=0,
        description="Token di input fatturati (0 in baseline/fallback).",
    )
    tokens_output: int = Field(
        default=0,
        ge=0,
        description="Token di output generati (0 in baseline/fallback).",
    )
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

    La ``confidence`` per-POI e' UNIFICATA col livello per-rischio del grounding
    (#202/M1): ``speculativo`` se il POI e' fuori ontologia (nessun rischio),
    altrimenti la stessa regola nome->verificabilita' dei suoi rischi
    (:func:`confidence_from_poi_name`), cosi' il badge del POI non diverge dai
    livelli dei rischi che porta.

    Invariante: ``grounded["validated_risks"]`` ha stesso ordine e lunghezza di
    ``retrieval_ctx["pois"]``. ``strict=True`` esplicita l'errore se si rompe.
    """
    out: list[PoiOut] = []
    for poi, vr in zip(retrieval_ctx["pois"], grounded["validated_risks"], strict=True):
        confidence: Confidence = (
            confidence_from_poi_name(poi["name"]) if vr["risks"] else "speculativo"
        )
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


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _structured_response(
    citta: str,
    zona: str,
    poi_out: list[PoiOut],
    grounded: GroundedContext,
    *,
    latenza_ms: int,
    fallback: bool,
) -> AnalyzeResponse:
    """Assembla la AnalyzeResponse SENZA LLM (baseline e fallback di /analyze)."""
    return AnalyzeResponse(
        citta=citta,
        zona_normalizzata=zona,
        poi=poi_out,
        risk_models=_risk_models_from_grounded(grounded),
        narrativa="",
        confidence_summary=ConfidenceSummary.model_validate(
            grounded["confidence_summary"]
        ),
        llm_used="",
        latenza_ms=latenza_ms,
        repro=Repro(temperature=0.0, seed=0, prompt_hash=""),
        cache_hit=False,
        fallback=fallback,
    )


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
    poi_source: PoiSource | None = None,
    geo_source: GeoSource | None = None,
    domanda: str | None = None,
) -> AnalyzeResponse:
    """Esegue la pipeline completa e assembla la response canonica.

    ``retrieve`` (async) -> ``ground`` (sync) -> ``generate_analysis`` (async).
    Su :class:`LLMError` ritorna i soli dati strutturati (``fallback=True``).
    ``latenza_ms`` e' end-to-end sull'intera pipeline.

    ``domanda`` (opzionale, #119) e' la domanda libera dell'utente: viene
    propagata a :func:`generate_analysis` e iniettata nello ``user_content`` del
    prompt LLM; ``None`` = comportamento invariato.

    ``geo_source`` (opzionale, #169) e' propagato a :func:`retrieve` per il replay
    del geo nell'harness di eval; ``None`` = geocoding live (prodotto invariato).
    """
    start = time.perf_counter()
    retrieval_ctx = await retrieve(
        citta, zona, executor=executor, poi_source=poi_source, geo_source=geo_source
    )
    grounded = ground(retrieval_ctx)
    poi_out = _build_poi_list(retrieval_ctx, grounded)
    try:
        gen = await generate_analysis(dict(grounded), llm_client, domanda=domanda)
        tokens_input = gen.tokens_input
        tokens_output = gen.tokens_output
    except LLMError:
        tokens_input = 0
        tokens_output = 0
        return _structured_response(
            citta, zona, poi_out, grounded, latenza_ms=_elapsed_ms(start), fallback=True
        )
    return AnalyzeResponse(
        citta=citta,
        zona_normalizzata=zona,
        poi=poi_out,
        risk_models=gen.risk_models,
        narrativa=gen.narrativa,
        narrativa_fonti=parse_source_prose(gen.narrativa),
        confidence_summary=gen.confidence_summary,
        llm_used=gen.llm_used,
        latenza_ms=_elapsed_ms(start),
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        repro=gen.repro,
        cache_hit=gen.cache_hit,
        fallback=False,
    )


def _filter_pois_by_type(
    ctx: RetrievalContext, terminus_class: str
) -> RetrievalContext:
    """Restringe il ``RetrievalContext`` ai soli POI di classe TERMINUS data.

    Filtra ``pois`` per ``terminus_class`` PRIMA del grounding, cosi' la lista di
    POI e i rischi validati restano in lockstep (l'invariante di zip in
    :func:`_build_poi_list`). Pota ``profiles`` alle sole classi superstiti e
    ricalcola ``stats``; ``geo``/``zona``/``citta`` restano invariati.
    """
    pois = [poi for poi in ctx["pois"] if poi["terminus_class"] == terminus_class]
    classes = {poi["terminus_class"] for poi in pois}
    profiles = {cls: ctx["profiles"][cls] for cls in classes}
    return RetrievalContext(
        citta=ctx["citta"],
        zona=ctx["zona"],
        geo=ctx["geo"],
        pois=pois,
        profiles=profiles,
        stats=RetrievalStats(n_pois=len(pois), n_classes=len(profiles)),
    )


async def run_baseline(
    citta: str,
    zona: str,
    *,
    executor: RiskProfiler,
    poi_source: PoiSource | None = None,
    geo_source: GeoSource | None = None,
    tipo_poi: str | None = None,
) -> AnalyzeResponse:
    """Pipeline baseline: retrieve -> ground -> serializza (NESSUN LLM).

    ``tipo_poi`` (opzionale, #119) filtra i POI server-side per classe TERMINUS
    (:func:`_filter_pois_by_type`), applicato prima del grounding. ``None`` o
    stringa vuota/whitespace = nessun filtro (comportamento invariato).

    ``geo_source`` (opzionale, #169) e' propagato a :func:`retrieve` per il replay
    del geo nell'harness di eval; ``None`` = geocoding live (prodotto invariato).
    """
    start = time.perf_counter()
    retrieval_ctx = await retrieve(
        citta, zona, executor=executor, poi_source=poi_source, geo_source=geo_source
    )
    tipo = (tipo_poi or "").strip()
    if tipo:
        retrieval_ctx = _filter_pois_by_type(retrieval_ctx, tipo)
    grounded = ground(retrieval_ctx)
    poi_out = _build_poi_list(retrieval_ctx, grounded)
    return _structured_response(
        citta, zona, poi_out, grounded, latenza_ms=_elapsed_ms(start), fallback=False
    )
