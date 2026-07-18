"""Test di WIRING dell'entry point ``eval/__main__.main`` (#118).

Copre il ROUTING degli argomenti: ``main()`` con l'``argv`` di un sottocomando
deve instradare alla funzione giusta con gli argomenti giusti. Le funzioni
interne sono mockate (nessuna rete, nessun LLM, nessun grafo reale): qui si
verifica il dispatch, non il comportamento delle funzioni instradate (testate
altrove). I branch ``compare``/``compare-repeated``/``gold`` hanno gia' test di
dispatch nei rispettivi file (test_compare/test_repeated_comparison/test_gold);
qui copro i branch residui: capture, run, aggregate, city-agnostic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import crime_risk_analyzer.eval.__main__ as eval_main
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
    """``capture --config C --results R --force`` → ``_capture`` con ``force=True``."""
    calls: list[tuple[Path, Path, bool]] = []

    async def fake_capture(
        config_path: Path, results_dir: Path, *, force: bool = False
    ) -> None:
        calls.append((config_path, results_dir, force))

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
    """Senza ``--force`` il dispatch passa ``force=False`` (idempotenza di default)."""
    seen_force: list[bool] = []

    async def fake_capture(
        config_path: Path, results_dir: Path, *, force: bool = False
    ) -> None:
        seen_force.append(force)

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


# --- run (esercita anche il corpo di _run: build client + run_experiment) -----


def test_main_run_baseline_routes_without_llm_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run`` baseline: _run non costruisce il client (llm_client=None) e inoltra
    repeat/clean_stale/results_dir a run_experiment. NON mocko _run: cosi' il
    dispatch E il corpo di _run sono entrambi esercitati."""
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
    """``run`` analyze: _run costruisce il client via build_llm_eval_client e lo
    inoltra a run_experiment (ramo mode != baseline della riga 133)."""
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
    # default del parser: una ripetizione, nessuna pulizia legacy.
    assert captured["repeat"] == 1
    assert captured["clean_stale"] is False


# --- aggregate ---------------------------------------------------------------


def test_main_aggregate_routes_to_write_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``aggregate --experiment E --results R`` → ``write_tables(R, E)``."""
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
    """``city-agnostic capture --results R`` → ``capture_roster(ROSTER, R)``."""
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
    """``city-agnostic report --results R`` → carica il grafo UNA volta e chiama
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
        return (
            results_dir / "records.json",
            results_dir / "report.csv",
            results_dir / "report.md",
        )

    monkeypatch.setattr(eval_main, "build_report", fake_build_report)
    _set_argv(monkeypatch, "city-agnostic", "report", "--results", str(tmp_path))

    assert eval_main.main() == 0
    assert calls == [(tmp_path, graph_sentinel, "hashZ")]
