"""Modelli del contratto della fondazione di valutazione (#34)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

Mode = Literal["analyze", "baseline"]
ModelChoice = Literal["claude", "groq"]


class RunStatus(StrEnum):
    """Esito di una singola run."""

    OK = "ok"
    FALLBACK = "fallback"
    ERROR = "error"


class Provenance(BaseModel):
    """Provenienza riproducibile di una run."""

    code_commit: str = Field(description="git rev-parse HEAD al momento della run.")
    ontology_hash: str = Field(description="sha256 del file ontologia caricato.")
    snapshot_id: str = Field(description="Id dello snapshot POI usato (replay).")
    model_id: str = Field(description="Model id esatto, o 'baseline'.")
    prompt_hash: str = Field(description="Hash del system prompt (vuoto in baseline).")
    temperature: float = Field(description="Temperature fissata (0 in eval).")
    seed: int = Field(description="Seed loggato.")
    experiment: str = Field(description="Nome dell'esperimento.")


class Metrics(BaseModel):
    """Le quattro metriche deterministiche."""

    grounding: float = Field(ge=0.0, le=1.0, description="Copertura citazioni [0,1].")
    hallucination: float = Field(
        ge=0.0, le=1.0, description="Tasso allucinazione [0,1]."
    )
    latency_ms: int = Field(ge=0, description="Latenza end-to-end della pipeline.")
    cost_usd: float = Field(ge=0.0, description="Costo stimato in USD.")


class RunCase(BaseModel):
    """Un singolo caso (citta, zona)."""

    citta: str
    zona: str


class ExperimentConfig(BaseModel):
    """Configurazione di un esperimento: una macchina, tante run."""

    name: str = Field(description="Nome dell'esperimento (prefisso di run_id e file).")
    mode: Mode = Field(description="analyze (con LLM) o baseline (senza LLM).")
    model: ModelChoice = Field(description="Provider LLM (ignorato se mode=baseline).")
    cases: list[RunCase] = Field(description="Casi da eseguire.")


class RunRecord(BaseModel):
    """Record completo di una run (sorgente di verità, un JSON per run)."""

    run_id: str
    experiment: str
    citta: str
    zona: str
    mode: Mode
    model_id: str
    status: RunStatus
    metrics: Metrics
    narrativa: str = Field(description="Narrativa grezza, per audit.")
    n_poi: int = Field(ge=0)
    annotazione_manuale: dict[str, object] | None = Field(
        default=None, description="Gold standard umano (popolato fuori da #34)."
    )
    provenance: Provenance
