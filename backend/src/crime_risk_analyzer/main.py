"""Entrypoint dell'applicazione FastAPI.

Espone la factory :func:`create_app` e un'istanza ``app`` pronta per Uvicorn
(``uvicorn crime_risk_analyzer.main:app``). Per ora solo l'ossatura runnable con
``GET /health``, ``GET /cities`` e ``GET /scenarios``; gli altri endpoint di
dominio (``/analyze``) arrivano in fase P2.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel
from rdflib import Graph

from crime_risk_analyzer.config import Settings, get_settings
from crime_risk_analyzer.errors import register_exception_handlers
from crime_risk_analyzer.ontology import get_ontology
from crime_risk_analyzer.scenarios import ScenarioPreset, get_scenarios


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


@router.get("/scenarios")
async def scenarios(
    presets: Annotated[list[ScenarioPreset], Depends(get_scenarios)],
) -> list[ScenarioPreset]:
    """Elenca i 10 scenari demo precaricati (≥3 città, city-agnostic).

    Fonte unica anche per il frontend (vedi backend/orchestrator.md §``/scenarios``).
    Dati statici e indipendenti dall'ontologia, iniettati via ``Depends``
    (overridabili nei test, niente stato globale).
    """
    return presets


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
