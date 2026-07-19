"""Entrypoint dell'applicazione FastAPI.

Espone la factory :func:`create_app` e un'istanza ``app`` pronta per Uvicorn
(``uvicorn crime_risk_analyzer.main:app``). Registra gli endpoint di dominio —
``GET /health``, ``GET /cities``, ``POST /analyze`` e ``POST /analyze/baseline`` —
e configura il CORS (#106) e il warm-up delle risorse nel ``lifespan``.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from rdflib import Graph

from crime_risk_analyzer.config import Settings, get_settings
from crime_risk_analyzer.errors import register_exception_handlers
from crime_risk_analyzer.llm.client import LLMClient, get_llm_client
from crime_risk_analyzer.ontology import get_ontology
from crime_risk_analyzer.orchestrator import (
    AnalyzeRequest,
    AnalyzeResponse,
    BaselineRequest,
    run_analysis,
    run_baseline,
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


@router.get("/cities")
async def cities(settings: Annotated[Settings, Depends(get_settings)]) -> list[str]:
    """Elenca le città supportate.

    Roma, Milano e Napoli sono garantite e testate end-to-end; le altre sono
    best-effort (vedi backend/orchestrator.md). La lista vive nella config
    centralizzata ed è iniettata via ``Depends`` (niente stato globale).
    """
    return settings.supported_cities


@router.post("/analyze")
async def analyze(
    request: AnalyzeRequest,
    executor: Annotated[RiskQueryExecutor, Depends(get_executor)],
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
) -> AnalyzeResponse:
    """Pipeline completa: geocoding -> OSM -> SPARQL -> grounding -> LLM -> JSON.

    Nessuna allowlist di citta' (#191): qualsiasi citta' italiana raggiunge il
    geocoding (ristretto all'Italia via ``GEOCODING_COUNTRY_CODES``). Una citta'/
    zona inesistente fallisce pulita al geocoding con ``ZoneNotFoundError`` -> 422.
    Gli altri errori di dominio propagano agli handler centrali (#21); ``LLMError``
    e' gestito in :func:`run_analysis` come fallback strutturato (200).
    ``request.domanda`` (opzionale, #119) e' propagata fino allo ``user_content``
    del prompt LLM.
    """
    return await run_analysis(
        request.citta,
        request.zona,
        executor=executor,
        llm_client=llm_client,
        domanda=request.domanda,
    )


@router.post("/analyze/baseline")
async def analyze_baseline(
    request: BaselineRequest,
    executor: Annotated[RiskQueryExecutor, Depends(get_executor)],
) -> AnalyzeResponse:
    """Variante senza LLM per l'ablation: solo dati strutturati dal grounding.

    Nessuna allowlist di citta' (#191): come ``/analyze``, qualsiasi citta'
    italiana raggiunge il geocoding. ``request.tipo_poi`` (opzionale, #119) filtra
    i POI server-side per classe TERMINUS; ``None``/vuoto = nessun filtro.
    """
    return await run_baseline(
        request.citta,
        request.zona,
        executor=executor,
        tipo_poi=request.tipo_poi,
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
    # buchi cross-origin in dev su ``/health``/``/cities`` (non proxati da
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
