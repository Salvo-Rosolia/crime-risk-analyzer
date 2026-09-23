"""Entrypoint dell'applicazione FastAPI.

Espone la factory :func:`create_app` e un'istanza ``app`` pronta per Uvicorn
(``uvicorn crime_risk_analyzer.main:app``). Registra gli endpoint di dominio —
``GET /health``, ``GET /geocode`` (#318), ``POST /analyze`` + ``POST
/analyze/narrativa`` (le due fasi dell'analisi di zona, #259/#292), ``POST
/analyze/baseline`` e ``POST /analyze/poi`` (#197) — e configura il CORS (#106)
e il warm-up delle risorse nel ``lifespan``.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

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
from crime_risk_analyzer.circle_search import resolve_circle
from crime_risk_analyzer.config import Settings, get_settings
from crime_risk_analyzer.errors import register_exception_handlers
from crime_risk_analyzer.llm.client import LLMClient, get_llm_client
from crime_risk_analyzer.ontology import get_ontology
from crime_risk_analyzer.orchestrator import (
    AnalyzeRequest,
    AnalyzeResponse,
    BaselineRequest,
    run_baseline,
)
from crime_risk_analyzer.poi_narrative import (
    PoiNarrativeRequest,
    PoiNarrativeResponse,
    run_poi_narrative,
)
from crime_risk_analyzer.sparql_module.query_executor import (
    RiskQueryExecutor,
    get_executor,
)


class HealthResponse(BaseModel):
    """Risposta dell'endpoint di health-check."""

    status: str
    ontology_triples: int


router = APIRouter()


@router.get("/health")
async def health(graph: Annotated[Graph, Depends(get_ontology)]) -> HealthResponse:
    """Health-check: servizio in piedi + numero di triple dell'ontologia caricata.

    Il grafo arriva via ``Depends(get_ontology)`` (caricato una volta nel
    ``lifespan``, niente I/O per richiesta): ``ontology_triples`` segnala che
    l'ontologia e' effettivamente in memoria (vedi backend/orchestrator.md).
    """
    return HealthResponse(status="ok", ontology_triples=len(graph))


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
    """Fase 1 (#259/#292): cerchio -> OSM -> SPARQL -> grounding -> JSON.

    **Nessuna chiamata LLM qui.** La rotta risponde con i dati strutturati e
    ``narrativa=None`` — non un fallback (``fallback`` resta ``False``), ma
    "testo in arrivo": il client rende subito mappa e lista, poi chiede la prosa a
    ``POST /analyze/narrativa`` rimandando il ``contesto_hash`` di questa
    risposta. Prima la mappa compariva solo dopo la generazione, cioe' dopo tutta
    la latenza del provider.

    Il body porta centro+raggio del cerchio disegnato sulla mappa (#318), non
    piu' ``citta``/``zona`` testuali: ``resolve_circle`` deriva una label
    citta'/zona best-effort via reverse geocode (mai bloccante, #318) e un
    ``geo_source`` che ignora il geocoding forward — nessuna allowlist di
    citta' (#191) e nessuna zona da risolvere. Gli errori di dominio (Overpass
    giu', ecc.) propagano agli handler centrali (#21).

    La ``domanda`` libera (#119) resta della fase 2, che e' l'unica a costruire
    un prompt. Per la stessa ragione questa rotta non dipende ne' dal client
    LLM ne' dai tetti di token di ``Settings``: sono argomenti della fase 2.
    """
    citta, zona, geo_source = await resolve_circle(
        request.center.lat, request.center.lon, request.radius_m
    )
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

    ``citta`` e ``zona`` restano stringhe del client che raggiungono il prompt
    non sanificate quando la cache e' fredda (la ricostruzione le passa a
    ``retrieve``, e la zona finisce nello ``user_content``), come nel percorso
    per-POI: l'impronta non copre quel vettore — verifica l'identita' della lista
    di POI, non la provenienza delle due stringhe.
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
    )


@router.post("/analyze/baseline")
async def analyze_baseline(
    request: BaselineRequest,
    executor: Annotated[RiskQueryExecutor, Depends(get_executor)],
) -> AnalyzeResponse:
    """Variante senza LLM per l'ablation: solo dati strutturati dal grounding.

    Stesso cerchio centro+raggio di ``/analyze`` (#318), via lo stesso
    ``resolve_circle``: nessuna allowlist di citta' (#191) e nessuna zona
    testuale da risolvere. ``request.tipo_poi`` (opzionale, #119) filtra i POI
    server-side per classe TERMINUS, applicato dopo il filtro per raggio;
    ``None``/vuoto = nessun filtro.
    """
    citta, zona, geo_source = await resolve_circle(
        request.center.lat, request.center.lon, request.radius_m
    )
    return await run_baseline(
        citta,
        zona,
        executor=executor,
        geo_source=geo_source,
        radius_m=request.radius_m,
        tipo_poi=request.tipo_poi,
    )


@router.post("/analyze/poi")
async def analyze_poi(
    request: PoiNarrativeRequest,
    executor: Annotated[RiskQueryExecutor, Depends(get_executor)],
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
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
    restano invece stringhe del client che raggiungono il prompt non sanificate,
    come nel percorso di zona (#119): l'impronta non copre quel vettore.
    """
    return await run_poi_narrative(
        request.citta,
        request.zona,
        request.poi_id,
        contesto_hash=request.contesto_hash,
        executor=executor,
        llm_client=llm_client,
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
      che alla prima ``/analyze``).
    """
    get_ontology()
    get_executor()
    get_llm_client()
    yield


def create_app() -> FastAPI:
    """Costruisce e configura l'istanza FastAPI."""
    settings = get_settings()
    app = FastAPI(title="Crime Risk Analyzer", lifespan=lifespan)
    register_exception_handlers(app)
    # CORS (#106) come DIFESA IN PROFONDITA'. Il deploy canonico e' same-origin
    # (build Angular servita da FastAPI/StaticFiles): li' il CORS non serve. Il
    # middleware abilita comunque un eventuale deploy split-origin e chiude i
    # buchi cross-origin in dev su ``/health``/``/geocode`` (non proxati da
    # ``ng serve``, a differenza di ``/analyze``). Allowlist ESPLICITA da
    # ``Settings`` (mai wildcard ``*``); API stateless -> nessun cookie
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
