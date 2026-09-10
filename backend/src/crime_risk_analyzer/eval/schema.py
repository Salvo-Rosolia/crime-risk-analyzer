"""Modelli del contratto della fondazione di valutazione (#34)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from crime_risk_analyzer.rag.generation import (
    DEFAULT_CONTEXT_FORMAT,
    ContextFormat,
    RiskModel,
)

#: Bracci dell'esperimento. ``analyze`` = pipeline completa (LLM + grounding
#: ontologico nel prompt); ``baseline`` = nessun LLM (soli dati strutturati);
#: ``no_ontology_prompt`` = STESSO LLM del braccio completo, sullo STESSO snapshot
#: POI, ma con un prompt che porta solo nome e classe dei punti (#236). Il terzo
#: braccio esiste perche' ``analyze`` vs ``baseline`` isola la presenza dell'LLM,
#: non quella dell'ontologia: uno dei due non produce prosa, quindi i proxy
#: ``grounding``/``hallucination`` non si applicano a entrambi in modo
#: interpretabile. Il nome dice cio' che e' ablato — il PROMPT, non il grounding:
#: ``ground()`` gira comunque e i dati strutturati della response restano
#: ontologici in tutti i bracci.
Mode = Literal["analyze", "baseline", "no_ontology_prompt"]
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
    # #267: ``snapshot_id`` è solo la CHIAVE (citta, zona) dello snapshot, non la
    # sua provenienza — non basta a distinguere due catture della stessa zona con
    # politiche di selezione diverse. Entrambi ``None`` per gli snapshot pre-#241
    # (liste nude, nessuna provenienza da riportare): un default falso sarebbe un
    # dato fabbricato, peggio del silenzio che erano prima.
    snapshot_catturato_il: str | None = Field(
        default=None,
        description="Istante di cattura dello snapshot POI consumato (#267).",
    )
    snapshot_configurazione_canonica: dict[str, object] | None = Field(
        default=None,
        description=(
            "Configurazione canonica dichiarata dallo snapshot POI consumato "
            "(#267): permette di riconoscere a posteriori una run che ha "
            "rigiocato una fixture con una politica di selezione diversa da "
            "quella corrente."
        ),
    )


class Metrics(BaseModel):
    """Le quattro metriche deterministiche."""

    grounding: float = Field(ge=0.0, le=1.0, description="Copertura citazioni [0,1].")
    hallucination: float = Field(
        ge=0.0, le=1.0, description="Tasso allucinazione [0,1]."
    )
    quality_vacuous: bool | None = Field(
        default=None,
        description=(
            "True se grounding/hallucination cadono nel ramo vacuo di "
            "metrics.py::_grade (nessuna narrativa/ancoraggio da giudicare, non "
            "qualita' reale, #240). None sui record pre-#240 (dato non "
            "disponibile): NON equivale a False, che dichiara esplicitamente "
            "che la run era gradabile."
        ),
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
    mode: Mode = Field(
        description=(
            "analyze (con LLM), baseline (senza LLM) o no_ontology_prompt "
            "(con LLM, prompt senza il contributo ontologico)."
        )
    )
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

    @model_validator(mode="after")
    def _reject_grouping_without_ontology(self) -> ExperimentConfig:
        """``per_classe`` non esiste nel braccio ablato (#236).

        Raggruppare per classe TERMINUS serve a non ripetere l'insieme di hazard
        per ogni punto: nel prompt senza ontologia quell'insieme non c'e', quindi
        il formato non avrebbe alcun effetto. Accettarlo in silenzio scriverebbe
        una ``Provenance`` che descrive un prompt mai costruito — l'esatto difetto
        che il campo era stato aggiunto per chiudere.
        """
        if self.mode == "no_ontology_prompt" and self.context_format != "per_poi":
            raise ValueError(
                "mode='no_ontology_prompt' non ammette "
                f"context_format={self.context_format!r}: il prompt ablato non "
                "porta hazard, quindi non c'e' nulla da raggruppare per classe"
            )
        return self


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
    risk_models: list[RiskModel] = Field(
        default_factory=list,
        description=(
            "Set grounded COMPLETO (pre-filtro, costruito PRIMA della "
            "generazione LLM — identico fra analyze/baseline/no_ontology_prompt "
            "per la stessa (citta, zona)). NON e' 'cosa l'LLM ha mantenuto': "
            "quella nozione (#152) si applica a valle, in eval/gold.py, "
            "incrociando questo campo con la narrativa via "
            "metrics.hazards_cited_in. Lista vuota su status != OK."
        ),
    )
    provenance: Provenance
