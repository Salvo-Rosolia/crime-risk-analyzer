"""Harness di esecuzione di un esperimento di valutazione (#34)."""

from __future__ import annotations

import re
from pathlib import Path

from crime_risk_analyzer.eval.metrics import compute_metrics
from crime_risk_analyzer.eval.schema import (
    ExperimentConfig,
    Metrics,
    Provenance,
    RunCase,
    RunRecord,
    RunStatus,
)
from crime_risk_analyzer.eval.snapshots import replay_source, snapshot_path
from crime_risk_analyzer.orchestrator import (
    AnalyzeResponse,
    _LLMClientLike,  # pyright: ignore[reportPrivateUsage]
    run_analysis,
    run_baseline,
)
from crime_risk_analyzer.rag.retrieval import RiskProfiler


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def make_run_id(experiment: str, citta: str, zona: str, mode: str, model: str) -> str:
    """run_id deterministico: niente timestamp, ri-girare sovrascrive."""
    parts = [experiment, citta, zona, mode, model]
    return "__".join(_slug(p) for p in parts)


def write_record(results_dir: Path, record: RunRecord) -> Path:
    """Scrive il RunRecord come JSON in results/runs/<run_id>.json."""
    path = results_dir / "runs" / f"{record.run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return path


def _record_from_response(
    *,
    run_id: str,
    config: ExperimentConfig,
    case: RunCase,
    model_id: str,
    resp: AnalyzeResponse,
    code_commit: str,
    ontology_hash: str,
) -> RunRecord:
    status = RunStatus.FALLBACK if resp.fallback else RunStatus.OK
    return RunRecord(
        run_id=run_id,
        experiment=config.name,
        citta=case.citta,
        zona=case.zona,
        mode=config.mode,
        model_id=model_id,
        status=status,
        metrics=compute_metrics(resp),
        narrativa=resp.narrativa,
        n_poi=len(resp.poi),
        provenance=Provenance(
            code_commit=code_commit,
            ontology_hash=ontology_hash,
            snapshot_id=run_id,
            model_id=model_id,
            prompt_hash=resp.repro.prompt_hash,
            temperature=resp.repro.temperature,
            seed=resp.repro.seed,
            experiment=config.name,
        ),
    )


def _error_record(
    *,
    run_id: str,
    config: ExperimentConfig,
    case: RunCase,
    model_id: str,
    code_commit: str,
    ontology_hash: str,
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        experiment=config.name,
        citta=case.citta,
        zona=case.zona,
        mode=config.mode,
        model_id=model_id,
        status=RunStatus.ERROR,
        metrics=Metrics(grounding=0.0, hallucination=0.0, latency_ms=0, cost_usd=0.0),
        narrativa="",
        n_poi=0,
        provenance=Provenance(
            code_commit=code_commit,
            ontology_hash=ontology_hash,
            snapshot_id=run_id,
            model_id=model_id,
            prompt_hash="",
            temperature=0.0,
            seed=0,
            experiment=config.name,
        ),
    )


def _model_id_of(llm_client: _LLMClientLike, config: ExperimentConfig) -> str:
    """Model id dal client se esposto (.model), altrimenti dal config."""
    model = getattr(llm_client, "model", None)
    if isinstance(model, str):
        return model
    return (
        "claude-sonnet-4-6" if config.model == "claude" else "llama-3.3-70b-versatile"
    )


async def run_case(
    case: RunCase,
    config: ExperimentConfig,
    *,
    executor: RiskProfiler,
    llm_client: _LLMClientLike | None = None,
    results_dir: Path,
    code_commit: str,
    ontology_hash: str,
) -> RunRecord:
    """Esegue un caso e ritorna il RunRecord (status=error su eccezione).

    ``llm_client`` e' opzionale: richiesto solo per ``mode='analyze'``;
    per ``mode='baseline'`` puo' essere ``None``.
    Solleva :class:`ValueError` se ``mode='analyze'`` e ``llm_client is None``.
    """
    model_id: str
    if config.mode == "baseline":
        model_id = "baseline"
    else:
        if llm_client is None:
            raise ValueError("llm_client required for mode=analyze")
        model_id = _model_id_of(llm_client, config)
    run_id = make_run_id(config.name, case.citta, case.zona, config.mode, config.model)
    source = replay_source(snapshot_path(results_dir, run_id))
    try:
        if config.mode == "baseline":
            resp = await run_baseline(
                case.citta, case.zona, executor=executor, poi_source=source
            )
        else:
            assert llm_client is not None  # narrowing per pyright strict
            resp = await run_analysis(
                case.citta,
                case.zona,
                executor=executor,
                llm_client=llm_client,
                poi_source=source,
            )
    except Exception:  # noqa: BLE001 — un caso rotto non blocca l'esperimento
        return _error_record(
            run_id=run_id,
            config=config,
            case=case,
            model_id=model_id,
            code_commit=code_commit,
            ontology_hash=ontology_hash,
        )
    return _record_from_response(
        run_id=run_id,
        config=config,
        case=case,
        model_id=model_id,
        resp=resp,
        code_commit=code_commit,
        ontology_hash=ontology_hash,
    )


async def run_experiment(
    config: ExperimentConfig,
    *,
    executor: RiskProfiler,
    llm_client: _LLMClientLike | None = None,
    results_dir: Path,
    code_commit: str,
    ontology_hash: str,
) -> list[RunRecord]:
    """Esegue tutti i casi, scrive i JSON, ritorna i record.

    ``llm_client`` e' opzionale: puo' essere ``None`` per ``mode='baseline'``;
    per ``mode='analyze'`` deve essere fornito (propagato a :func:`run_case`).
    """
    records: list[RunRecord] = []
    for case in config.cases:
        record = await run_case(
            case,
            config,
            executor=executor,
            llm_client=llm_client,
            results_dir=results_dir,
            code_commit=code_commit,
            ontology_hash=ontology_hash,
        )
        write_record(results_dir, record)
        records.append(record)
    return records
