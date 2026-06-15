"""Entrypoint dell'applicazione FastAPI.

Espone la factory :func:`create_app` e un'istanza ``app`` pronta per Uvicorn
(``uvicorn crime_risk_analyzer.main:app``). Per ora solo l'ossatura runnable con
``GET /health``; gli endpoint di dominio (``/analyze``, ``/cities``,
``/scenarios``) arrivano in fase P2.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from crime_risk_analyzer.ontology import get_ontology


class HealthResponse(BaseModel):
    """Risposta dell'endpoint di health-check."""

    status: str
    # TODO(#ontologia): aggiungere `ontology_triples: int` quando il loader
    # del grafo .ttl esiste (vedi backend/orchestrator.md §Response /health).


router = APIRouter()


@router.get("/health")
async def health() -> HealthResponse:
    """Health-check: segnala che il servizio è in piedi."""
    return HealthResponse(status="ok")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Warm-up all'avvio: carica l'ontologia (fail-fast se manca o è invalida)."""
    get_ontology()
    yield


def create_app() -> FastAPI:
    """Costruisce e configura l'istanza FastAPI."""
    app = FastAPI(title="Crime Risk Analyzer", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
