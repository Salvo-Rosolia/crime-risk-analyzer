"""Entry point: uv run python -m crime_risk_analyzer.eval <comando> ..."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.eval.aggregate import write_tables
from crime_risk_analyzer.eval.city_agnostic import ROSTER, capture_roster
from crime_risk_analyzer.eval.city_agnostic_report import build_report
from crime_risk_analyzer.eval.cli import (
    build_llm_eval_client,
    build_parser,
    code_commit,
    load_config,
    ontology_hash,
)
from crime_risk_analyzer.eval.compare import compare_experiments
from crime_risk_analyzer.eval.gold import write_agreement_report
from crime_risk_analyzer.eval.harness import make_snapshot_key, run_experiment
from crime_risk_analyzer.eval.repeated_comparison import build_repeated_report
from crime_risk_analyzer.eval.snapshots import (
    capturing_source,
    load_snapshot,
    snapshot_path,
)
from crime_risk_analyzer.ontology import load_ontology
from crime_risk_analyzer.orchestrator import run_analysis, run_baseline
from crime_risk_analyzer.overpass_client import fetch_pois
from crime_risk_analyzer.rag.retrieval import PoiSource
from crime_risk_analyzer.sparql_module.query_executor import get_executor

logger = logging.getLogger(__name__)


def _snapshot_reusable(path: Path) -> bool:
    """True se lo snapshot esistente è riusabile sullo skip (#148).

    Riusabile = il file esiste, è non vuoto (``size > 0``) ED è JSON parsabile.
    Uno snapshot troncato/corrotto (scrittura interrotta) NON è riusabile: va
    ri-catturato invece di essere rigiocato in silenzio (recuperabile prima solo
    con ``--force``). Check leggero: non valida ogni POI, solo che il file
    ``load_snapshot`` lo sappia leggere senza esplodere.
    """
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        load_snapshot(path)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return True


async def _capture(
    config_path: Path,
    results_dir: Path,
    *,
    force: bool = False,
    poi_source: PoiSource | None = None,
) -> None:
    config = load_config(config_path)
    executor = get_executor()
    # Build the client only when the mode requires it (fix T9: baseline needs no key).
    llm_client = build_llm_eval_client(config) if config.mode != "baseline" else None
    inner = poi_source or fetch_pois
    for case in config.cases:
        # Cattura chiavata per (citta, zona) (#110): i bracci comparativi
        # riusano la stessa fixture, senza query Overpass divergenti per braccio.
        key = make_snapshot_key(case.citta, case.zona)
        path = snapshot_path(results_dir, key)
        # Idempotenza (skip-if-exists, #110 M2): non ri-catturare la stessa
        # (citta, zona) per un secondo braccio — reintrodurrebbe il confondimento.
        # Salta SOLO se lo snapshot è integro (#148): uno troncato/corrotto va
        # ri-catturato, non rigiocato in silenzio. --force forza la ri-cattura.
        if not force and _snapshot_reusable(path):
            logger.info(
                "snapshot (%s, %s) già presente, riuso: %s",
                case.citta,
                case.zona,
                path,
            )
            continue
        if not force and path.exists():
            logger.warning(
                "snapshot (%s, %s) presente ma vuoto/corrotto, ri-cattura: %s",
                case.citta,
                case.zona,
                path,
            )
        source = capturing_source(path, inner=inner)
        if config.mode == "baseline":
            await run_baseline(
                case.citta, case.zona, executor=executor, poi_source=source
            )
        else:
            assert llm_client is not None  # narrowing: mode != baseline guarantees this
            await run_analysis(
                case.citta,
                case.zona,
                executor=executor,
                llm_client=llm_client,
                poi_source=source,
            )


async def _run(
    config_path: Path, results_dir: Path, *, repeat: int = 1, clean_stale: bool = False
) -> None:
    config = load_config(config_path)
    # Build the client only when mode requires it (fix T9), using config.model (fix I1).
    client = build_llm_eval_client(config) if config.mode != "baseline" else None
    await run_experiment(
        config,
        executor=get_executor(),
        llm_client=client,
        results_dir=results_dir,
        code_commit=code_commit(),
        ontology_hash=ontology_hash(),
        repeat=repeat,
        clean_stale=clean_stale,
    )


def main() -> int:
    ns = build_parser().parse_args()
    results_dir = Path(ns.results)
    if ns.command == "capture":
        asyncio.run(_capture(Path(ns.config), results_dir, force=ns.force))
    elif ns.command == "run":
        asyncio.run(
            _run(
                Path(ns.config),
                results_dir,
                repeat=ns.repeat,
                clean_stale=ns.clean_stale,
            )
        )
    elif ns.command == "aggregate":
        write_tables(results_dir, ns.experiment)
    elif ns.command == "compare":
        compare_experiments(
            results_dir,
            ns.experiment_a,
            ns.experiment_b,
            label_a=ns.label_a,
            label_b=ns.label_b,
            stem=ns.out,
            force=ns.force,
        )
    elif ns.command == "compare-repeated":
        build_repeated_report(
            results_dir,
            ns.experiment_a,
            ns.experiment_b,
            label_a=ns.label_a,
            label_b=ns.label_b,
            stem=ns.out,
            force=ns.force,
        )
    elif ns.command == "city-agnostic":
        if ns.phase == "capture":
            asyncio.run(capture_roster(ROSTER, results_dir))
        else:
            graph = load_ontology(get_settings().ontology_path)
            build_report(results_dir, graph, ontology_hash())
    elif ns.command == "gold":
        write_agreement_report(
            results_dir, experiment=ns.experiment, threshold=ns.threshold
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
