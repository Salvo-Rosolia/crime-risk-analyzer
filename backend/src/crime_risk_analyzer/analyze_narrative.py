"""Fase 1+2 di ``/analyze`` senza bloccare sulla narrativa (#259).

Modulo fratello di :mod:`~crime_risk_analyzer.poi_narrative` (#197): stesso
schema — chiama ``retrieve``/``ground`` direttamente, non tocca il corpo di
``orchestrator.run_analysis`` — applicato al livello di zona invece che al
singolo POI. ``run_analysis_fast`` ha sostituito ``run_analysis`` sulla rotta
``POST /analyze``: stesso retrieve+ground, nessuna chiamata LLM — la risposta ha
``narrativa=None`` (#259 fase 1) — ed e' l'unico punto che scalda
``zone_context_cache`` per i clic successivi. La narrativa arriva con
``run_zone_narrative`` (``POST /analyze/narrativa``), che legge il contesto
(caldo o ricostruito, stesso schema di ``run_poi_narrative``) e genera.
"""

from __future__ import annotations

import logging
import time

from pydantic import BaseModel, Field

from crime_risk_analyzer import zone_context_cache
from crime_risk_analyzer.context_fingerprint import ContestoHash, fingerprint
from crime_risk_analyzer.geocoding import ZoneNotFoundError
from crime_risk_analyzer.llm.client import LLMError
from crime_risk_analyzer.orchestrator import (
    AnalyzeResponse,
    PoiSource,
    RiskProfiler,
    _build_poi_list,  # pyright: ignore[reportPrivateUsage]
    _elapsed_ms,  # pyright: ignore[reportPrivateUsage]
    _filter_pois_by_radius,  # pyright: ignore[reportPrivateUsage]
    _LLMClientLike,  # pyright: ignore[reportPrivateUsage]
    _messaggio_zero_poi,  # pyright: ignore[reportPrivateUsage]
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
    radius_m: float | None = None,
) -> AnalyzeResponse:
    """Fase 1 (#259): dati strutturati subito, ``narrativa=None``.

    ``retrieve`` -> ``ground`` -> warm di ``zone_context_cache``: la narrativa
    vera arriva con :func:`run_zone_narrative`, che rilegge questa stessa cache,
    e cosi' fa ``/analyze/poi`` a ogni clic. Il deposito in cache vive SOLO qui
    (#292): i percorsi di valutazione
    (:func:`~crime_risk_analyzer.orchestrator.run_analysis` e il braccio ablato)
    non ci scrivono, perche' nessuno li' rilegge quel contesto.

    ``radius_m`` (opzionale, #318) filtra i POI server-side entro il raggio dal
    centro geocodificato (``_filter_pois_by_radius``), stesso pattern di
    ``run_baseline``: applicato PRIMA del grounding, cosi' la cache di zona
    scalda col contesto GIA' filtrato. ``None`` = nessun filtro per raggio
    (comportamento invariato).
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
        geo=retrieval_ctx["geo"],
        narrativa=None,
    )


class ZoneNarrativeRequest(BaseModel):
    """Body di ``POST /analyze/narrativa`` (#259).

    Porta ``domanda`` ma non ``tipo_poi``: l'asimmetria con ``BaselineRequest``
    (che porta ``tipo_poi`` ma non ``domanda``) è tracciata da #263, non ancora
    chiusa perché dipende dalla decisione sul contratto di ``tipo_poi`` FE-BE
    (#143). Vedi ``BaselineRequest`` in :mod:`~crime_risk_analyzer.orchestrator`.
    """

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
            "Domanda libera (opzionale) iniettata come input NON fidato (fenced) "
            "nello user_content del prompt LLM (#119); None/vuota = prompt "
            "invariato. Unico posto in cui vive dopo lo split (#292): la fase 1 "
            "non chiama il modello. max_length=500: una domanda in linguaggio "
            "naturale di un operatore ci sta ampiamente, mentre il tetto limita "
            "token/costo/latenza e riduce la superficie di prompt-injection."
        ),
    )
    contesto_hash: ContestoHash


class ZoneNarrativeResponse(BaseModel):
    """Narrativa di zona generata in fase 2 (#259): solo testo + provenienza."""

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

    A cache fredda senza ``geo_source`` (il caso reale della rotta: il client
    rimanda solo ``citta``/``zona``, mai il cerchio originale) la ricostruzione
    passa da un geocode FORWARD (:func:`~crime_risk_analyzer.geocoding.geocode_zone`)
    di un'etichetta che pero' nasce da un reverse geocode del centro del cerchio
    (#318): quasi mai una stringa che Nominatim ritrova cercandola in avanti, e
    sempre impossibile nel caso di fallback (``"area lat,lon"``/``"zona non
    identificata"``, D9 del design doc). La conseguente
    :class:`~crime_risk_analyzer.geocoding.ZoneNotFoundError` diventa qui lo
    stesso :class:`ContextMismatchError` del ramo ``contesto_hash`` -> 409, non
    un 422 "zona non geocodificabile": il contesto non e' scritto male, e'
    semplicemente scaduto/sfrattato, e la via d'uscita e' la stessa, rilanciare
    l'analisi di zona (che ridisegna il cerchio e ripassa da
    ``resolve_circle``). :class:`~crime_risk_analyzer.geocoding.GeocodingError`
    generico (Nominatim irraggiungibile) resta INVECE un 503 non catturato qui:
    e' un guasto di servizio reale, non un'etichetta non ricercabile, e
    rilanciare l'analisi non lo risolverebbe.
    """
    start = time.perf_counter()
    cached = zone_context_cache.get(citta, zona)
    ricostruito = cached is None
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

    if fingerprint(cached["retrieval"]["pois"]) != contesto_hash:
        raise ContextMismatchError(
            f"il contesto di {citta}/{zona} non e' quello dell'analisi che hai "
            "davanti: rilancia l'analisi di zona"
        )
    if ricostruito:
        zone_context_cache.put(citta, zona, cached)

    n_poi = len(cached["retrieval"]["pois"])

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
            # Nessun modello ha scritto nulla: stessa scelta di
            # ``_structured_response`` sul ramo senza LLM, non un id inventato.
            llm_used="",
            tokens_input=0,
            tokens_output=0,
            latenza_ms=_elapsed_ms(start),
            repro=Repro(temperature=0.0, seed=0, prompt_hash=""),
            fallback=True,
            messaggio=_messaggio_zero_poi(n_poi, ""),
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
        messaggio=_messaggio_zero_poi(n_poi, gen.narrativa),
    )
