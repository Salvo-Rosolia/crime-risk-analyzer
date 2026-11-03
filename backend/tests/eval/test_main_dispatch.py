"""WIRING tests of the entry point ``eval/__main__.main`` (#118).

Covers the ROUTING of the arguments: ``main()`` with the ``argv`` of a subcommand
must route to the right function with the right arguments. The internal functions
are mocked (no network, no LLM, no real graph): here the dispatch is
verified, not the behaviour of the routed functions (tested
elsewhere). The ``compare``/``compare-repeated``/``gold-sample``/``gold-report``
branches have their dispatch tests in the respective files
(test_compare/test_repeated_comparison/test_gold, those of the two gold verbs
added with the fix wave of #152); here I cover the residual branches: capture, run,
aggregate, city-agnostic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import crime_risk_analyzer.eval.__main__ as eval_main
from crime_risk_analyzer.eval.__main__ import CaptureCase, CaptureSummary
from crime_risk_analyzer.eval.schema import ExperimentConfig, Mode, RunCase


def _set_argv(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["crime_risk_analyzer.eval", *args])


def _write_config(tmp_path: Path, *, mode: Mode) -> Path:
    cfg = ExperimentConfig(
        name="exp",
        mode=mode,
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    path = tmp_path / "cfg.json"
    path.write_text(cfg.model_dump_json(), encoding="utf-8")
    return path


# --- capture -----------------------------------------------------------------


def test_main_capture_routes_to_capture_with_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``capture --config C --results R --force`` -> ``_capture`` with
    ``force=True``."""
    calls: list[tuple[Path, Path, bool]] = []

    async def fake_capture(
        config_path: Path, results_dir: Path, *, force: bool = False
    ) -> CaptureSummary:
        calls.append((config_path, results_dir, force))
        return CaptureSummary(succeeded=(), failed=())

    monkeypatch.setattr(eval_main, "_capture", fake_capture)
    cfg = tmp_path / "cfg.json"
    _set_argv(
        monkeypatch,
        "capture",
        "--config",
        str(cfg),
        "--results",
        str(tmp_path),
        "--force",
    )

    assert eval_main.main() == 0
    assert calls == [(cfg, tmp_path, True)]


def test_main_capture_force_defaults_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ``--force`` the dispatch passes ``force=False`` (idempotent by
    default)."""
    seen_force: list[bool] = []

    async def fake_capture(
        config_path: Path, results_dir: Path, *, force: bool = False
    ) -> CaptureSummary:
        seen_force.append(force)
        return CaptureSummary(succeeded=(), failed=())

    monkeypatch.setattr(eval_main, "_capture", fake_capture)
    _set_argv(
        monkeypatch,
        "capture",
        "--config",
        str(tmp_path / "c.json"),
        "--results",
        str(tmp_path),
    )

    assert eval_main.main() == 0
    assert seen_force == [False]


def test_main_capture_returns_nonzero_on_partial_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#252: if the summary of ``_capture`` reports failed cases, ``main()``
    exits with a non-zero code -- a partial capture is not a complete
    experiment."""

    async def fake_capture(
        config_path: Path, results_dir: Path, *, force: bool = False
    ) -> CaptureSummary:
        return CaptureSummary(
            succeeded=(CaptureCase("Roma", "Centro"),),
            failed=(
                CaptureCase("Milano", "Duomo", error_type="OverpassError", error="503"),
            ),
        )

    monkeypatch.setattr(eval_main, "_capture", fake_capture)
    _set_argv(
        monkeypatch,
        "capture",
        "--config",
        str(tmp_path / "c.json"),
        "--results",
        str(tmp_path),
    )

    assert eval_main.main() != 0


# --- run (also exercises the body of _run: build client + run_experiment) -----


def test_main_run_baseline_routes_without_llm_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run`` baseline: _run does not build the client (llm_client=None) and forwards
    repeat/clean_stale/results_dir to run_experiment. I do NOT mock _run: so the
    dispatch AND the body of _run are both exercised."""
    captured: dict[str, object] = {}

    async def fake_run_experiment(config: ExperimentConfig, **kwargs: object) -> None:
        captured["config"] = config
        captured.update(kwargs)

    monkeypatch.setattr(eval_main, "run_experiment", fake_run_experiment)
    monkeypatch.setattr(eval_main, "get_executor", lambda: object())

    def _explode(config: ExperimentConfig) -> object:
        raise AssertionError("baseline non deve costruire il client LLM")

    monkeypatch.setattr(eval_main, "build_llm_eval_client", _explode)

    cfg = _write_config(tmp_path, mode="baseline")
    _set_argv(
        monkeypatch,
        "run",
        "--config",
        str(cfg),
        "--results",
        str(tmp_path),
        "--repeat",
        "3",
        "--clean-stale",
    )

    assert eval_main.main() == 0
    assert captured["llm_client"] is None
    assert captured["repeat"] == 3
    assert captured["clean_stale"] is True
    assert captured["results_dir"] == tmp_path
    assert isinstance(captured["config"], ExperimentConfig)


def test_main_run_analyze_builds_and_passes_llm_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run`` analyze: _run builds the client via build_llm_eval_client and forwards it
    to run_experiment (branch mode != baseline of line 133)."""
    sentinel = object()
    captured: dict[str, object] = {}

    async def fake_run_experiment(config: ExperimentConfig, **kwargs: object) -> None:
        captured.update(kwargs)

    def fake_build_client(config: ExperimentConfig) -> object:
        return sentinel

    monkeypatch.setattr(eval_main, "run_experiment", fake_run_experiment)
    monkeypatch.setattr(eval_main, "get_executor", lambda: object())
    monkeypatch.setattr(eval_main, "build_llm_eval_client", fake_build_client)

    cfg = _write_config(tmp_path, mode="analyze")
    _set_argv(monkeypatch, "run", "--config", str(cfg), "--results", str(tmp_path))

    assert eval_main.main() == 0
    assert captured["llm_client"] is sentinel
    # parser default: one repetition, no legacy cleaning.
    assert captured["repeat"] == 1
    assert captured["clean_stale"] is False
    # #357: no pause by default.
    assert captured["pause_seconds"] == 0.0


def test_main_run_no_ontology_builds_and_passes_llm_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#236: the ablated arm too is an arm WITH a model.

    The condition of ``_run`` is ``mode != 'baseline'``: if it were
    ``mode == 'analyze'`` the new arm would run with ``llm_client=None`` and
    the harness would send it into error on every case, silently.
    """
    sentinel = object()
    captured: dict[str, object] = {}

    async def fake_run_experiment(config: ExperimentConfig, **kwargs: object) -> None:
        captured.update(kwargs)

    def fake_build_client(config: ExperimentConfig) -> object:
        return sentinel

    monkeypatch.setattr(eval_main, "run_experiment", fake_run_experiment)
    monkeypatch.setattr(eval_main, "get_executor", lambda: object())
    monkeypatch.setattr(eval_main, "build_llm_eval_client", fake_build_client)

    cfg = _write_config(tmp_path, mode="no_ontology_prompt")
    _set_argv(
        monkeypatch,
        "run",
        "--config",
        str(cfg),
        "--results",
        str(tmp_path),
        "--pausa",
        "0.5",
    )

    assert eval_main.main() == 0
    assert captured["llm_client"] is sentinel
    # #357: --pausa reaches run_experiment.
    assert captured["pause_seconds"] == 0.5


# --- aggregate ---------------------------------------------------------------


def test_main_aggregate_routes_to_write_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``aggregate --experiment E --results R`` -> ``write_tables(R, E)``."""
    calls: list[tuple[Path, str]] = []

    def fake_write_tables(results_dir: Path, experiment: str) -> tuple[Path, Path]:
        calls.append((results_dir, experiment))
        return results_dir / "e.csv", results_dir / "e.md"

    monkeypatch.setattr(eval_main, "write_tables", fake_write_tables)
    _set_argv(
        monkeypatch, "aggregate", "--experiment", "exp", "--results", str(tmp_path)
    )

    assert eval_main.main() == 0
    assert calls == [(tmp_path, "exp")]


# --- city-agnostic -----------------------------------------------------------


def test_main_city_agnostic_capture_routes_to_capture_roster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``city-agnostic capture --results R`` -> ``capture_roster(ROSTER, R)``."""
    calls: list[tuple[object, Path]] = []

    async def fake_capture_roster(roster: object, results_dir: Path) -> None:
        calls.append((roster, results_dir))

    monkeypatch.setattr(eval_main, "capture_roster", fake_capture_roster)
    _set_argv(monkeypatch, "city-agnostic", "capture", "--results", str(tmp_path))

    assert eval_main.main() == 0
    assert calls == [(eval_main.ROSTER, tmp_path)]


def test_main_city_agnostic_report_routes_to_build_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``city-agnostic report --results R`` -> loads the graph ONCE and calls
    ``build_report(R, graph, ontology_hash())``."""
    graph_sentinel = object()
    settings_sentinel = type("S", (), {"ontology_path": "onto.ttl"})()
    calls: list[tuple[Path, object, str]] = []

    def fake_load_ontology(path: str) -> object:
        return graph_sentinel

    monkeypatch.setattr(eval_main, "get_settings", lambda: settings_sentinel)
    monkeypatch.setattr(eval_main, "load_ontology", fake_load_ontology)
    monkeypatch.setattr(eval_main, "ontology_hash", lambda: "hashZ")

    def fake_build_report(
        results_dir: Path, graph: object, ontology_hash: str
    ) -> tuple[Path, Path, Path]:
        calls.append((results_dir, graph, ontology_hash))
        (results_dir / "records.json").write_text(
            json.dumps({"summary": {"avvisi": []}}), encoding="utf-8"
        )
        return (
            results_dir / "records.json",
            results_dir / "report.csv",
            results_dir / "report.md",
        )

    monkeypatch.setattr(eval_main, "build_report", fake_build_report)
    _set_argv(monkeypatch, "city-agnostic", "report", "--results", str(tmp_path))

    assert eval_main.main() == 0
    assert calls == [(tmp_path, graph_sentinel, "hashZ")]


@pytest.mark.parametrize(
    ("warnings", "expected"),
    [
        (["Roma: esito senza provenienza (pre-#374)"], True),
        ([], False),
    ],
)
def test_main_city_agnostic_report_prints_warnings_on_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    warnings: list[str],
    expected: bool,
) -> None:
    """The provenance AVVISO lines also go on screen (stderr), not only in the
    gitignored files; exit code unchanged (0) and no output if consistent."""
    monkeypatch.setattr(
        eval_main, "get_settings", lambda: type("S", (), {"ontology_path": "o"})()
    )

    def fake_load_ontology(path: str) -> object:
        return object()

    monkeypatch.setattr(eval_main, "load_ontology", fake_load_ontology)
    monkeypatch.setattr(eval_main, "ontology_hash", lambda: "h")

    def fake_build_report(
        results_dir: Path, graph: object, ontology_hash: str
    ) -> tuple[Path, Path, Path]:
        records = results_dir / "records.json"
        records.write_text(
            json.dumps({"summary": {"avvisi": warnings}, "records": []}),
            encoding="utf-8",
        )
        return (records, results_dir / "report.csv", results_dir / "report.md")

    monkeypatch.setattr(eval_main, "build_report", fake_build_report)
    _set_argv(monkeypatch, "city-agnostic", "report", "--results", str(tmp_path))

    assert eval_main.main() == 0
    err = capsys.readouterr().err
    if expected:
        assert "AVVISO: Roma: esito senza provenienza (pre-#374)" in err
    else:
        assert "AVVISO" not in err
