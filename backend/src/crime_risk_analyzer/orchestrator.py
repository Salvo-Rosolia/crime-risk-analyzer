"""Orchestrator of the ``/analyze`` pipeline (#18).

Wires the three already-ready RAG layers (retrieval #22 -> grounding #24 ->
generation #23) and serialises the canonical schema of ``/analyze``
(backend/orchestrator.md). It holds the contract models and the pure functions
(testable without HTTP) of the paths that return the canonical response:
:func:`run_baseline` (route ``POST /analyze/baseline``), :func:`run_analysis`
(full synchronous path, now only for evaluation) and
:func:`run_no_ontology_prompt` (ablation arm, evaluation only).

The two phases of the route ``POST /analyze`` + ``POST /analyze/narrativa`` (#292)
live in :mod:`~crime_risk_analyzer.analyze_narrative` and reuse the contract and
assembly from here; the FastAPI routes live in ``main.py``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel, Field, field_validator, model_validator

from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.context_fingerprint import (
    active_sources_id,
    fingerprint,
    istat_version_for,
)
from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.i18n.terminus_labels import label_en, label_it
from crime_risk_analyzer.istat.figures import CheckOutcome
from crime_risk_analyzer.istat.response_fields import IstatResponseFields
from crime_risk_analyzer.istat.rows import IstatPoi
from crime_risk_analyzer.llm.client import LLMError, LLMResponse
from crime_risk_analyzer.models.geo import haversine_m
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.models.vocab import Confidence, ConfidenceSummary
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.rag.generation import (
    DEFAULT_CONTEXT_FORMAT,
    DEFAULT_MAX_TOKENS,
    DEFAULT_REQUEST_TOKEN_BUDGET,
    ONTOLOGY_TOKEN,
    ContextFormat,
    GenerationResult,
    Repro,
    RiskItem,
    RiskModel,
    SourceProse,
    generate_analysis,
    parse_source_prose,
    zone_prompt_pois,
)
from crime_risk_analyzer.rag.grounding import (
    GroundedContext,
    confidence_from_poi_name,
    ground,
)
from crime_risk_analyzer.rag.no_ontology_generation import (
    LLM_SYNTHESIS_TOKEN,
    generate_no_ontology_analysis,
)
from crime_risk_analyzer.rag.retrieval import (
    GeoSource,
    PoiSource,
    RetrievalContext,
    RetrievalStats,
    retrieve,
)

logger = logging.getLogger(__name__)


class Center(BaseModel):
    """Centre of the circle drawn on the map (#318)."""

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class _AreaRequest(BaseModel):
    """Base of the bodies that carry the AREA to analyse, in one of the TWO modes.

    The circle drawn on the map does not replace the two text fields: the two
    modes coexist and the user uses one or the other. The body therefore carries
    EXACTLY one, and the endpoint picks the corresponding resolver
    (:mod:`crime_risk_analyzer.area_search`):

    * ``center`` + ``radius_m`` — the circle: bbox computed purely, no network;
    * ``citta`` + ``zona`` — the zone inside the city: bbox from Nominatim on
      "zona, citta" with the minimum floor. BOTH are needed: a single half
      would reach Nominatim as an ambiguous query (a zone without a city across
      all of Italy) or too wide (a whole city).

    Why "exactly one" and not a precedence: silently accepting one when both
    arrive would mean analysing an area different from the one the user thinks
    they chose, with no way to notice. Better a 422.
    """

    center: Center | None = Field(
        default=None, description="Centro del cerchio disegnato (con ``radius_m``)."
    )
    radius_m: float | None = Field(
        default=None,
        description=(
            "Raggio in metri del cerchio disegnato sulla mappa. Validato contro "
            "Settings.search_radius_min_m/search_radius_max_m (422 se fuori range)."
        ),
    )
    citta: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "Citta' da analizzare (con ``zona``), alternativa al cerchio. "
            "Autocomplete via GET /cities (suggerimenti, non un vincolo). "
            "max_length=100: un nome di comune ci sta ampiamente e chiude la "
            "superficie free-text verso Nominatim e la chiave di _CACHE (#170)."
        ),
    )
    zona: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Zona/quartiere da analizzare dentro ``citta``, alternativa al cerchio. "
            "max_length=200: un nome di zona ci sta ampiamente, mentre il tetto "
            "chiude la superficie free-text verso Nominatim e _CACHE (#170)."
        ),
    )

    @field_validator("citta", "zona", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        """Edge spaces removed; empty or whitespace-only is equivalent to ABSENT.

        Spaces must not end up in Nominatim nor in the cache. And a box
        left empty is not a request for the second mode: a client
        that serialises the form with ``citta: ""`` next to the circle sends a
        valid circle, not an ambiguous body.

        ``mode="before"``: the strip happens BEFORE ``max_length``, so the
        cap is measured on the value that will actually end up in Nominatim, and a
        whitespace-only box longer than the cap stays "empty", not a 422.
        Non-strings pass intact and are rejected by the type validation.
        """
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("radius_m")
    @classmethod
    def _radius_in_range(cls, v: float | None) -> float | None:
        if v is None:
            return None
        settings = get_settings()
        if not (settings.search_radius_min_m <= v <= settings.search_radius_max_m):
            raise ValueError(
                f"radius_m deve essere tra {settings.search_radius_min_m} e "
                f"{settings.search_radius_max_m} metri"
            )
        return v

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> _AreaRequest:
        """Exactly one mode: COMPLETE circle or non-empty citta + zona.

        The empty text fields are already ``None`` (``_strip``), so here "text"
        means at least one field with content: ``{"citta": "Roma", "zona": ""}``
        is a 422 that names the missing zone.
        """
        circle = self.center is not None or self.radius_m is not None
        text = self.citta is not None or self.zona is not None
        if circle and text:
            raise ValueError(
                "specificare il cerchio (center+radius_m) OPPURE citta e zona, "
                "non entrambi"
            )
        if not circle and not text:
            raise ValueError(
                "specificare il cerchio (center+radius_m) oppure citta e zona"
            )
        if circle and (self.center is None or self.radius_m is None):
            raise ValueError("il cerchio richiede sia center sia radius_m")
        if text and not (self.citta and self.zona):
            raise ValueError("la ricerca per zona richiede sia citta sia zona")
        return self

    @property
    def is_circle(self) -> bool:
        """True if the body carries the circle, False if it carries citta + zona.

        The validator guarantees that the chosen branch is complete: circle with
        ``center`` and ``radius_m``, or ``citta`` and ``zona`` both non-empty.
        """
        return self.center is not None


class AnalyzeRequest(_AreaRequest):
    """Body of phase 1 of ``POST /analyze``: the area, in one of the two modes.

    No ``domanda``: the route does not call the model (#292), so it has no
    prompt to inject it into. That field lives in ``ZoneNarrativeRequest``
    (:mod:`~crime_risk_analyzer.analyze_narrative`), the phase 2 request that
    really carries the operator's text to the model.
    """


class BaselineRequest(_AreaRequest):
    """Body of ``POST /analyze/baseline`` (ablation, no LLM).

    It carries ``tipo_poi`` but not ``domanda``: the asymmetry with
    ``ZoneNarrativeRequest`` (which carries ``domanda`` but not ``tipo_poi``) makes
    the full-arm vs baseline comparison not iso-input on these two parameters
    (#263). The ``tipo_poi`` contract is now fixed (#143: ``GET /poi-types``
    catalogue, normalisation to the canonical class in
    :func:`~crime_risk_analyzer.poi_types.resolve_poi_type`), but the asymmetry
    remains: it is documented here and in the test
    ``test_baseline_request_surface_is_cerchio_or_citta_zona_tipo_poi``, not closed.

    The model only does strip and length cap; the recognition of the type
    happens in the route, because an unknown type is a domain error (422
    in the ``{"errore", "messaggio"}`` format of :mod:`~crime_risk_analyzer.errors`),
    not a body shape error.
    """

    tipo_poi: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "Filtro server-side per tipo di POI (opzionale, #119/#143): nome della "
            "classe TERMINUS o etichetta IT del catalogo GET /poi-types, senza "
            "distinzione di maiuscole; None/vuoto = nessun filtro, tipo non "
            "riconosciuto = 422."
        ),
    )

    @field_validator("tipo_poi", mode="before")
    @classmethod
    def _strip_poi_type(cls, v: object) -> object:
        """Like ``_strip`` of citta/zona: strip before the cap, empty = absent."""
        if isinstance(v, str):
            return v.strip() or None
        return v


class OntologyItem(BaseModel):
    """Ontological entity of a non-hazard axis, with citation and labels (#256).

    No ``confidence`` and no ``tag``: the evidential strength is a bit derived
    from the POI name, hence identical for every ontological assertion on that
    point — the POI badge qualifies them all together — and the source is the
    ontology by construction. No numeric field: they are qualitative lists, like
    the hazards (anti-scoring legal constraint, _project.md §Vincoli).
    """

    name: str = Field(
        description="Nome-classe TERMINUS bare (es. 'Poor_surveillance')."
    )
    source: str = Field(
        description="Citazione lineare 'Classe → property → entita' dal grounding."
    )
    label_it: str = Field(default="", description="Etichetta IT controllata (display).")
    label_en: str = Field(default="", description="Etichetta EN corretta (display).")

    @model_validator(mode="after")
    def _fill_labels(self) -> OntologyItem:
        if not self.label_it:
            self.label_it = label_it(self.name)
        if not self.label_en:
            self.label_en = label_en(self.name)
        return self


class PoiOut(BaseModel):
    """POI in the canonical ``/analyze`` schema (coords + confidence + path)."""

    id: str
    name: str
    terminus_class: str
    lat: float
    lon: float
    confidence: Confidence | None = Field(
        default=None,
        description=(
            "None se il POI e' fuori ontologia (nessun rischio da qualificare); "
            "altrimenti verificato se ha un nome OSM o da_confermare se e' anonimo "
            "(unificata coi livelli per-rischio, #202)."
        ),
    )
    sparql_path: str | None = None
    terminus_label_it: str = Field(
        default="", description="Etichetta IT controllata della classe (display)."
    )
    terminus_label_en: str = Field(
        default="", description="Etichetta EN corretta della classe (display)."
    )
    critical_events: list[OntologyItem] = Field(
        default_factory=list[OntologyItem],
        description=(
            "Eventi critici della classe TERMINUS (havingCriticalEvent), ciascuno "
            "con la propria citazione (#256)."
        ),
    )
    vulnerabilities: list[OntologyItem] = Field(
        default_factory=list[OntologyItem],
        description=(
            "Vulnerabilita' della classe (isVulnerableTo + havingVulnerability): "
            "arrivavano solo al prompt, senza citazione (#256)."
        ),
    )
    stakeholders: list[OntologyItem] = Field(
        default_factory=list[OntologyItem],
        description=(
            "Stakeholder della classe (havingPerformer), ciascuno con la propria "
            "citazione: il quarto asse TERMINUS, esposto da quando il vocabolario "
            "controllato copre anche questa categoria (#270)."
        ),
    )
    istat: IstatPoi | None = Field(
        default=None,
        description=(
            "Dati ISTAT del luogo del POI (comune capoluogo o provincia, dalle "
            "coordinate del punto) collegati ai suoi hazard, gia' calcolati nel "
            "grounding (#345). Il frontend li usa per ordinare i rischi (#346) e "
            "per l'indicatore (#347). None con interruttore ISTAT spento, POI fuori "
            "da ogni poligono, nessuna voce collegata o dati assenti. Il dato e' "
            "del comune o della provincia, mai del POI. Sempre None in "
            "POST /analyze/baseline (ablation) e nei bracci di valutazione che non "
            "passano istat_context_enabled=True (run_no_ontology_prompt, e "
            "run_analysis/run_analysis_fast col default)."
        ),
    )

    @model_validator(mode="after")
    def _fill_labels(self) -> PoiOut:
        if not self.terminus_label_it:
            self.terminus_label_it = label_it(self.terminus_class)
        if not self.terminus_label_en:
            self.terminus_label_en = label_en(self.terminus_class)
        return self


class GeoZone(BaseModel):
    """Centre and bbox of the geocoded zone (#260).

    Before it did not leave the orchestrator: the frontend map could only centre
    on the POIs, so a zone with 0 results and a zone not found were
    indistinguishable on screen (in both cases the map stayed still).
    """

    lat: float
    lon: float
    bbox_min_lat: float
    bbox_min_lon: float
    bbox_max_lat: float
    bbox_max_lon: float


_ZERO_POI_MESSAGE = (
    "La zona e' stata geocodificata correttamente, ma non e' stato trovato "
    "nessun punto in questa copertura OSM/TERMINUS."
)


def _geo_zone(geo: GeoResult) -> GeoZone:
    return GeoZone(
        lat=geo["lat"],
        lon=geo["lon"],
        bbox_min_lat=geo["bbox"].min_lat,
        bbox_min_lon=geo["bbox"].min_lon,
        bbox_max_lat=geo["bbox"].max_lat,
        bbox_max_lon=geo["bbox"].max_lon,
    )


def _zero_poi_message(n_poi: int, narrativa: str | None) -> str | None:
    """``None`` if there is a POI or if a real narrative already covers the case.

    ``n_poi`` is a count, not a ``list[PoiOut]``: the function serves both the
    synchronous assembly of ``AnalyzeResponse`` (which has already built the
    ``PoiOut``) and phase 2 of ``run_zone_narrative`` in
    :mod:`~crime_risk_analyzer.analyze_narrative` (which has only the raw ``Poi``
    of the cached ``RetrievalContext``) — neither must build a list of the
    other type just for the count.

    In the evaluation arms (``run_analysis``/``run_no_ontology_prompt``) the LLM
    can write prose even on a context without POIs: if it does, that prose is
    already the information for the reader and a ``messaggio`` that hints at
    "nothing to see" next to a non-empty narrative would be contradictory
    (finding of review #260). Same principle in the real two-phase path: phase 1
    (``run_analysis_fast``) does not yet know whether phase 2 will write a real
    narrative, so it is phase 2 (``run_zone_narrative``) that must
    recompute ``messaggio`` from scratch — never retransmit that of phase 1.

    ``narrativa`` is STRIPPED before the truthiness check: a whitespace-only
    string is not real coverage (second finding of review #260), and without the
    strip such a value would have suppressed the explicit message leaving the
    user without any explanation.
    """
    if n_poi or (narrativa or "").strip():
        return None
    return _ZERO_POI_MESSAGE


class AnalyzeResponse(IstatResponseFields):
    """Canonical schema of ``/analyze`` (backend/orchestrator.md).

    ``istat_attivo``/``istat_versione_dati``/``istat_frasi_scartate`` come from
    :class:`~crime_risk_analyzer.istat.response_fields.IstatResponseFields`, the
    base shared with ``ZoneNarrativeResponse``/``PoiNarrativeResponse`` (#345).
    """

    citta: str
    zona_normalizzata: str
    poi: list[PoiOut]
    risk_models: list[RiskModel]
    narrativa: str | None = Field(
        default=None,
        description=(
            "Testo dell'analisi. None se non ancora generato (fase 1 di #259: "
            "in arrivo da POST /analyze/narrativa); stringa vuota in baseline "
            "o quando l'LLM e' caduto (fallback)."
        ),
    )
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
    contesto_hash: str = Field(
        description=(
            "Impronta del contesto di zona (#242): identifica la lista di POI "
            "di questa risposta. Il client la rimanda OPACA in "
            "/analyze/narrativa e /analyze/poi, che rifiutano con 409 se il "
            "contesto che userebbero non e' questo. Digest di identita', non "
            "una misura: nessuno scoring."
        ),
    )
    zona_geo: GeoZone = Field(
        description=(
            "Centro e bbox della zona geocodificata (#260): permette al "
            "frontend di ricentrare la mappa anche quando ``poi`` e' vuoto."
        )
    )
    messaggio: str | None = Field(
        default=None,
        description=(
            "Messaggio esplicito quando ``poi`` e' vuoto E nessuna narrativa "
            "copre gia' il caso (#260): chiarisce che la zona e' stata "
            "geocodificata ma la copertura OSM/TERMINUS non ha trovato punti, "
            "invece di lasciar intendere una zona indicata male. None quando "
            "``poi`` non e' vuoto o quando ``narrativa`` ha gia' del testo."
        ),
    )
    narrativa_grezza: str | None = Field(
        default=None,
        exclude=True,
        description="Testo del modello prima del controllo (#345): solo per l'harness.",
    )
    controllo_istat: CheckOutcome | None = Field(
        default=None,
        exclude=True,
        description="Esito del controllo delle cifre (#345): solo per l'harness.",
    )
    poi_nel_prompt: list[str] | None = Field(
        default=None,
        exclude=True,
        description=(
            "Id dei POI entrati nel prompt (#349): solo per l'harness, che li salva "
            "nel record perche' il confronto fra bracci verifichi la parita'."
        ),
    )


def _build_poi_list(
    retrieval_ctx: RetrievalContext,
    grounded: GroundedContext,
    *,
    istat_context_enabled: bool = False,
) -> list[PoiOut]:
    """Joins coords (from retrieval) and confidence/path (from grounding) per POI.

    The per-POI ``confidence`` is UNIFIED with the per-risk level of the grounding
    (#202/M1): ``None`` if the POI is outside the ontology (no risk to
    qualify), otherwise the same name->verifiability rule of its
    risks (:func:`confidence_from_poi_name`), so the POI badge does not diverge
    from the levels of the risks it carries.

    Invariant: ``grounded["validated_risks"]`` has the same order and length as
    ``retrieval_ctx["pois"]``. ``strict=True`` makes the error explicit if it breaks.

    ``istat_context_enabled`` (#346): the grounding's ``IstatPoi`` is always
    computed (the zone cache carries it), so it is here that the switch, when off,
    keeps it out of the response — off means off in the interface too.
    """
    out: list[PoiOut] = []
    for poi, vr in zip(retrieval_ctx["pois"], grounded["validated_risks"], strict=True):
        # ``strict=True`` verifies the LENGTHS, not the identity alignment: two
        # lists reordered differently would pass, and each POI would receive the
        # confidence and ``sparql_path`` of another point. Now that both carry
        # the id, the misalignment is a hard error instead of a silent
        # misattribution.
        if poi["id"] != vr["poi_id"]:
            raise ValueError(
                "pois e validated_risks disallineati: "
                f"{poi['id']!r} != {vr['poi_id']!r}"
            )
        confidence: Confidence | None = (
            confidence_from_poi_name(poi["name"]) if vr["risks"] else None
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
                # The four axes come from the grounding, which anchored them
                # (#256/#270): here we serialise, nothing is re-derived.
                critical_events=[
                    OntologyItem(name=e["name"], source=e["source"])
                    for e in vr["critical_events"]
                ],
                vulnerabilities=[
                    OntologyItem(name=e["name"], source=e["source"])
                    for e in vr["vulnerabilities"]
                ],
                stakeholders=[
                    OntologyItem(name=e["name"], source=e["source"])
                    for e in vr["stakeholders"]
                ],
                istat=vr.get("istat") if istat_context_enabled else None,
            )
        )
    return out


def _risk_models_from_grounded(grounded: GroundedContext) -> list[RiskModel]:
    """Rebuilds the risk_models from the validated context (fallback without LLM)."""
    models: list[RiskModel] = []
    for vr in grounded["validated_risks"]:
        items = [
            RiskItem(
                hazard=r["hazard"],
                confidence=r["confidence"],
                tag=r["tag"],
                source=r["source"],
            )
            for r in vr["risks"]
        ]
        models.append(RiskModel(poi_id=vr["poi_id"], poi=vr["poi"], risks=items))
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
    contesto_hash: str,
    geo: GeoResult,
    narrativa: str | None = "",
) -> AnalyzeResponse:
    """Assembles the AnalyzeResponse WITHOUT LLM (baseline, fallback, or phase 1 of
    #259).

    ``contesto_hash`` comes from the caller, which has the ``RetrievalContext``: the
    response contract is single, so the fingerprint also accompanies the
    responses without narrative. On phase 1 of ``/analyze`` it is fully
    usable (:func:`~crime_risk_analyzer.analyze_narrative.run_analysis_fast`
    populates the zone cache and the context is that one). On the baseline it is not:
    ``run_baseline`` does not populate ``zone_context_cache`` and ``/analyze/poi``
    does not know ``tipo_poi``, so a FILTERED baseline fingerprint could only
    diverge from the rebuilt context. It is not a path reachable from the UI
    — the per-POI narrative lives only in the full pipeline (backend review M2).
    The LLM fallback of the evaluation paths does not populate the cache either (#292):
    its fingerprint remains a verifiable identity of the returned list, but
    no click will ever send it back.

    ``narrativa``: ``""`` (default) for baseline/fallback — no narrative
    will ever arrive. ``None`` for phase 1 of ``/analyze`` (#259): the narrative is
    on its way from a separate call to ``POST /analyze/narrativa``, it is not a
    fallback.
    """
    return AnalyzeResponse(
        citta=citta,
        zona_normalizzata=zona,
        poi=poi_out,
        risk_models=_risk_models_from_grounded(grounded),
        narrativa=narrativa,
        confidence_summary=ConfidenceSummary.model_validate(
            grounded["confidence_summary"]
        ),
        llm_used="",
        latenza_ms=latenza_ms,
        repro=Repro(temperature=0.0, seed=0, prompt_hash=""),
        cache_hit=False,
        fallback=fallback,
        contesto_hash=contesto_hash,
        zona_geo=_geo_zone(geo),
        messaggio=_zero_poi_message(len(poi_out), narrativa),
    )


def _generated_response(
    citta: str,
    zona: str,
    poi_out: list[PoiOut],
    gen: GenerationResult,
    *,
    latenza_ms: int,
    contesto_hash: str,
    geo: GeoResult,
    measured_token: str,
) -> AnalyzeResponse:
    """Assembles the AnalyzeResponse WITH narrative from the generation layer's output.

    Twin of :func:`_structured_response` for the LLM branch. Extracted when the
    callers became two (#236: the ablation arm without ontological contribution
    uses another generation layer but the SAME response contract): a second
    copied assembly could have diverged exactly on the fields that make the two
    arms comparable.

    ``measured_token`` is the token of the label line of the first block, which
    depends on the prompt that generated the narrative: the ablated arm has
    ``[SINTESI-LLM]`` written (it consulted no ontology and does not claim to),
    so cutting its prose on the label of the other arm would put
    everything in ``overview`` — a second reading of the same text, in disagreement
    with that of the eval.

    MANDATORY and without default: with ``[ONTOLOGIA]`` as default a third
    arm that forgot to declare its own label would not
    err visibly — ``parse_source_prose`` would find nothing,
    the prose would all end up in ``overview`` and that narrative would count as a
    NON-ATTRIBUTION (0.0/1.0) with nobody raising. Making every
    caller declare it moves that error from silence to the type check.
    """
    return AnalyzeResponse(
        citta=citta,
        zona_normalizzata=zona,
        poi=poi_out,
        risk_models=gen.risk_models,
        narrativa=gen.narrativa,
        narrativa_fonti=parse_source_prose(
            gen.narrativa, measured_token=measured_token
        ),
        confidence_summary=gen.confidence_summary,
        llm_used=gen.llm_used,
        latenza_ms=latenza_ms,
        tokens_input=gen.tokens_input,
        tokens_output=gen.tokens_output,
        repro=gen.repro,
        cache_hit=gen.cache_hit,
        fallback=False,
        contesto_hash=contesto_hash,
        zona_geo=_geo_zone(geo),
        messaggio=_zero_poi_message(len(poi_out), gen.narrativa),
        istat_attivo=gen.istat_attivo,
        istat_versione_dati=gen.istat_versione_dati,
        istat_frasi_scartate=gen.istat_frasi_scartate,
        # The no-ontology arm does not set the raw text: it coincides with the text.
        narrativa_grezza=(
            gen.narrativa_grezza if gen.narrativa_grezza is not None else gen.narrativa
        ),
        controllo_istat=gen.controllo_istat,
        poi_nel_prompt=gen.poi_nel_prompt,
    )


class RiskProfiler(Protocol):
    """Minimal surface of the SPARQL executor used by the pipeline (DI)."""

    def profile(self, terminus_class: str) -> PoiRiskProfile: ...


class _LLMClientLike(Protocol):
    """Minimal surface of the LLM client (DI; doubles in the tests)."""

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
    request_token_budget: int = DEFAULT_REQUEST_TOKEN_BUDGET,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    context_format: ContextFormat = DEFAULT_CONTEXT_FORMAT,
    istat_context_enabled: bool = False,
) -> AnalyzeResponse:
    """Runs the full pipeline and assembles the canonical response.

    **No longer wired to ``POST /analyze``** (#292): the route answers in two
    phases (:func:`~crime_risk_analyzer.analyze_narrative.run_analysis_fast` +
    ``POST /analyze/narrativa``). This remains the FULL SYNCHRONOUS path —
    structured data and narrative in the same response — and serves
    :mod:`~crime_risk_analyzer.eval.harness` (``mode="analyze"``): the
    grounding/hallucination metrics compare the prose with the ontological context
    that produced it, so they must arise from the same invocation. It is therefore
    not dead code, and the two phases of the route cannot replace it: the ablation
    arm (:func:`run_no_ontology_prompt`) is comparable only with a full
    iso-input arm like this one.

    ``retrieve`` (async) -> ``ground`` (sync) -> ``generate_analysis`` (async).
    On :class:`LLMError` it returns only the structured data (``fallback=True``) and
    logs a warning with the exception message, so the fallbacks (empty
    narrative) remain diagnosable instead of being silently swallowed (#210).
    ``latenza_ms`` is end-to-end over the whole pipeline.

    ``domanda`` (optional, #119) is the user's free question: it is
    propagated to :func:`generate_analysis` and injected into the ``user_content``
    of the LLM prompt; ``None`` = behaviour unchanged.

    Token budget (#210): ``request_token_budget`` is the TOTAL (estimated) cap
    of the whole LLM request (system prompt + user_content + ``max_tokens``) and
    ``max_tokens`` the tokens reserved for the output; both are propagated to
    :func:`generate_analysis`, which derives from them the allowance for user_content.
    On a dense zone the POIs beyond the allowance do not enter the prompt (map/list
    stay complete) and the whole request does not exceed the provider's TPM.

    ``geo_source`` (optional, #169) is propagated to :func:`retrieve` for the geo
    replay in the eval harness; ``None`` = live geocoding (product unchanged).

    ``istat_context_enabled`` (#345): the harness takes it from
    ``ExperimentConfig.istat``; off by default like the thesis comparison (D6).

    NO side effect on :mod:`~crime_risk_analyzer.zone_context_cache`
    (#292). It used to store the context for ``/analyze/poi`` (#197) when it was the
    route's function; now the cache is warmed by phase 1
    (:func:`~crime_risk_analyzer.analyze_narrative.run_analysis_fast`) and here
    nobody re-reads it, because in the evaluation path there are no clicks on
    a POI. Same choice — and same reason — as
    :func:`run_no_ontology_prompt`: filling it with the context of an offline run
    would be process state nobody asked for, and with a full cache it would evict
    a real user's zone.
    """
    start = time.perf_counter()
    retrieval_ctx = await retrieve(
        citta, zona, executor=executor, poi_source=poi_source, geo_source=geo_source
    )
    grounded = ground(retrieval_ctx)
    # Fingerprint of the POI list of THIS capture (#242): /analyze/poi compares it
    # with that of the context it would use and refuses (409) if they
    # diverge, instead of generating prose on a neighbourhood that is not on screen.
    contesto_hash = fingerprint(
        retrieval_ctx["pois"],
        istat_version=istat_version_for(istat_context_enabled),
        sources_id=active_sources_id(),
    )
    poi_out = _build_poi_list(
        retrieval_ctx, grounded, istat_context_enabled=istat_context_enabled
    )
    try:
        gen = await generate_analysis(
            dict(grounded),
            llm_client,
            domanda=domanda,
            request_token_budget=request_token_budget,
            max_tokens=max_tokens,
            context_format=context_format,
            istat=istat_context_enabled,
        )
    except LLMError as exc:
        logger.warning(
            "LLM generation failed for %s/%s: structured fallback (empty "
            "narrative). Cause: %s",
            citta,
            zona,
            exc,
        )
        return _structured_response(
            citta,
            zona,
            poi_out,
            grounded,
            latenza_ms=_elapsed_ms(start),
            fallback=True,
            contesto_hash=contesto_hash,
            geo=retrieval_ctx["geo"],
        )
    return _generated_response(
        citta,
        zona,
        poi_out,
        gen,
        latenza_ms=_elapsed_ms(start),
        contesto_hash=contesto_hash,
        geo=retrieval_ctx["geo"],
        # The prompt of this arm asks for the ontological label (rule 3):
        # the prose is cut on that. Declared here too, where it would have been
        # the default, because the label is a property of the prompt used.
        measured_token=ONTOLOGY_TOKEN,
    )


async def run_no_ontology_prompt(
    citta: str,
    zona: str,
    *,
    executor: RiskProfiler,
    llm_client: _LLMClientLike,
    poi_source: PoiSource | None = None,
    geo_source: GeoSource | None = None,
    request_token_budget: int = DEFAULT_REQUEST_TOKEN_BUDGET,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    context_format: ContextFormat = DEFAULT_CONTEXT_FORMAT,
    istat_context_enabled: bool = False,
) -> AnalyzeResponse:
    """Pipeline of the ablation arm: same LLM, prompt WITHOUT ontology (#236).

    ``retrieve`` and ``ground`` are unchanged — the structured data of the response
    (``poi[]``, ``risk_models``, ``confidence_summary``, ``sparql_path``) stays
    the ontological one — while the narrative is generated by
    :func:`~crime_risk_analyzer.rag.no_ontology_generation.generate_no_ontology_analysis`,
    which passes the model only the name and class of the points. The only variable
    manipulated with respect to :func:`run_analysis` is therefore the contribution
    of the ontology in the PROMPT, which is what contribution C3 puts to the
    test; the response contract and the legal constraints are the same.

    EVALUATION path, not a product one: it is not exposed by any route
    (the canonical API remains ``/analyze`` and ``/analyze/baseline``) and it does
    not store anything in :mod:`~crime_risk_analyzer.zone_context_cache` — that cache
    serves the user's clicks on ``/analyze/poi``, and filling it with the context of
    an ablation would be process state nobody asked for. Since #292
    it holds for both evaluation arms: :func:`run_analysis` too, having left
    the route, has stopped writing to it.

    On :class:`LLMError` it returns only the structured data (``fallback=True``) with
    the same diagnosable warning as the full arm (#210): a mute arm must
    be seen, because downstream it makes the quality proxies vacuous (#231).

    Same POIs as the full arm (#349): ``request_token_budget``,
    ``max_tokens``, ``context_format`` and ``istat_context_enabled`` are those
    of the :func:`run_analysis` run and serve ONLY to rebuild which points its
    prompt kept after the budget truncation
    (:func:`~crime_risk_analyzer.rag.generation.zone_prompt_pois`). The
    ablated prompt lists the same set of points: before it always sent all the points,
    and the comparison was not at input parity. The order stays that of the retrieval
    and the note on the cut does not state the criterion, because the order by relevance
    (most hazards first) is ontological information. What remains, and must be declared
    in the validity of the comparison, is the CHOICE of which points to keep: it too
    uses the ontology, and set parity cannot be obtained without it. The direction of
    its effect on the comparison is NOT determined, and must be declared: the cut keeps
    the classes with many risks (Police, School, Hospital) and discards those with
    few (pharmacies, banks), whose risks are close to what a model
    without ontology would write anyway. The response stays complete like that
    of the full arm; the ids of the listed points travel in
    ``poi_nel_prompt`` (harness only), which the comparison uses to verify
    parity instead of presuming it.
    """
    start = time.perf_counter()
    retrieval_ctx = await retrieve(
        citta, zona, executor=executor, poi_source=poi_source, geo_source=geo_source
    )
    grounded = ground(retrieval_ctx)
    contesto_hash = fingerprint(
        retrieval_ctx["pois"],
        istat_version=istat_version_for(istat_context_enabled),
        sources_id=active_sources_id(),
    )
    poi_out = _build_poi_list(retrieval_ctx, grounded)
    in_prompt = zone_prompt_pois(
        dict(grounded),
        request_token_budget=request_token_budget,
        max_tokens=max_tokens,
        context_format=context_format,
        istat=istat_context_enabled,
    )
    try:
        gen = await generate_no_ontology_analysis(
            dict(grounded), llm_client, poi_nel_prompt=in_prompt
        )
    except LLMError as exc:
        logger.warning(
            "LLM generation (no-ontology arm) failed for %s/%s: "
            "structured fallback (empty narrative). Cause: %s",
            citta,
            zona,
            exc,
        )
        return _structured_response(
            citta,
            zona,
            poi_out,
            grounded,
            latenza_ms=_elapsed_ms(start),
            fallback=True,
            contesto_hash=contesto_hash,
            geo=retrieval_ctx["geo"],
        )
    return _generated_response(
        citta,
        zona,
        poi_out,
        gen,
        latenza_ms=_elapsed_ms(start),
        contesto_hash=contesto_hash,
        geo=retrieval_ctx["geo"],
        # The narrative of this arm opens the measured block with its own
        # label (#236): the per-source cut must look for that, not
        # the ontological label that the ablated prompt no longer asks for.
        measured_token=LLM_SYNTHESIS_TOKEN,
    )


def _filter_pois(
    ctx: RetrievalContext, keep: Callable[[Poi], bool]
) -> RetrievalContext:
    """Filters ``ctx["pois"]`` by ``keep`` and recomputes classes/profiles/stats (#318).

    Generalisation of the only existing filter (by ``tipo_poi``): both
    filters (type, radius) share the same reconstruction of
    ``profiles``/``stats``, which must stay in lockstep with the surviving
    POI list (same invariant as :func:`_build_poi_list`).
    """
    pois = [poi for poi in ctx["pois"] if keep(poi)]
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


def _filter_pois_by_type(
    ctx: RetrievalContext, terminus_class: str
) -> RetrievalContext:
    """Restricts the ``RetrievalContext`` to POIs of the given TERMINUS class."""
    return _filter_pois(ctx, lambda poi: poi["terminus_class"] == terminus_class)


def _filter_pois_by_radius(
    ctx: RetrievalContext, lat: float, lon: float, radius_m: float
) -> RetrievalContext:
    """Restricts the ``RetrievalContext`` to the POIs within ``radius_m`` of
    ``(lat, lon)`` only (#318).

    Applied AFTER ``retrieve()`` (which has already chosen the ``MAX_POIS`` closest
    to the circumscribed bbox), so it can return fewer POIs than the cap if the pool
    contained corner points outside the true circle but inside the bbox — accepted
    by design (never a POI outside the drawn circle, see design doc §2).
    """
    return _filter_pois(
        ctx, lambda poi: haversine_m(lat, lon, poi["lat"], poi["lon"]) <= radius_m
    )


async def run_baseline(
    citta: str,
    zona: str,
    *,
    executor: RiskProfiler,
    poi_source: PoiSource | None = None,
    geo_source: GeoSource | None = None,
    tipo_poi: str | None = None,
    radius_m: float | None = None,
) -> AnalyzeResponse:
    """Baseline pipeline: retrieve -> ground -> serialise (NO LLM).

    ``radius_m`` (optional, #318) filters the POIs server-side within the radius from
    the geocoded centre (:func:`_filter_pois_by_radius`), applied BEFORE the
    ``tipo_poi`` filter (both, before the grounding). ``None`` = no radius
    filter (behaviour unchanged).

    ``tipo_poi`` (optional, #119) filters the POIs server-side by TERMINUS class
    (:func:`_filter_pois_by_type`), applied before the grounding. ``None`` or
    empty/whitespace string = no filter (behaviour unchanged). The
    comparison is exact: the expected value is already the canonical class name, which
    the route derives from the free input with
    :func:`~crime_risk_analyzer.poi_types.resolve_poi_type` (#143).

    ``geo_source`` (optional, #169) is propagated to :func:`retrieve` for the geo
    replay in the eval harness; ``None`` = live geocoding (product unchanged).
    """
    start = time.perf_counter()
    retrieval_ctx = await retrieve(
        citta, zona, executor=executor, poi_source=poi_source, geo_source=geo_source
    )
    if radius_m is not None:
        lat, lon = retrieval_ctx["geo"]["lat"], retrieval_ctx["geo"]["lon"]
        retrieval_ctx = _filter_pois_by_radius(retrieval_ctx, lat, lon, radius_m)
    type_name = (tipo_poi or "").strip()
    if type_name:
        retrieval_ctx = _filter_pois_by_type(retrieval_ctx, type_name)
    grounded = ground(retrieval_ctx)
    poi_out = _build_poi_list(retrieval_ctx, grounded)
    # Fingerprint computed AFTER any ``tipo_poi`` filter (#119): it must
    # identify the list actually returned, not the pre-filter one.
    # Without ISTAT version (#354): the baseline never feeds /analyze/poi, the
    # frontend only clicks with the contesto_hash of the full analysis.
    return _structured_response(
        citta,
        zona,
        poi_out,
        grounded,
        latenza_ms=_elapsed_ms(start),
        fallback=False,
        contesto_hash=fingerprint(retrieval_ctx["pois"]),
        geo=retrieval_ctx["geo"],
    )
