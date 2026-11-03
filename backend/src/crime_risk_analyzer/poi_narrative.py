"""Narrative of the selected POI: orchestration and contract (#197).

It reuses the zone context from the cache (:mod:`zone_context_cache`) and on a
cold cache rebuilds it: ``retrieve`` -> ``ground``. Then it narrows down to the
requested POI, computes neighbourhood and composition, generates the prose.

The POI is identified by ``poi_id`` alone and everything else — class, risks,
ontological path — is RE-DERIVED by the server: the client cannot inject
risks, which is the premise of the claim of non-hallucinability of the data.

The context used is VERIFIED against the one shown (#242): the client sends the
fingerprint received from ``/analyze`` and here it is compared with that of the
context that would be used. Neither the cache nor the reconstruction are accepted
blindly — the first may have been overwritten by a re-analysis of the same zone,
the second may land on a different OSM capture. If they diverge, we refuse with
:class:`ContextMismatchError` (409) instead of anchoring the prose to points that
are not on screen.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from crime_risk_analyzer import zone_context_cache
from crime_risk_analyzer.context_fingerprint import (
    ContextHash,
    active_sources_id,
    fingerprint,
    istat_version_for,
)
from crime_risk_analyzer.geocoding import ZoneNotFoundError
from crime_risk_analyzer.i18n.terminus_labels import label_it
from crime_risk_analyzer.istat.response_fields import IstatResponseFields
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
    "ContextMismatchError",
    "PoiNarrativeRequest",
    "PoiNarrativeResponse",
    "PoiNotFoundError",
    "run_poi_narrative",
]


class PoiNotFoundError(Exception):
    """The ``poi_id`` does not belong to the context of the indicated zone."""


class ContextMismatchError(Exception):
    """The client's fingerprint does not identify the context that would be used (#242).

    The context shown to the user and the one available here diverge: cache
    overwritten by a re-analysis of the same zone, or a cold-cache reconstruction
    on a different OSM capture. Generating anyway would produce prose
    anchored to points that are not on screen.
    """


class PoiNarrativeRequest(BaseModel):
    """Body of ``POST /analyze/poi``."""

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
    contesto_hash: ContextHash


class PoiNarrativeResponse(IstatResponseFields):
    """Narrative of the single POI: prose, sources, citable risks, provenance.

    The three ``istat_*`` fields come from
    :class:`~crime_risk_analyzer.istat.response_fields.IstatResponseFields`, the
    base shared with ``AnalyzeResponse``/``ZoneNarrativeResponse`` (#345).
    """

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
    """RiskModel of the POI alone, for the source tags and frontend citations.

    ``RiskModel`` has exactly three fields (``poi_id``, ``poi``, ``risks``): the
    TERMINUS class, the vulnerabilities and the ``sparql_path`` do NOT live here — the
    frontend already has them in ``PoiOut`` from the zone analysis. Same construction
    as ``orchestrator._risk_models_from_grounded``, for a single POI.
    """
    return RiskModel(
        poi_id=vr["poi_id"],
        poi=vr["poi"],
        risks=[
            RiskItem(
                hazard=r["hazard"],
                confidence=r["confidence"],
                tag=r["tag"],
                source=r["source"],
            )
            for r in vr["risks"]
        ],
    )


async def run_poi_narrative(
    citta: str,
    zona: str,
    poi_id: str,
    *,
    contesto_hash: str,
    executor: RiskProfiler,
    llm_client: _LLMClientLike,
    poi_source: PoiSource | None = None,
    geo_source: GeoSource | None = None,
    istat_context_enabled: bool = False,
) -> PoiNarrativeResponse:
    """Generates the narrative of the POI ``poi_id`` in the indicated zone.

    Raises :class:`ContextMismatchError` (-> 409) if ``contesto_hash`` does not
    identify the context that would be used: the invariant is that the prose arises
    on the SHOWN context, and it holds both with a warm cache (zone re-analysed from
    another tab: the cache is no longer that of the current analysis) and with a
    cold cache (reconstruction on a different OSM capture). The comparison precedes
    every LLM call: a rejection costs no tokens.

    Raises :class:`PoiNotFoundError` if the POI is not in the context (POI
    vanished from OSM, or fell outside the ``MAX_POIS`` cap between two captures): the
    registry in :mod:`errors` translates it to 404. On :class:`LLMError` it returns
    only the structured data with ``fallback=True``, like the zone path.

    On a cold cache without ``geo_source`` (the real case of the route: the client
    sends back only ``citta``/``zona``, never the original area) the reconstruction
    goes through a FORWARD geocode
    (:func:`~crime_risk_analyzer.geocoding.geocode_zone`) of the labels. In the
    city + zone mode they are the typed text (``area_search.resolve_zone``), so
    the reconstruction finds the same area again. In the circle, instead, the
    label comes from a reverse geocode of the centre (#318): almost never a string
    that Nominatim finds when searching forward, and always impossible in the
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

    pois = cached["retrieval"]["pois"]
    # Is the context that would be used the one shown? (#242) Comparison before the
    # POI lookup and before any generation: if the fingerprint does not
    # match, the POI present is irrelevant, and a rejection must not cost
    # tokens. The fingerprint is only compared: it does not enter the prompt.
    if (
        fingerprint(
            pois,
            istat_version=istat_version_for(istat_context_enabled),
            sources_id=active_sources_id(),
        )
        != contesto_hash
    ):
        raise ContextMismatchError(
            f"il contesto di {citta}/{zona} non e' quello dell'analisi che hai "
            "davanti: rilancia l'analisi di zona"
        )
    # Writing to the cache happens AFTER the comparison: a rebuilt and rejected
    # context was never in front of anyone, and storing it would take up
    # one of the MAX_ZONES slots, evicting, with a full cache, the valid context of
    # another zone (backend review M1).
    if rebuilt:
        zone_context_cache.put(citta, zona, cached)
    # NB: from here to the building of the prompt there is no ``await``, and ``pois``
    # is a local reference to a list that nobody mutates. A concurrent ``/analyze``
    # that overwrites the cache entry therefore cannot make the prose be generated
    # on a list different from the one just compared: inserting an
    # ``await`` in between would break this property.
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
            poi_label_it=label_it(poi["ontology_class"]),
            risks=vr["risks"],
            # Only the name goes to the prompt: the citation that #256 adds is for
            # the UI. So the text of the per-POI prompt stays identical.
            vulnerabilities=[v["name"] for v in vr["vulnerabilities"]],
            sparql_path=vr["sparql_path"],
            neighbours=neighbours,
            zone_summary=zone_summary,
            llm_client=llm_client,
            istat=vr.get("istat") if istat_context_enabled else None,
        )
    except LLMError as exc:
        logger.warning(
            "POI narrative generation failed for %s/%s poi=%s: structured "
            "fallback (empty narrative). Cause: %s",
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
        istat_attivo=generated.istat_attivo,
        istat_versione_dati=generated.istat_versione_dati,
        istat_frasi_scartate=generated.istat_frasi_scartate,
    )
