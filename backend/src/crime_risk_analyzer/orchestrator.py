"""Orchestratore della pipeline di ``/analyze`` (#18).

Cabla i tre layer RAG gia' pronti (retrieval #22 -> grounding #24 ->
generation #23) e serializza lo schema canonico di ``/analyze``
(backend/orchestrator.md). Contiene i modelli del contratto e le funzioni pure
(testabili senza HTTP) dei percorsi che restituiscono la response canonica:
:func:`run_baseline` (rotta ``POST /analyze/baseline``), :func:`run_analysis`
(percorso sincrono completo, ormai solo per la valutazione) e
:func:`run_no_ontology_prompt` (braccio di ablazione, solo valutazione).

Le due fasi della rotta ``POST /analyze`` + ``POST /analyze/narrativa`` (#292)
vivono in :mod:`~crime_risk_analyzer.analyze_narrative` e riusano da qui
contratto e assemblaggio; le rotte FastAPI vivono in ``main.py``.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

from pydantic import BaseModel, Field, model_validator

from crime_risk_analyzer.context_fingerprint import fingerprint
from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.i18n.terminus_labels import label_en, label_it
from crime_risk_analyzer.llm.client import LLMError, LLMResponse
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.models.vocab import Confidence, ConfidenceSummary
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


class AnalyzeRequest(BaseModel):
    """Body della fase 1 di ``POST /analyze`` (naming ASCII).

    Solo ``citta``/``zona``: la rotta non chiama il modello (#292), quindi non ha
    un prompt in cui iniettare una ``domanda``. Quel campo vive in
    ``ZoneNarrativeRequest`` (:mod:`~crime_risk_analyzer.analyze_narrative`), la
    richiesta della fase 2 che porta davvero il testo dell'operatore al modello.
    """

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


class OntologyItem(BaseModel):
    """Entita' ontologica di un asse non-hazard, con citazione ed etichette (#256).

    Nessuna ``confidence`` e nessun ``tag``: la forza probatoria e' un bit derivato
    dal nome del POI, quindi identica per ogni asserzione ontologica su quel punto —
    il badge del POI le qualifica tutte insieme — e la fonte e' l'ontologia per
    costruzione. Nessun campo numerico: sono elenchi qualitativi, come gli hazard
    (vincolo legale anti-scoring, _project.md §Vincoli).
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
    """POI nello schema canonico ``/analyze`` (coords + confidence + path)."""

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
    # NB: l'asse ``stakeholders`` (havingPerformer) NON e' esposto, di proposito: il
    # vocabolario controllato non ha la categoria e 72 dei suoi filler non hanno
    # etichetta italiana, quindi la sezione uscirebbe in inglese in una UI italiana.
    # Vedi il commento in ``rag/grounding.py``.

    @model_validator(mode="after")
    def _fill_labels(self) -> PoiOut:
        if not self.terminus_label_it:
            self.terminus_label_it = label_it(self.terminus_class)
        if not self.terminus_label_en:
            self.terminus_label_en = label_en(self.terminus_class)
        return self


class ZonaGeo(BaseModel):
    """Centro e bbox della zona geocodificata (#260).

    Prima non usciva dall'orchestrator: la mappa frontend poteva centrarsi solo
    sui POI, quindi una zona con 0 risultati e una zona non trovata erano
    indistinguibili a schermo (in entrambi i casi la mappa restava ferma).
    """

    lat: float
    lon: float
    bbox_min_lat: float
    bbox_min_lon: float
    bbox_max_lat: float
    bbox_max_lon: float


_MESSAGGIO_ZERO_POI = (
    "La zona e' stata geocodificata correttamente, ma non e' stato trovato "
    "nessun punto in questa copertura OSM/TERMINUS."
)


def _zona_geo(geo: GeoResult) -> ZonaGeo:
    return ZonaGeo(
        lat=geo["lat"],
        lon=geo["lon"],
        bbox_min_lat=geo["bbox"].min_lat,
        bbox_min_lon=geo["bbox"].min_lon,
        bbox_max_lat=geo["bbox"].max_lat,
        bbox_max_lon=geo["bbox"].max_lon,
    )


def _messaggio_zero_poi(poi_out: list[PoiOut], narrativa: str | None) -> str | None:
    """``None`` se c'e' un POI o se una narrativa reale copre gia' il caso.

    Nei bracci di valutazione (``run_analysis``/``run_no_ontology_prompt``) l'LLM
    puo' scrivere prosa anche su un contesto senza POI: se lo fa, quella prosa e'
    gia' l'informazione per chi legge e un ``messaggio`` che lascia intendere
    "nulla da vedere" affiancato a una narrativa non vuota sarebbe contraddittorio
    (reperto review #260). ``narrativa`` falsy (``None``/``""``: fase 1 pendente,
    baseline, o fallback LLM) non conta come copertura.
    """
    if poi_out or narrativa:
        return None
    return _MESSAGGIO_ZERO_POI


class AnalyzeResponse(BaseModel):
    """Schema canonico di ``/analyze`` (backend/orchestrator.md)."""

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
    zona_geo: ZonaGeo = Field(
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


def _build_poi_list(
    retrieval_ctx: RetrievalContext, grounded: GroundedContext
) -> list[PoiOut]:
    """Unisce coords (da retrieval) e confidence/path (da grounding) per POI.

    La ``confidence`` per-POI e' UNIFICATA col livello per-rischio del grounding
    (#202/M1): ``None`` se il POI e' fuori ontologia (nessun rischio da
    qualificare), altrimenti la stessa regola nome->verificabilita' dei suoi
    rischi (:func:`confidence_from_poi_name`), cosi' il badge del POI non diverge
    dai livelli dei rischi che porta.

    Invariante: ``grounded["validated_risks"]`` ha stesso ordine e lunghezza di
    ``retrieval_ctx["pois"]``. ``strict=True`` esplicita l'errore se si rompe.
    """
    out: list[PoiOut] = []
    for poi, vr in zip(retrieval_ctx["pois"], grounded["validated_risks"], strict=True):
        # ``strict=True`` verifica le LUNGHEZZE, non l'allineamento di identita': due
        # liste riordinate in modo diverso passerebbero, e ogni POI riceverebbe
        # confidence e ``sparql_path`` di un altro punto. Ora che entrambe portano
        # l'id, il disallineamento e' un errore forte invece di una misattribuzione
        # silenziosa.
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
                # I tre assi arrivano dal grounding, che li ha ancorati (#256): qui
                # si serializza, non si ri-deriva nulla.
                critical_events=[
                    OntologyItem(name=e["name"], source=e["source"])
                    for e in vr["critical_events"]
                ],
                vulnerabilities=[
                    OntologyItem(name=e["name"], source=e["source"])
                    for e in vr["vulnerabilities"]
                ],
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
    """Assembla la AnalyzeResponse SENZA LLM (baseline, fallback, o fase 1 di #259).

    ``contesto_hash`` arriva dal chiamante, che ha il ``RetrievalContext``: il
    contratto della response e' unico, quindi l'impronta accompagna anche le
    response senza narrativa. Sulla fase 1 di ``/analyze`` e' pienamente
    utilizzabile (:func:`~crime_risk_analyzer.analyze_narrative.run_analysis_fast`
    popola la cache di zona e il contesto e' quello). Sulla baseline no:
    ``run_baseline`` non popola ``zone_context_cache`` e ``/analyze/poi`` non
    conosce ``tipo_poi``, quindi un'impronta di baseline FILTRATA non potrebbe che
    divergere dal contesto ricostruito. Non e' un percorso raggiungibile dalla UI
    — la narrativa per-POI vive solo nella pipeline completa (review backend M2).
    Nemmeno il fallback LLM dei percorsi di valutazione popola la cache (#292):
    la sua impronta resta un'identita' verificabile della lista restituita, ma
    nessun clic la rimandera' mai.

    ``narrativa``: ``""`` (default) per baseline/fallback — nessuna narrativa
    arrivera' mai. ``None`` per la fase 1 di ``/analyze`` (#259): la narrativa e'
    in arrivo da una chiamata separata a ``POST /analyze/narrativa``, non e' un
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
        zona_geo=_zona_geo(geo),
        messaggio=_messaggio_zero_poi(poi_out, narrativa),
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
    """Assembla la AnalyzeResponse CON narrativa dal contributo del generation layer.

    Gemello di :func:`_structured_response` per il ramo con LLM. Estratto quando i
    chiamanti sono diventati due (#236: il braccio di ablazione senza contributo
    ontologico usa un altro generation layer ma lo STESSO contratto di risposta):
    un secondo assemblaggio copiato avrebbe potuto divergere proprio sui campi che
    rendono confrontabili i due bracci.

    ``measured_token`` e' il token della riga-etichetta del primo blocco, che
    dipende dal prompt che ha generato la narrativa: il braccio ablato fa scrivere
    ``[SINTESI-LLM]`` (non ha consultato alcuna ontologia e non lo dichiara),
    quindi tagliare la sua prosa sull'etichetta dell'altro braccio metterebbe
    tutto in ``overview`` — una seconda lettura dello stesso testo, in disaccordo
    con quella dell'eval.

    OBBLIGATORIO e senza default: con ``[ONTOLOGIA]`` come default un terzo
    braccio che dimenticasse di dichiarare la propria etichetta non
    sbaglierebbe in modo visibile — ``parse_source_prose`` non troverebbe nulla,
    la prosa finirebbe tutta in ``overview`` e quella narrativa risulterebbe una
    NON-ATTRIBUZIONE (0.0/1.0) senza che nessuno solleva. Farlo dichiarare a ogni
    chiamante sposta quell'errore dal silenzio al type check.
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
        zona_geo=_zona_geo(geo),
        messaggio=_messaggio_zero_poi(poi_out, gen.narrativa),
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
    request_token_budget: int = DEFAULT_REQUEST_TOKEN_BUDGET,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    context_format: ContextFormat = DEFAULT_CONTEXT_FORMAT,
) -> AnalyzeResponse:
    """Esegue la pipeline completa e assembla la response canonica.

    **Non e' piu' cablata a ``POST /analyze``** (#292): la rotta risponde in due
    fasi (:func:`~crime_risk_analyzer.analyze_narrative.run_analysis_fast` +
    ``POST /analyze/narrativa``). Questa resta il percorso SINCRONO COMPLETO —
    dati strutturati e narrativa nella stessa response — e serve
    :mod:`~crime_risk_analyzer.eval.harness` (``mode="analyze"``): le metriche di
    grounding/allucinazione confrontano la prosa con il contesto ontologico che
    l'ha prodotta, quindi devono nascere dalla stessa invocazione. Non e' quindi
    dead code, e le due fasi della rotta non possono sostituirla: il braccio di
    ablazione (:func:`run_no_ontology_prompt`) e' confrontabile solo con un
    braccio completo iso-input come questo.

    ``retrieve`` (async) -> ``ground`` (sync) -> ``generate_analysis`` (async).
    Su :class:`LLMError` ritorna i soli dati strutturati (``fallback=True``) e
    logga un warning col messaggio dell'eccezione, cosi' i fallback (narrativa
    vuota) restano diagnosticabili invece di essere inghiottiti in silenzio (#210).
    ``latenza_ms`` e' end-to-end sull'intera pipeline.

    ``domanda`` (opzionale, #119) e' la domanda libera dell'utente: viene
    propagata a :func:`generate_analysis` e iniettata nello ``user_content`` del
    prompt LLM; ``None`` = comportamento invariato.

    Budget di token (#210): ``request_token_budget`` e' il tetto TOTALE (stima)
    dell'intera richiesta LLM (system prompt + user_content + ``max_tokens``) e
    ``max_tokens`` i token riservati all'output; entrambi sono propagati a
    :func:`generate_analysis`, che ne ricava l'allowance per lo user_content. Su
    una zona densa i POI oltre allowance non entrano nel prompt (mappa/lista
    restano complete) e l'intera richiesta non sfora il TPM del provider.

    ``geo_source`` (opzionale, #169) e' propagato a :func:`retrieve` per il replay
    del geo nell'harness di eval; ``None`` = geocoding live (prodotto invariato).

    NESSUN effetto collaterale su :mod:`~crime_risk_analyzer.zone_context_cache`
    (#292). Depositava il contesto per ``/analyze/poi`` (#197) quando era la
    funzione della rotta; ora la cache la scalda la fase 1
    (:func:`~crime_risk_analyzer.analyze_narrative.run_analysis_fast`) e qui
    nessuno la rilegge, perche' nel percorso di valutazione non ci sono clic su
    un POI. Stessa scelta — e stessa ragione — di
    :func:`run_no_ontology_prompt`: riempirla col contesto di una run offline
    sarebbe stato di processo che nessuno ha chiesto, e a cache piena sfratterebbe
    la zona di un utente vero.
    """
    start = time.perf_counter()
    retrieval_ctx = await retrieve(
        citta, zona, executor=executor, poi_source=poi_source, geo_source=geo_source
    )
    grounded = ground(retrieval_ctx)
    # Impronta della lista POI di QUESTA cattura (#242): /analyze/poi la
    # confronta con quella del contesto che userebbe e rifiuta (409) se
    # divergono, invece di generare prosa su un intorno che a schermo non c'e'.
    contesto_hash = fingerprint(retrieval_ctx["pois"])
    poi_out = _build_poi_list(retrieval_ctx, grounded)
    try:
        gen = await generate_analysis(
            dict(grounded),
            llm_client,
            domanda=domanda,
            request_token_budget=request_token_budget,
            max_tokens=max_tokens,
            context_format=context_format,
        )
    except LLMError as exc:
        logger.warning(
            "Generazione LLM fallita per %s/%s: fallback strutturato (narrativa "
            "vuota). Causa: %s",
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
        # Il prompt di questo braccio chiede l'etichetta ontologica (regola 3):
        # la prosa si taglia su quella. Dichiarato anche qui, dove sarebbe stato
        # il default, perche' l'etichetta e' una proprieta' del prompt usato.
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
) -> AnalyzeResponse:
    """Pipeline del braccio di ablazione: stesso LLM, prompt SENZA ontologia (#236).

    ``retrieve`` e ``ground`` sono invariati — i dati strutturati della response
    (``poi[]``, ``risk_models``, ``confidence_summary``, ``sparql_path``) restano
    quelli ontologici — mentre la narrativa e' generata da
    :func:`~crime_risk_analyzer.rag.no_ontology_generation.generate_no_ontology_analysis`,
    che passa al modello i soli nome e classe dei punti. L'unica variabile
    manipolata rispetto a :func:`run_analysis` e' quindi il contributo
    dell'ontologia nel PROMPT, che e' cio' che la contribuzione C3 mette alla
    prova; il contratto di risposta e i vincoli legali sono gli stessi.

    Percorso di VALUTAZIONE, non di prodotto: non e' esposto da alcuna rotta
    (l'API canonica resta ``/analyze`` e ``/analyze/baseline``) e non deposita
    nulla in :mod:`~crime_risk_analyzer.zone_context_cache` — quella cache serve i
    clic dell'utente su ``/analyze/poi``, e riempirla con il contesto di
    un'ablazione sarebbe uno stato di processo che nessuno ha chiesto. Dal #292
    vale per entrambi i bracci di valutazione: anche :func:`run_analysis`, uscita
    dalla rotta, ha smesso di scriverci.

    Su :class:`LLMError` ritorna i soli dati strutturati (``fallback=True``) con
    lo stesso warning diagnosticabile del braccio completo (#210): un braccio muto
    va visto, perche' a valle rende vacui i proxy di qualita' (#231).
    """
    start = time.perf_counter()
    retrieval_ctx = await retrieve(
        citta, zona, executor=executor, poi_source=poi_source, geo_source=geo_source
    )
    grounded = ground(retrieval_ctx)
    contesto_hash = fingerprint(retrieval_ctx["pois"])
    poi_out = _build_poi_list(retrieval_ctx, grounded)
    try:
        gen = await generate_no_ontology_analysis(dict(grounded), llm_client)
    except LLMError as exc:
        logger.warning(
            "Generazione LLM (braccio senza ontologia) fallita per %s/%s: "
            "fallback strutturato (narrativa vuota). Causa: %s",
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
        # La narrativa di questo braccio apre il blocco misurato con la propria
        # etichetta (#236): il taglio per fonte deve cercare quella, non
        # l'etichetta ontologica che il prompt ablato non chiede piu'.
        measured_token=LLM_SYNTHESIS_TOKEN,
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
    # Impronta calcolata DOPO l'eventuale filtro per ``tipo_poi`` (#119): deve
    # identificare la lista effettivamente restituita, non quella pre-filtro.
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
