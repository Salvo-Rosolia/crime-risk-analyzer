"""Entry point: uv run python -m crime_risk_analyzer.eval <comando> ..."""

from __future__ import annotations

import asyncio
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
from crime_risk_analyzer.eval.harness import make_run_id, run_experiment
from crime_risk_analyzer.eval.snapshots import capturing_source, snapshot_path
from crime_risk_analyzer.ontology import load_ontology
from crime_risk_analyzer.orchestrator import run_analysis, run_baseline
from crime_risk_analyzer.sparql_module.query_executor import get_executor


async def _capture(config_path: Path, results_dir: Path) -> None:
    config = load_config(config_path)
    executor = get_executor()
    # Build the client only when the mode requires it (fix T9: baseline needs no key).
    llm_client = build_llm_eval_client(config) if config.mode != "baseline" else None
    for case in config.cases:
        run_id = make_run_id(
            config.name, case.citta, case.zona, config.mode, config.model
        )
        source = capturing_source(snapshot_path(results_dir, run_id))
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


async def _run(config_path: Path, results_dir: Path) -> None:
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
    )


def main() -> int:
    ns = build_parser().parse_args()
    results_dir = Path(ns.results)
    if ns.command == "capture":
        asyncio.run(_capture(Path(ns.config), results_dir))
    elif ns.command == "run":
        asyncio.run(_run(Path(ns.config), results_dir))
    elif ns.command == "aggregate":
        write_tables(results_dir, ns.experiment)
    elif ns.command == "city-agnostic":
        if ns.phase == "capture":
            asyncio.run(capture_roster(ROSTER, results_dir))
        else:
            graph = load_ontology(get_settings().ontology_path)
            build_report(results_dir, graph, ontology_hash())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
