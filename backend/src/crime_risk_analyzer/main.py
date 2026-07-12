"""Entrypoint dell'applicazione FastAPI.

Espone la factory :func:`create_app` e un'istanza ``app`` pronta per Uvicorn
(``uvicorn crime_risk_analyzer.main:app``). Per ora solo l'ossatura runnable con
``GET /health`` e ``GET /cities``; gli altri endpoint di dominio (``/analyze``)
arrivano in fase P2.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel
from rdflib import Graph

from crime_risk_analyzer.config import Settings, get_settings
from crime_risk_analyzer.errors import CityNotFoundError, register_exception_handlers
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
    settings: Annotated[Settings, Depends(get_settings)],
    executor: Annotated[RiskQueryExecutor, Depends(get_executor)],
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
) -> AnalyzeResponse:
    """Pipeline completa: geocoding -> OSM -> SPARQL -> grounding -> LLM -> JSON.

    Valida la citta' (``CityNotFoundError`` -> 400). Gli altri errori di dominio
    propagano agli handler centrali (#21); ``LLMError`` e' gestito in
    :func:`run_analysis` come fallback strutturato (200). ``request.domanda``
    (opzionale, #119) e' propagata fino allo ``user_content`` del prompt LLM.
    """
    if request.citta not in settings.supported_cities:
        raise CityNotFoundError(request.citta, supported=settings.supported_cities)
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
    settings: Annotated[Settings, Depends(get_settings)],
    executor: Annotated[RiskQueryExecutor, Depends(get_executor)],
) -> AnalyzeResponse:
    """Variante senza LLM per l'ablation: solo dati strutturati dal grounding.

    ``request.tipo_poi`` (opzionale, #119) filtra i POI server-side per classe
    TERMINUS; ``None``/vuoto = nessun filtro (comportamento invariato).
    """
    if request.citta not in settings.supported_cities:
        raise CityNotFoundError(request.citta, supported=settings.supported_cities)
    return await run_baseline(
        request.citta,
        request.zona,
        executor=executor,
        tipo_poi=request.tipo_poi,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Warm-up all'avvio: carica l'ontologia (fail-fast se manca o è invalida)."""
    get_ontology()
    yield


def create_app() -> FastAPI:
    """Costruisce e configura l'istanza FastAPI."""
    app = FastAPI(title="Crime Risk Analyzer", lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(router)
    return app


app = create_app()
