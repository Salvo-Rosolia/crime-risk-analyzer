"""Harness di esecuzione di un esperimento di valutazione (#34).

Vincolo migrazione (#165.4): ``results/runs/`` deve contenere solo run in
formato #157 (run_id con marker ``__rep{NN}``). Record legacy pre-#157 per lo
stesso esperimento sono rilevati e rifiutati da ``run`` (o rimossi con
``--clean-stale``): coesistere con run ``__rep`` corromperebbe fold/compare.
"""

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
from crime_risk_analyzer.eval.snapshots import (
    offline_geo_source,
    replay_source,
    snapshot_path,
)
from crime_risk_analyzer.orchestrator import (
    AnalyzeResponse,
    _LLMClientLike,  # pyright: ignore[reportPrivateUsage]
    run_analysis,
    run_baseline,
)
from crime_risk_analyzer.rag.retrieval import RiskProfiler


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def make_run_id(
    experiment: str, citta: str, zona: str, mode: str, model: str, rep: int = 0
) -> str:
    """run_id deterministico + indice di ripetizione (#157).

    Il suffisso ``__rep{NN}`` (2 cifre) rende distinte le K ripetizioni dello
    stesso (esperimento, citta, zona, mode, model): rigirare con --repeat K NON
    sovrascrive piu' i JSON. ``rep=0`` di default (K=1) → ``__rep00``.
    """
    parts = [experiment, citta, zona, mode, model]
    return "__".join(_slug(p) for p in parts) + f"__rep{rep:02d}"


def make_snapshot_key(citta: str, zona: str) -> str:
    """Chiave dello snapshot POI, derivata SOLO da (citta, zona) (#110).

    Indipendente da mode/model: i bracci comparativi (analyze/claude,
    analyze/groq, baseline) sulla stessa (citta, zona) rigiocano la STESSA
    fixture POI (confronto iso-input, sblocca #32/#33). Riusa lo stesso
    ``_slug`` di :func:`make_run_id`, così la normalizzazione di citta/zona
    resta unica e non diverge tra run_id e chiave snapshot.
    """
    return "__".join(_slug(p) for p in (citta, zona))


_REP_MARKER = re.compile(r"__rep\d{2,}$")


def is_repeated_run_id(run_id: str) -> bool:
    """True se il run_id porta il marker di ripetizione ``__rep{NN}`` (#157)."""
    return _REP_MARKER.search(run_id) is not None


def legacy_run_paths(results_dir: Path, experiment: str) -> list[Path]:
    """Path dei record dell'esperimento in formato PRE-#157 (senza ``__rep``).

    Un record legacy per la stessa (citta, zona) di una run ``__rep`` verrebbe
    trattato come ripetizione stantia da fold/compare: va rilevato prima di
    scrivere nuove ripetizioni.
    """
    from crime_risk_analyzer.eval.aggregate import load_runs

    return [
        results_dir / "runs" / f"{rec.run_id}.json"
        for rec in load_runs(results_dir, experiment=experiment)
        if not is_repeated_run_id(rec.run_id)
    ]


def guard_no_legacy_runs(
    results_dir: Path, experiment: str, *, clean_stale: bool = False
) -> None:
    """Difende da record legacy pre-#157 per l'esperimento (#165.4).

    ``clean_stale=True`` li rimuove; altrimenti solleva ``ValueError`` con
    l'elenco e l'indicazione di rigenerare o usare ``--clean-stale``.
    """
    legacy = legacy_run_paths(results_dir, experiment)
    if not legacy:
        return
    if clean_stale:
        for path in legacy:
            path.unlink(missing_ok=True)
        return
    joined = ", ".join(str(p) for p in legacy)
    raise ValueError(
        f"run legacy pre-#157 (senza __rep) per l'esperimento '{experiment}': "
        f"{joined}. Rigenera results/runs/ o rilancia con --clean-stale."
    )


def write_record(results_dir: Path, record: RunRecord) -> Path:
    """Scrive il RunRecord come JSON in results/runs/<run_id>.json."""
    path = results_dir / "runs" / f"{record.run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return path


def _record_from_response(
    *,
    run_id: str,
    snapshot_id: str,
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
            snapshot_id=snapshot_id,
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
    snapshot_id: str,
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
            snapshot_id=snapshot_id,
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
    rep: int = 0,
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
    run_id = make_run_id(
        config.name, case.citta, case.zona, config.mode, config.model, rep
    )
    # Snapshot chiavato per (citta, zona): condiviso dai bracci comparativi (#110).
    snapshot_key = make_snapshot_key(case.citta, case.zona)
    source = replay_source(snapshot_path(results_dir, snapshot_key))
    # Geo placeholder deterministico (#169): la run replaya i POI e non deve mai
    # chiamare Nominatim. Il geo e' dead-downstream, quindi il valore non conta.
    geo_source = offline_geo_source()
    try:
        if config.mode == "baseline":
            resp = await run_baseline(
                case.citta,
                case.zona,
                executor=executor,
                poi_source=source,
                geo_source=geo_source,
            )
        else:
            assert llm_client is not None  # narrowing per pyright strict
            resp = await run_analysis(
                case.citta,
                case.zona,
                executor=executor,
                llm_client=llm_client,
                poi_source=source,
                geo_source=geo_source,
            )
    except Exception:  # noqa: BLE001 — un caso rotto non blocca l'esperimento
        return _error_record(
            run_id=run_id,
            snapshot_id=snapshot_key,
            config=config,
            case=case,
            model_id=model_id,
            code_commit=code_commit,
            ontology_hash=ontology_hash,
        )
    return _record_from_response(
        run_id=run_id,
        snapshot_id=snapshot_key,
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
    repeat: int = 1,
    clean_stale: bool = False,
) -> list[RunRecord]:
    """Esegue tutti i casi ``repeat`` volte, scrive i JSON, ritorna i record.

    ``llm_client`` e' opzionale: puo' essere ``None`` per ``mode='baseline'``;
    per ``mode='analyze'`` deve essere fornito (propagato a :func:`run_case`).

    ``repeat`` (#157): K ripetizioni per stimare la varianza; ogni ripetizione
    ha un ``rep`` distinto nel run_id (nessuna sovrascrittura). Default 1.

    ``clean_stale`` (#165.4): se ``True`` rimuove i record legacy pre-#157
    dell'esperimento prima di eseguire; altrimenti la guardia solleva
    :class:`ValueError` se ne trova (coesistere con run ``__rep`` corrompe
    fold/compare).

    Solleva :class:`ValueError` se ``repeat < 1`` (niente esperimento vuoto
    in silenzio: senza guardia ``range(repeat)`` ritornerebbe ``[]``).
    """
    if repeat < 1:
        raise ValueError(f"repeat deve essere >= 1, ricevuto {repeat}")
    guard_no_legacy_runs(results_dir, config.name, clean_stale=clean_stale)
    records: list[RunRecord] = []
    for rep in range(repeat):
        for case in config.cases:
            record = await run_case(
                case,
                config,
                executor=executor,
                llm_client=llm_client,
                results_dir=results_dir,
                code_commit=code_commit,
                ontology_hash=ontology_hash,
                rep=rep,
            )
            write_record(results_dir, record)
            records.append(record)
    return records
