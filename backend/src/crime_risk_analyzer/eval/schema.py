"""Contract models of the evaluation foundation (#34)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from crime_risk_analyzer.rag.generation import (
    DEFAULT_CONTEXT_FORMAT,
    ContextFormat,
    RiskModel,
)

#: Experiment arms. ``analyze`` = full pipeline (LLM + ontological grounding
#: in the prompt); ``baseline`` = no LLM (structured data only);
#: ``no_ontology_prompt`` = SAME LLM as the full arm, on the SAME POI
#: snapshot, but with a prompt that carries only name and class of the points (#236).
#: The third arm exists because ``analyze`` vs ``baseline`` isolates the presence
#: of the LLM, not that of the ontology: one of the two produces no prose, so the
#: ``grounding``/``hallucination`` proxies do not apply to both in an
#: interpretable way. The name says what is ablated -- the PROMPT, not the grounding:
#: ``ground()`` runs anyway and the structured data of the response stay
#: ontological in all arms.
Mode = Literal["analyze", "baseline", "no_ontology_prompt"]
ModelChoice = Literal["claude", "groq"]


class RunStatus(StrEnum):
    """Outcome of a single run.

    ``ERROR`` and ``HARNESS_ERROR`` are both failures, but they do not say the
    same thing and are not diagnosed the same way:

    - ``ERROR`` = the case's PIPELINE failed (missing snapshot, provider
      down, geocoding, SPARQL...): the error lies inside what the experiment
      measures, and the case simply produced no answer;
    - ``HARNESS_ERROR`` = the pipeline may well have succeeded and
      the INSTRUMENTATION broke downstream (typically the computation of the
      metrics: a ``model_id`` not in the price list -> ``KeyError`` from
      ``pricing.cost_usd``). It is a code or configuration bug, not a
      model failure.

    Keeping them distinct is the point: a live run that comes back with 100% ERROR
    reads as "the provider was down/the snapshots were missing" and is redone
    tomorrow; the same run with 100% HARNESS_ERROR instead says that the quota HAS
    BEEN SPENT and that it was our code that broke after the call. With a
    single label the two diagnoses are indistinguishable in the results -- i.e.
    exactly the misattribution that the ``run_case`` fix had closed.

    Neither enters the means: see ``compare.py``/``repeat.py``.
    """

    OK = "ok"
    FALLBACK = "fallback"
    ERROR = "error"
    HARNESS_ERROR = "harness_error"


class Provenance(BaseModel):
    """Reproducible provenance of a run."""

    code_commit: str = Field(description="git rev-parse HEAD al momento della run.")
    ontology_hash: str = Field(description="sha256 del file ontologia caricato.")
    snapshot_id: str = Field(description="Id dello snapshot POI usato (replay).")
    model_id: str = Field(description="Model id esatto, o 'baseline'.")
    prompt_hash: str = Field(description="Hash del system prompt (vuoto in baseline).")
    temperature: float = Field(description="Temperature fissata (0 in eval).")
    seed: int = Field(description="Seed loggato.")
    experiment: str = Field(description="Nome dell'esperimento.")
    # ``prompt_hash`` covers ONLY the system prompt, while #273 changes the
    # user_content: without this field two runs that differ only by the
    # format of the POI block would be indistinguishable in the results, and an
    # A/B between the two prompts would not be readable afterwards. Default =
    # historical format, so records written before #273 stay readable and
    # labelled for what they really are (those runs were per-POI).
    context_format: ContextFormat = Field(
        default=DEFAULT_CONTEXT_FORMAT,
        description="Formato del blocco POI dello user_content (#273).",
    )
    # #267: ``snapshot_id`` is only the KEY (citta, zona) of the snapshot, not
    # its provenance -- it is not enough to tell apart two captures of the same
    # zone with different selection policies. Both ``None`` for pre-#241 snapshots
    # (bare lists, no provenance to report): a false default would be
    # fabricated data, worse than the silence they were before.
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
    # #345: with or without ISTAT data requested. Default False: records written
    # before stay valid and tell the truth (ISTAT did not exist then).
    istat: bool = Field(
        default=False,
        description=(
            "ISTAT richiesto dalla configurazione (#345). Se i dati sono "
            "arrivati davvero nel prompt lo dice istat_versione_dati (None = "
            "nessuna riga ISTAT nel prompt)."
        ),
    )
    istat_versione_dati: str | None = Field(
        default=None,
        description=(
            "Data di estrazione dei dati ISTAT finiti nel prompt (#345); None se "
            "il prompt non li portava."
        ),
    )
    # #345 (F8 of the final review): the budget decides how many POIs go into the
    # prompt, so two arms with different budgets isolate no
    # variable. ``None`` on old records (value not recorded): it is not equivalent
    # to any value, and the comparison treats it as different from every budget.
    request_token_budget: int | None = Field(
        default=None,
        description=(
            "Budget di token dell'intera richiesta LLM usato dalla run (#345); "
            "None sui record vecchi e nel braccio baseline (nessuna chiamata LLM)."
        ),
    )
    llm_max_tokens: int | None = Field(
        default=None,
        description=(
            "Token riservati all'output nel budget della richiesta (#345); None "
            "sui record vecchi e nel braccio baseline."
        ),
    )


class Metrics(BaseModel):
    """The four deterministic metrics."""

    grounding: float = Field(ge=0.0, le=1.0, description="Copertura citazioni [0,1].")
    hallucination: float = Field(
        ge=0.0, le=1.0, description="Tasso allucinazione [0,1]."
    )
    quality_vacuous: bool | None = Field(
        default=None,
        description=(
            "True se grounding/hallucination cadono nel ramo vacuo di "
            "metrics.py::_grade (nessuna narrativa/POI da giudicare, non "
            "qualita' reale, #240). None sui record pre-#240 (dato non "
            "disponibile): NON equivale a False, che dichiara esplicitamente "
            "che la run era gradabile."
        ),
    )
    # #408: version of the M1 semantics (``metrics.METRICS_VERSION``) with which
    # grounding/hallucination were graded. Records written before do not
    # carry it and it cannot be derived: it was 1, 2 or 3 depending on that day's
    # code. A numeric default would assert something false, hence ``None``; the
    # comparison shows it as ``n/d`` and warns if it differs from the other arm.
    versione: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Versione della semantica M1 di grounding/hallucination (#408); None "
            "sui record precedenti, dove non e' nota."
        ),
    )
    latency_ms: int = Field(ge=0, description="Latenza end-to-end della pipeline.")
    cost_usd: float = Field(ge=0.0, description="Costo stimato in USD.")


class IstatMetrics(BaseModel):
    """Metrics of the ISTAT data in the narrative (#345, spec 4.9; version 2 from #365).

    SEPARATE object from :class:`Metrics`: aggregate and verdict do not see them, and
    on the ontology vs ontology + ISTAT pair there is no winner (D12). Computed
    on the RAW text of the model, before the filter. Counts only, so that
    summing them across repetitions stays correct.

    Version 2 (#365): the model uses the ISTAT data in words in the
    [ONTOLOGIA] block, without figures. ``frasi_istat`` (sentences of
    ANY block that speak of the datum, no longer the [ISTAT] sentences with figures)
    changes meaning, as do ``frasi_istat_con_luogo``, ``voci_citate`` and
    ``corrispondenze_non_dichiarate``;
    ``cifre_istat_corrette`` and ``precisione_cifre`` disappear (every ISTAT figure
    is removed: ``cifre_istat`` counts them, expected 0); the comparisons with the
    Italian datum arrive. Records written before have no ``versione`` and count as
    1: their new fields stay at 0 and are not to be read.

    Version 3 (#368): the counts are the same, but M1 of the records with ISTAT
    grades the text without all the sentences that speak of the datum (split as
    the filter splits them). Grounding and hallucination of version 2 records are
    graded on the text with those sentences in and are not compared with these.

    Version 4 (#369): M1 excludes only the sentences that speak of the datum without
    naming a POI or a risk, split as M1 splits them and with the place
    inherited also from the sentences removed by the filter; ``frasi_escluse_m1``
    counts them (0 and not to be read in earlier versions). The graded
    text changes again: version 3 records are not compared with
    these, and the comparisons reject an arm that mixes versions.
    """

    versione: int = Field(
        default=1,
        ge=1,
        description=(
            "Versione delle metriche ISTAT (1 = #345, 2 = #365, 3 = #368, 4 = #369)."
        ),
    )
    cifre_totali: int = Field(
        ge=0, description="Numeri nella narrativa fuori dalla lista fissa."
    )
    cifre_istat: int = Field(
        default=0,
        ge=0,
        description="Cifre ISTAT scritte dal modello, in qualunque blocco (attese 0).",
    )
    frasi_scartabili: int = Field(ge=0, description="Frasi che il filtro toglie.")
    voci_fornite: int = Field(
        ge=0, description="Voci ISTAT nel prompt (cornice esclusa)."
    )
    voci_citate: int = Field(
        ge=0, description="Voci nominate in frasi ISTAT che il filtro tiene."
    )
    frasi_istat: int = Field(
        ge=0, description="Frasi di qualunque blocco che parlano del dato ISTAT."
    )
    frasi_istat_con_luogo: int = Field(
        ge=0, description="Di queste, quante nominano il luogo del dato."
    )
    frasi_istat_con_luogo_ereditato: int = Field(
        default=0,
        ge=0,
        description=(
            "Frasi ISTAT senza luogo che usano quello detto prima nello stesso "
            "paragrafo (non contate in frasi_istat_con_luogo)."
        ),
    )
    direzioni_totali: int = Field(
        ge=0, description="Frasi ISTAT con parole di tendenza su una voce."
    )
    direzioni_coerenti: int = Field(ge=0, description="Di queste, coerenti col segno.")
    confronti_totali: int = Field(
        default=0,
        ge=0,
        description="Frasi ISTAT che confrontano col dato italiano una voce classificata.",  # noqa: E501
    )
    confronti_coerenti: int = Field(
        default=0, ge=0, description="Di queste, coerenti col confronto della riga."
    )
    corrispondenze_non_dichiarate: int = Field(
        ge=0,
        description=(
            "Frasi ISTAT su voci piu' ampie/strette del rischio senza dirlo "
            "(euristica sul testo)."
        ),
    )
    numeri_in_lettere: int = Field(
        ge=0, description="Numeri scritti in lettere (non tolti)."
    )
    codici_voce: int = Field(
        default=0,
        ge=0,
        description=(
            "Codici delle voci ISTAT (es. THEFT) scritti dal modello, a parola "
            "intera e in maiuscolo (attesi 0; non tolgono la frase)."
        ),
    )
    frasi_escluse_m1: int = Field(
        default=0,
        ge=0,
        description=(
            "Frasi che parlano del dato ISTAT senza nominare un POI ne' un rischio, "
            "escluse dal denominatore di M1 (#369; 0 prima della versione 4)."
        ),
    )
    frasi_escluse_senza_voce: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Di frasi_escluse_m1, quante non nominano nessuna voce delle righe "
            "ISTAT del prompt ne' un rischio collegato (#378): candidate da leggere "
            "a mano, non un conteggio di rischi inventati. None sui record "
            "precedenti a #378."
        ),
    )


class RunCase(BaseModel):
    """A single case (citta, zona)."""

    citta: str
    zona: str


class ExperimentConfig(BaseModel):
    """Configuration of an experiment: one machine, many runs."""

    name: str = Field(description="Nome dell'esperimento (prefisso di run_id e file).")
    mode: Mode = Field(
        description=(
            "analyze (con LLM), baseline (senza LLM) o no_ontology_prompt "
            "(con LLM, prompt senza il contributo ontologico)."
        )
    )
    model: ModelChoice = Field(description="Provider LLM (ignorato se mode=baseline).")
    cases: list[RunCase] = Field(description="Casi da eseguire.")
    # Third dimension of the experiment next to mode/model (#273), opt-in: an
    # experiment that does not name it behaves exactly as before. The two
    # arms of an A/B on the prompt must be launched with TWO distinct ``name``s,
    # because the format does not enter the ``run_id`` (changing it would rename
    # every existing run); ``Provenance.context_format`` then makes every record
    # self-describing.
    context_format: ContextFormat = Field(
        default=DEFAULT_CONTEXT_FORMAT,
        description="Formato del blocco POI dello user_content (#273).",
    )
    # #345: ontology + ISTAT arm (spec 4.9). Off by default: the thesis comparison
    # ontology vs without ontology runs without ISTAT (D6).
    istat: bool = Field(default=False, description="Dati ISTAT nel prompt (#345).")

    @model_validator(mode="after")
    def _reject_grouping_without_ontology(self) -> ExperimentConfig:
        """``per_classe`` does not exist in the ablated arm (#236).

        The ablated prompt is always one row per point: it carries no hazard, so
        it has no set to group by class. The format is not however
        without effect (#349): the ablated arm passes it to the reconstructed
        selection of the full arm's POIs, and with ``per_classe`` it would pick the
        points of a ``per_classe`` full arm. The constraint stays because the
        thesis pair is ``per_poi`` against ``per_poi``: an ablated
        ``per_classe`` would declare in the ``Provenance`` a POI block format
        that its prompt does not have, and POI parity would have to be sought against
        a full arm different from that of the comparison.
        """
        if self.mode == "no_ontology_prompt" and self.context_format != "per_poi":
            raise ValueError(
                "mode='no_ontology_prompt' non ammette "
                f"context_format={self.context_format!r}: il prompt ablato non "
                "porta hazard, quindi non c'e' nulla da raggruppare per classe "
                "(la coppia del confronto e' per_poi contro per_poi)"
            )
        return self

    @model_validator(mode="after")
    def _reject_istat_without_full_arm(self) -> ExperimentConfig:
        """ISTAT only in the full arm: without an LLM there is no prompt, without
        ontology there are no hazards to link the items to."""
        if self.istat and self.mode != "analyze":
            raise ValueError(
                f"mode={self.mode!r} non ammette istat=True: i dati ISTAT si "
                "collegano agli hazard dell'ontologia nel prompt del braccio completo"
            )
        return self


class RunRecord(BaseModel):
    """Complete record of a run (source of truth, one JSON per run)."""

    run_id: str
    experiment: str
    citta: str
    zona: str
    mode: Mode
    model_id: str
    status: RunStatus
    metrics: Metrics
    narrativa: str = Field(
        description=(
            "Narrativa mostrata all'operatore (filtrata dal controllo delle "
            "cifre con ISTAT, #345). eval/gold.py (collect_kept_risks) e "
            "eval/compare.py (has_narrative / vacuity) leggono QUESTO campo, "
            "non narrativa_grezza: coincide con il grezzo nel braccio analyze a "
            "ISTAT spento."
        )
    )
    n_poi: int = Field(ge=0)
    risk_models: list[RiskModel] = Field(
        default_factory=list[RiskModel],
        description=(
            "Set grounded COMPLETO (pre-filtro, costruito PRIMA della "
            "generazione LLM — identico fra analyze/baseline/no_ontology_prompt "
            "per la stessa (citta, zona)). NON e' 'cosa l'LLM ha mantenuto': "
            "quella nozione (#152) si applica a valle, in eval/gold.py, "
            "incrociando questo campo con la narrativa via "
            "metrics.hazards_cited_in. Lista vuota su status=ERROR (nessuna "
            "risposta strutturata da cui copiare); popolata anche su FALLBACK, "
            "perche' il set grounded e' costruito prima della chiamata LLM."
        ),
    )
    narrativa_grezza: str | None = Field(
        default=None,
        description="Testo del modello prima del controllo delle cifre (#345); None sui record vecchi.",  # noqa: E501
    )
    poi_nel_prompt: list[str] | None = Field(
        default=None,
        description=(
            "Id (``poi_id``) dei POI entrati nel prompt del braccio LLM, nell'ordine "
            "in cui il prompt li elenca (#349). Il confronto analyze vs "
            "no_ontology_prompt dichiara la variabile isolata solo se, zona per "
            "zona, i due INSIEMI coincidono. None sulla baseline (nessun prompt), "
            "sui fallback e sui record precedenti a #349."
        ),
    )
    istat_frasi_scartate: int = Field(
        default=0, ge=0, description="Frasi tolte (#345)."
    )
    istat_metrics: IstatMetrics | None = Field(
        default=None,
        description="Metriche ISTAT (#345); None senza dati ISTAT nel prompt.",
    )
    frasi_escluse_m1: list[str] | None = Field(
        default=None,
        description=(
            "Frasi del grezzo escluse dal denominatore di M1 perche' parlano del "
            "dato ISTAT senza nominare un POI ne' un rischio (#369): con "
            "narrativa_grezza ricostruiscono il testo misurato. None senza dati "
            "ISTAT nel prompt, sui record precedenti a #369 e sui record-media."
        ),
    )
    frasi_escluse_senza_voce: list[str] | None = Field(
        default=None,
        description=(
            "Le frasi di frasi_escluse_m1 che non nominano nessuna voce delle righe "
            "ISTAT del prompt ne' un rischio collegato (#378): candidate a un "
            "rischio fuori dalla base di conoscenza, da leggere a mano. None senza "
            "dati ISTAT nel prompt, sui record precedenti a #378 e sui record-media."
        ),
    )
    provenance: Provenance
