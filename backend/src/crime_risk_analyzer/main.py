"""Entrypoint dell'applicazione FastAPI.

Espone la factory :func:`create_app` e un'istanza ``app`` pronta per Uvicorn
(``uvicorn crime_risk_analyzer.main:app``). Per ora solo l'ossatura runnable con
``GET /health``; gli endpoint di dominio (``/analyze``, ``/cities``,
``/scenarios``) arrivano in fase P2.
"""

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel


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


def create_app() -> FastAPI:
    """Costruisce e configura l'istanza FastAPI."""
    app = FastAPI(title="Crime Risk Analyzer")
    app.include_router(router)
    return app


app = create_app()
