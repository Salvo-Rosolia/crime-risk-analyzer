"""Narrativa del POI selezionato: orchestrazione e contratto (#197).

Riusa il contesto di zona dalla cache (:mod:`zone_context_cache`) e a cache
fredda lo ricostruisce: ``retrieve`` -> ``ground``. Poi restringe al POI
richiesto, calcola vicinato e composizione, genera la prosa.

Il POI e' identificato dal solo ``poi_id`` e tutto il resto — classe, rischi,
percorso ontologico — e' RI-DERIVATO dal server: il client non puo' iniettare
rischi, che e' il presupposto del claim di non-allucinabilita' dei dati.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from crime_risk_analyzer import zone_context_cache
from crime_risk_analyzer.i18n.terminus_labels import label_it
from crime_risk_analyzer.llm.client import LLMError
from crime_risk_analyzer.orchestrator import (
    GeoSource,
    PoiSource,
    RiskProfiler,
    _LLMClientLike,  # pyright: ignore[reportPrivateUsage]
)
from crime_risk_analyzer.rag.generation import Repro, RiskItem, RiskModel, SourceProse
from crime_risk_analyzer.rag.grounding import ValidatedRisk, ground
from crime_risk_analyzer.rag.poi_context import nearest_neighbours, zone_composition
from crime_risk_analyzer.rag.poi_generation import generate_poi_narrative
from crime_risk_analyzer.rag.retrieval import retrieve
from crime_risk_analyzer.zone_context_cache import ZoneContext

logger = logging.getLogger(__name__)

__all__ = [
    "PoiNarrativeRequest",
    "PoiNarrativeResponse",
    "PoiNotFoundError",
    "run_poi_narrative",
]


class PoiNotFoundError(Exception):
    """Il ``poi_id`` non appartiene al contesto della zona indicata."""


class PoiNarrativeRequest(BaseModel):
    """Body di ``POST /analyze/poi``."""

    citta: str = Field(
        max_length=100,
        description="Citta' dell'analisi di zona in corso (stessa di /analyze).",
    )
    zona: str = Field(
        max_length=200,
        description="Zona dell'analisi in corso (stessa di /analyze).",
    )
    poi_id: str = Field(
        max_length=100,
        description=(
            "Id del POI dall'analisi di zona. E' l'UNICO dato che il client "
            "fornisce sul punto: classe, rischi e path sono ri-derivati dal "
            "server, cosi' nessun rischio puo' essere iniettato dall'esterno."
        ),
    )


class PoiNarrativeResponse(BaseModel):
    """Narrativa del singolo POI: prosa, fonti, rischi citabili, provenienza."""

    poi_id: str
    narrativa: str
    narrativa_fonti: SourceProse
    risk_models: list[RiskModel]
    tokens_input: int = Field(ge=0)
    tokens_output: int = Field(ge=0)
    latenza_ms: int = Field(ge=0)
    repro: Repro
    fallback: bool = Field(
        default=False,
        description="True se l'LLM e' caduto: response con soli dati strutturati.",
    )


def _risk_model_of(vr: ValidatedRisk) -> RiskModel:
    """RiskModel del solo POI, per i tag fonte e le citazioni nel frontend.

    ``RiskModel`` ha esattamente due campi (``poi``, ``risks``): la classe
    TERMINUS, le vulnerabilita' e il ``sparql_path`` NON vivono qui — il
    frontend li ha gia' in ``PoiOut`` dall'analisi di zona. Stessa costruzione
    di ``orchestrator._risk_models_from_grounded``, per un solo POI.
    """
    return RiskModel(
        poi=vr["poi"],
        risks=[
            RiskItem(hazard=r["hazard"], confidence=r["confidence"], tag=r["tag"])
            for r in vr["risks"]
        ],
    )


async def run_poi_narrative(
    citta: str,
    zona: str,
    poi_id: str,
    *,
    executor: RiskProfiler,
    llm_client: _LLMClientLike,
    poi_source: PoiSource | None = None,
    geo_source: GeoSource | None = None,
) -> PoiNarrativeResponse:
    """Genera la narrativa del POI ``poi_id`` nella zona indicata.

    Solleva :class:`PoiNotFoundError` se il POI non e' nel contesto (POI
    scomparso da OSM, o caduto fuori dal cap ``MAX_POIS`` fra due catture): il
    registro in :mod:`errors` lo traduce in 404. Su :class:`LLMError` ritorna i
    soli dati strutturati con ``fallback=True``, come il percorso di zona.
    """
    cached = zone_context_cache.get(citta, zona)
    if cached is None:
        retrieval_ctx = await retrieve(
            citta, zona, executor=executor, poi_source=poi_source, geo_source=geo_source
        )
        grounded = ground(retrieval_ctx)
        cached = ZoneContext(retrieval=retrieval_ctx, grounded=grounded)
        zone_context_cache.put(citta, zona, cached)

    pois = cached["retrieval"]["pois"]
    index = next((i for i, p in enumerate(pois) if p["id"] == poi_id), None)
    if index is None:
        raise PoiNotFoundError(
            f"il POI {poi_id!r} non fa parte dell'analisi corrente di "
            f"{citta}/{zona}: rilancia l'analisi di zona"
        )

    poi = pois[index]
    vr = cached["grounded"]["validated_risks"][index]
    risk_models = [_risk_model_of(vr)]
    neighbours = nearest_neighbours(pois, poi_id)
    zone_summary = zone_composition(pois)

    try:
        generated = await generate_poi_narrative(
            citta=citta,
            zona=zona,
            poi_name=poi["name"],
            poi_label_it=label_it(poi["terminus_class"]),
            risks=vr["risks"],
            vulnerabilities=vr["vulnerabilities"],
            sparql_path=vr["sparql_path"],
            neighbours=neighbours,
            zone_summary=zone_summary,
            llm_client=llm_client,
        )
    except LLMError as exc:
        logger.warning(
            "Generazione narrativa POI fallita per %s/%s poi=%s: fallback "
            "strutturato (narrativa vuota). Causa: %s",
            citta,
            zona,
            poi_id,
            exc,
        )
        return PoiNarrativeResponse(
            poi_id=poi_id,
            narrativa="",
            narrativa_fonti=SourceProse(),
            risk_models=risk_models,
            tokens_input=0,
            tokens_output=0,
            latenza_ms=0,
            repro=Repro(temperature=0.0, seed=0, prompt_hash=""),
            fallback=True,
        )

    return PoiNarrativeResponse(
        poi_id=poi_id,
        narrativa=generated.narrativa,
        narrativa_fonti=generated.narrativa_fonti,
        risk_models=risk_models,
        tokens_input=generated.tokens_input,
        tokens_output=generated.tokens_output,
        latenza_ms=generated.latenza_ms,
        repro=generated.repro,
        fallback=False,
    )
