"""Modelli del contratto della fondazione di valutazione (#34)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from crime_risk_analyzer.rag.generation import (
    DEFAULT_CONTEXT_FORMAT,
    ContextFormat,
)

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
    # ``prompt_hash`` copre il SOLO system prompt, mentre #273 cambia lo
    # user_content: senza questo campo due run che differiscono solo per il
    # formato del blocco POI sarebbero indistinguibili nei risultati, e un A/B fra
    # i due prompt non sarebbe leggibile a posteriori. Default = formato storico,
    # cosi' i record scritti prima di #273 restano leggibili ed etichettati per
    # cio' che sono davvero (quelle run erano per-POI).
    context_format: ContextFormat = Field(
        default=DEFAULT_CONTEXT_FORMAT,
        description="Formato del blocco POI dello user_content (#273).",
    )


class Metrics(BaseModel):
    """Le quattro metriche deterministiche."""

    grounding: float = Field(ge=0.0, le=1.0, description="Copertura citazioni [0,1].")
    hallucination: float = Field(
        ge=0.0, le=1.0, description="Tasso allucinazione [0,1]."
    )
    latency_ms: int = Field(ge=0, description="Latenza end-to-end della pipeline.")
    cost_usd: float = Field(ge=0.0, description="Costo stimato in USD.")


class GoldAnnotation(BaseModel):
    """Annotazione gold umana di una run (popolata ESTERNAMENTE, #109).

    Non prodotta dal codice: ``RunRecord.annotazione_manuale`` resta ``None``
    finche' un annotatore umano (il tesista) non valuta la narrativa. Rispecchia
    le metriche proxy (:class:`Metrics`) cosi' che ``eval/gold.py`` possa misurare
    l'accordo proxy-vs-umano. Sono giudizi sulla QUALITA' del citation layer
    (copertura/fabbricazione), non punteggi di pericolosita' (vincolo legale).
    """

    grounding: float = Field(
        ge=0.0, le=1.0, description="Copertura citazioni giudicata dall'umano [0,1]."
    )
    hallucination: float = Field(
        ge=0.0, le=1.0, description="Tasso di fabbricazione giudicato dall'umano [0,1]."
    )
    annotator: str = Field(default="", description="Identificativo dell'annotatore.")
    note: str = Field(default="", description="Note libere dell'annotatore.")


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
    # Terza dimensione dell'esperimento accanto a mode/model (#273), opt-in: un
    # esperimento che non la nomina si comporta esattamente come prima. Le due
    # braccia di un A/B sul prompt vanno lanciate con DUE ``name`` distinti,
    # perche' il formato non entra nel ``run_id`` (cambiarlo rinominerebbe ogni
    # run esistente); ``Provenance.context_format`` rende poi ogni record
    # auto-descrittivo.
    context_format: ContextFormat = Field(
        default=DEFAULT_CONTEXT_FORMAT,
        description="Formato del blocco POI dello user_content (#273).",
    )


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
    annotazione_manuale: GoldAnnotation | None = Field(
        default=None,
        description=(
            "Gold standard umano (popolato ESTERNAMENTE, fuori dalla pipeline): "
            "consumato da eval/gold.py per l'accordo proxy-vs-umano (#109)."
        ),
    )
    provenance: Provenance
