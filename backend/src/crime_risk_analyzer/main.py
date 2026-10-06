"""Entrypoint dell'applicazione FastAPI.

Espone la factory :func:`create_app` e un'istanza ``app`` pronta per Uvicorn
(``uvicorn crime_risk_analyzer.main:app``). Registra gli endpoint di dominio —
``GET /health``, ``GET /cities``, ``GET /poi-types`` (#143), ``GET /geocode``
(#318), ``POST /analyze`` + ``POST
/analyze/narrativa`` (le due fasi dell'analisi di zona, #259/#292), ``POST
/analyze/baseline`` e ``POST /analyze/poi`` (#197) — e configura il CORS (#106)
e il warm-up delle risorse nel ``lifespan``.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated, cast

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from rdflib import Graph

from crime_risk_analyzer import geocoding
from crime_risk_analyzer.analyze_narrative import (
    ZoneNarrativeRequest,
    ZoneNarrativeResponse,
    run_analysis_fast,
    run_zone_narrative,
)
from crime_risk_analyzer.area_search import resolve_circle, resolve_zone
from crime_risk_analyzer.config import Settings, get_settings
from crime_risk_analyzer.errors import register_exception_handlers
from crime_risk_analyzer.istat.dati import dati_istat
from crime_risk_analyzer.llm.client import LLMClient, get_llm_client
from crime_risk_analyzer.ontology import get_ontology
from crime_risk_analyzer.orchestrator import (
    AnalyzeRequest,
    AnalyzeResponse,
    BaselineRequest,
    Center,
    run_baseline,
)
from crime_risk_analyzer.poi_narrative import (
    PoiNarrativeRequest,
    PoiNarrativeResponse,
    run_poi_narrative,
)
from crime_risk_analyzer.poi_types import PoiType, poi_types, resolve_poi_type
from crime_risk_analyzer.rag.retrieval import GeoSource
from crime_risk_analyzer.sparql_module.query_executor import (
    RiskQueryExecutor,
    get_executor,
)


class HealthResponse(BaseModel):
    """Risposta dell'endpoint di health-check."""

    status: str
    ontology_triples: int


async def _resolve_area(
    request: AnalyzeRequest | BaselineRequest,
) -> tuple[str, str, GeoSource]:
    """Instrada il body sul resolver della modalita' che porta.

    Le due modalita' di ricerca coesistono e il body ne porta esattamente una
    (invariante garantita dal validator di ``_AreaRequest``): qui si sceglie solo
    il resolver. Entrambi ritornano ``(citta, zona, geo_source)``, quindi da qui
    in giu' la pipeline non sa quale modalita' l'utente abbia usato.

    Il ``cast`` regge sull'invariante del validator, non su un controllo locale:
    ``is_circle`` implica ``center``/``radius_m`` valorizzati, ed e' la stessa
    ragione per cui il ramo testuale puo' passare ``citta``/``zona`` senza
    ri-verificarli.
    """
    if request.is_circle:
        center = cast(Center, request.center)
        return await resolve_circle(
            center.lat, center.lon, cast(float, request.radius_m)
        )
    return await resolve_zone(cast(str, request.citta), cast(str, request.zona))


router = APIRouter()


@router.get("/health")
async def health(graph: Annotated[Graph, Depends(get_ontology)]) -> HealthResponse:
    """Health-check: servizio in piedi + numero di triple dell'ontologia caricata.

    Il grafo arriva via ``Depends(get_ontology)`` (caricato una volta nel
    ``lifespan``, niente I/O per richiesta): ``ontology_triples`` segnala che
    l'ontologia e' effettivamente in memoria (vedi backend/orchestrator.md).
    """
    return HealthResponse(status="ok", ontology_triples=len(graph))


@router.get("/cities")
async def cities(settings: Annotated[Settings, Depends(get_settings)]) -> list[str]:
    """Elenca le città suggerite per l'autocomplete del campo città (non un vincolo).

    Roma, Milano e Napoli sono garantite e testate end-to-end; le altre sono
    best-effort (vedi backend/orchestrator.md). La lista vive nella config
    centralizzata ed è iniettata via ``Depends`` (niente stato globale).
    """
    return settings.supported_cities


@router.get("/poi-types")
async def list_poi_types() -> list[PoiType]:
    """Catalogo dei tipi POI accettati da ``tipo_poi`` di ``/analyze/baseline`` (#143).

    Le classi TERMINUS che il mapping OSM puo' produrre, con l'etichetta IT del
    vocabolario controllato, ordinate per etichetta. Dati statici del package,
    calcolati una volta (:func:`poi_types` e' in cache): nessuna rete, nessuna
    dipendenza dall'ontologia caricata.
    """
    return list(poi_types())


@router.get("/geocode")
async def geocode(
    query: Annotated[str, Query(max_length=200)],
) -> dict[str, float]:
    """Forward geocode di un luogo libero (#318): sposta solo la mappa, non fa
    parte dell'analisi.

    Serve la casella "vai a un luogo" del frontend: nessun bbox, nessuna
    zona/citta' — solo un punto per ricentrare la mappa, da cui l'utente
    disegna poi il cerchio che alimenta ``POST /analyze``. ``GeocodingError``
    (servizio non raggiungibile) e' gia' mappato centralmente -> 503 (#21); qui
    si gestisce solo l'esito "nessun risultato", che non e' un errore di
    servizio.
    """
    result = await run_in_threadpool(geocoding.geocode_freeform, query)
    if result is None:
        raise HTTPException(status_code=404, detail="luogo non trovato")
    lat, lon = result
    return {"lat": lat, "lon": lon}


@router.post("/analyze")
async def analyze(
    request: AnalyzeRequest,
    executor: Annotated[RiskQueryExecutor, Depends(get_executor)],
) -> AnalyzeResponse:
    """Fase 1 (#259/#292): area -> OSM -> SPARQL -> grounding -> JSON.

    **Nessuna chiamata LLM qui.** La rotta risponde con i dati strutturati e
    ``narrativa=None`` — non un fallback (``fallback`` resta ``False``), ma
    "testo in arrivo": il client rende subito mappa e lista, poi chiede la prosa a
    ``POST /analyze/narrativa`` rimandando il ``contesto_hash`` di questa
    risposta. Prima la mappa compariva solo dopo la generazione, cioe' dopo tutta
    la latenza del provider.

    Il body porta l'area in UNA delle due modalita' (:func:`_resolve_area`): il
    cerchio disegnato sulla mappa (#318), di cui ``resolve_circle`` deriva una
    label citta'/zona best-effort via reverse geocode (mai bloccante), oppure i
    due campi ``citta``/``zona``, che ``resolve_zone`` geocodifica in un bbox —
    una zona non trovata e' ``ZoneNotFoundError`` -> 422. Nessuna allowlist di
    citta' (#191): ``GET /cities`` suggerisce, non vincola. Gli errori di dominio
    (Overpass giu', ecc.) propagano agli handler centrali (#21).

    La ``domanda`` libera (#119) resta della fase 2, che e' l'unica a costruire
    un prompt. Per la stessa ragione questa rotta non dipende ne' dal client
    LLM ne' dai tetti di token di ``Settings``: sono argomenti della fase 2.
    """
    citta, zona, geo_source = await _resolve_area(request)
    return await run_analysis_fast(
        citta,
        zona,
        executor=executor,
        geo_source=geo_source,
        radius_m=request.radius_m,
    )


@router.post("/analyze/narrativa")
async def analyze_narrativa(
    request: ZoneNarrativeRequest,
    executor: Annotated[RiskQueryExecutor, Depends(get_executor)],
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ZoneNarrativeResponse:
    """Fase 2 (#259/#292): la narrativa di zona, generata a parte.

    Riusa il contesto scaldato dalla fase 1 (cache con TTL); a cache fredda lo
    ricostruisce, al costo di una chiamata Overpass. ``contesto_hash`` (#242) e'
    l'impronta del contesto che il client sta mostrando: se non identifica il
    contesto che l'endpoint userebbe -> ``ContextMismatchError`` -> 409
    (handler centrale in :mod:`errors`, lo stesso registro di ``/analyze/poi``),
    cosi' la prosa non puo' nascere su una lista di POI diversa da quella a
    schermo — e il rifiuto arriva prima di qualunque chiamata LLM, quindi non
    costa token. ``LLMError`` e' gestito in :func:`run_zone_narrative` come
    fallback (200 con narrativa vuota e ``fallback=True``): i dati strutturati
    sono gia' a schermo dalla fase 1.

    ``request.domanda`` (opzionale, #119) e' propagata fino allo ``user_content``
    del prompt. Il tetto totale di token della richiesta e i ``max_tokens`` di
    output (#210) arrivano da ``Settings`` (DI): il generation layer ne ricava
    l'allowance per lo user_content e limita i POI passati all'LLM su zone dense,
    cosi' l'intera richiesta non sfora il TPM del provider. Questa e' ormai
    l'unica chiamata a ``generate_analysis`` del prodotto, quindi e' qui che il
    tetto va rispettato.

    ``citta`` e ``zona`` restano stringhe del client: a cache fredda la
    ricostruzione le passa a ``retrieve`` e la zona finisce nello
    ``user_content``, normalizzata come dato non fidato (``build_context_str``),
    come nel percorso per-POI. L'impronta non ne verifica la PROVENIENZA:
    certifica l'identita' della lista di POI, non che le due stringhe siano
    quelle che la fase 1 ha restituito.
    """
    return await run_zone_narrative(
        request.citta,
        request.zona,
        contesto_hash=request.contesto_hash,
        executor=executor,
        llm_client=llm_client,
        domanda=request.domanda,
        request_token_budget=settings.llm_request_token_budget,
        max_tokens=settings.llm_max_tokens,
        istat_context_enabled=settings.istat_context_enabled,
    )


@router.post("/analyze/baseline")
async def analyze_baseline(
    request: BaselineRequest,
    executor: Annotated[RiskQueryExecutor, Depends(get_executor)],
) -> AnalyzeResponse:
    """Variante senza LLM per l'ablation: solo dati strutturati dal grounding.

    Stesse due modalita' di ``/analyze`` (cerchio oppure citta + zona), via lo
    stesso :func:`_resolve_area`: i due bracci dell'ablation analizzano la stessa
    area scelta nello stesso modo. Nessuna allowlist di citta' (#191).
    ``request.tipo_poi`` (opzionale, #119) filtra i POI server-side per classe
    TERMINUS, applicato dopo il filtro per raggio; ``None``/vuoto = nessun filtro.
    Arriva da un campo di testo libero: :func:`resolve_poi_type` lo normalizza
    alla classe canonica del catalogo ``GET /poi-types`` (maiuscole, spazi ed
    etichetta IT indifferenti, #143) PRIMA di geocoding e Overpass, cosi' un tipo
    sconosciuto e' un 422 (``UnknownPoiTypeError``, handler centrale) che non
    costa chiamate di rete, invece di una lista vuota silenziosa.
    """
    tipo_poi = resolve_poi_type(request.tipo_poi)
    citta, zona, geo_source = await _resolve_area(request)
    return await run_baseline(
        citta,
        zona,
        executor=executor,
        geo_source=geo_source,
        radius_m=request.radius_m,
        tipo_poi=tipo_poi,
    )


@router.post("/analyze/poi")
async def analyze_poi(
    request: PoiNarrativeRequest,
    executor: Annotated[RiskQueryExecutor, Depends(get_executor)],
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PoiNarrativeResponse:
    """Narrativa del singolo POI selezionato (#197).

    Riusa il contesto di zona calcolato da ``/analyze`` (cache con TTL); a cache
    fredda lo ricostruisce, al costo di una chiamata Overpass. ``contesto_hash``
    (#242) e' l'impronta del contesto che il client sta mostrando: se non
    identifica il contesto che l'endpoint userebbe -> ``ContextMismatchError``
    -> 409, cosi' la narrativa non puo' nascere su un vicinato diverso da quello
    a schermo. ``poi_id`` fuori dal contesto -> ``PoiNotFoundError`` -> 404
    (handler centrale). I dati di RISCHIO sono tutti ri-derivati dal server: del
    punto il client fornisce solo l'id e un'impronta opaca. ``citta`` e ``zona``
    restano invece stringhe del client: arrivano al prompt normalizzate come
    dato non fidato (#119), come nel percorso di zona, ma l'impronta non ne
    verifica la provenienza.
    """
    return await run_poi_narrative(
        request.citta,
        request.zona,
        request.poi_id,
        contesto_hash=request.contesto_hash,
        executor=executor,
        llm_client=llm_client,
        istat_context_enabled=settings.istat_context_enabled,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Warm-up all'avvio (fail-fast): ontologia, executor SPARQL e client LLM.

    Pre-costruisce a startup le risorse costose o critiche esposte via
    ``Depends``, così la prima ``POST /analyze`` non paga il costo lazy e un
    misconfig esplode subito all'avvio, non alla prima richiesta:

    * :func:`get_ontology` — carica e valida il grafo ``.ttl`` (fail-fast se
      manca o è invalido);
    * :func:`get_executor` — costruisce l'indice delle restrizioni SPARQL, parte
      costosa e POI-indipendente che appartiene allo startup e non alla prima
      richiesta (vedi docstring di :class:`RiskQueryExecutor`);
    * :func:`get_llm_client` — istanzia il client LLM dal provider configurato
      (fail-fast: ``LLMError`` all'avvio se la chiave del provider manca, invece
      che alla prima ``/analyze``);
    * :func:`dati_istat` — solo con ``istat_context_enabled``: carica e valida i
      dati ISTAT (fail-fast).
    """
    get_ontology()
    get_executor()
    get_llm_client()
    # Dati ISTAT (#345): con l'interruttore acceso, file mancanti o non validi
    # fermano l'avvio invece di produrre narrative senza dati in silenzio.
    if get_settings().istat_context_enabled:
        dati_istat()
    yield


def create_app() -> FastAPI:
    """Costruisce e configura l'istanza FastAPI."""
    settings = get_settings()
    app = FastAPI(title="Crime Risk Analyzer", lifespan=lifespan)
    register_exception_handlers(app)
    # CORS (#106) come DIFESA IN PROFONDITA', per un client su un'origine diversa
    # da quella dell'API. Oggi nessuna chiamata del frontend ne dipende:
    # ApiService usa percorsi relativi e in sviluppo passa dal proxy di
    # ``ng serve`` (``frontend/proxy.config.json`` e' l'unica fonte su cosa e'
    # proxato, #342). Per questo il CORS non puo' coprire una rotta dimenticata
    # nel proxy, e un deploy con l'API su un'altra origine richiederebbe anche
    # un base URL nel frontend. Allowlist ESPLICITA da ``Settings`` (mai
    # wildcard ``*``); API stateless -> nessun cookie
    # (``allow_credentials=False``). Copre tutte le rotte.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router)
    return app


app = create_app()
