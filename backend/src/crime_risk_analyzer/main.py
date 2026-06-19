"""Entrypoint dell'applicazione FastAPI.

Espone la factory :func:`create_app` e un'istanza ``app`` pronta per Uvicorn
(``uvicorn crime_risk_analyzer.main:app``). Per ora solo l'ossatura runnable con
``GET /health`` e ``GET /cities``; gli altri endpoint di dominio (``/analyze``,
``/scenarios``) arrivano in fase P2.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel

from crime_risk_analyzer.config import Settings, get_settings
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


@router.get("/cities")
async def cities(settings: Annotated[Settings, Depends(get_settings)]) -> list[str]:
    """Elenca le città supportate.

    Roma, Milano e Napoli sono garantite e testate end-to-end; le altre sono
    best-effort (vedi backend/orchestrator.md). La lista vive nella config
    centralizzata ed è iniettata via ``Depends`` (niente stato globale).
    """
    return settings.supported_cities


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
