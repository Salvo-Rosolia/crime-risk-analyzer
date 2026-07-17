"""Test del CLI eval: build_parser e load_config (#34)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from crime_risk_analyzer.eval.cli import (
    build_llm_eval_client,
    build_parser,
    load_config,
)
from crime_risk_analyzer.eval.schema import ExperimentConfig, RunCase
from crime_risk_analyzer.llm.client import LLMClient


def _settings(**overrides: Any) -> Any:
    from crime_risk_analyzer.config import Settings

    base: dict[str, Any] = {
        "_env_file": None,
        "anthropic_api_key": SecretStr("sk-ant-test"),
        "groq_api_key": SecretStr("gsk-test"),
    }
    base.update(overrides)
    return Settings(**base)  # pyright: ignore[reportCallIssue]


def test_parser_subcommands() -> None:
    parser = build_parser()
    ns = parser.parse_args(["run", "--config", "exp.json", "--results", "results"])
    assert ns.command == "run"
    assert ns.config == "exp.json"


def test_parser_capture_force_flag() -> None:
    """--force è opt-in sul sottocomando capture (ri-cattura, #110 M2)."""
    ns = build_parser().parse_args(["capture", "--config", "exp.json", "--force"])
    assert ns.command == "capture"
    assert ns.force is True


def test_parser_capture_force_defaults_false() -> None:
    """Senza --force la cattura è idempotente (skip-if-exists, #110 M2)."""
    ns = build_parser().parse_args(["capture", "--config", "exp.json"])
    assert ns.force is False


def test_load_config(tmp_path: Path) -> None:
    p = tmp_path / "exp.json"
    p.write_text(
        json.dumps(
            {
                "name": "ablation",
                "mode": "baseline",
                "model": "claude",
                "cases": [{"citta": "Roma", "zona": "Centro"}],
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.name == "ablation"
    assert cfg.cases[0].citta == "Roma"


# --- (C) build_llm_eval_client honora config.model ---


def test_build_llm_eval_client_uses_config_model_groq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """build_llm_eval_client(config) con config.model='groq' deve restituire
    un LLMClient con provider='groq', indipendentemente dal settings."""
    import crime_risk_analyzer.eval.cli as cli_mod

    monkeypatch.setattr(
        cli_mod, "get_settings", lambda: _settings(llm_provider="claude")
    )
    cfg = ExperimentConfig(
        name="test",
        mode="analyze",
        model="groq",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    client = build_llm_eval_client(cfg)
    assert isinstance(client, LLMClient)
    assert client.provider == "groq"


def test_build_llm_eval_client_uses_config_model_claude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """build_llm_eval_client(config) con config.model='claude' deve restituire
    un LLMClient con provider='claude', anche se settings dice groq."""
    import crime_risk_analyzer.eval.cli as cli_mod

    monkeypatch.setattr(cli_mod, "get_settings", lambda: _settings(llm_provider="groq"))
    cfg = ExperimentConfig(
        name="test",
        mode="analyze",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    client = build_llm_eval_client(cfg)
    assert isinstance(client, LLMClient)
    assert client.provider == "claude"


def test_parser_compare_subcommand() -> None:
    """#32: sottocomando compare a due bracci (experiment-a vs experiment-b)."""
    ns = build_parser().parse_args(
        ["compare", "--experiment-a", "full", "--experiment-b", "base"]
    )
    assert ns.command == "compare"
    assert ns.experiment_a == "full"
    assert ns.experiment_b == "base"
    assert ns.label_a is None
    assert ns.label_b is None
    assert ns.out is None
    assert ns.results == "results"


def test_parser_compare_optional_labels_and_out() -> None:
    """Label e stem di output sono opzionali e parametrizzabili (generico)."""
    ns = build_parser().parse_args(
        [
            "compare",
            "--experiment-a",
            "ablation-analyze",
            "--experiment-b",
            "ablation-baseline",
            "--label-a",
            "analyze",
            "--label-b",
            "baseline",
            "--out",
            "ablation",
            "--results",
            "r",
        ]
    )
    assert ns.label_a == "analyze"
    assert ns.label_b == "baseline"
    assert ns.out == "ablation"
    assert ns.results == "r"


def test_parser_city_agnostic_capture() -> None:
    ns = build_parser().parse_args(["city-agnostic", "capture", "--results", "r"])
    assert ns.command == "city-agnostic"
    assert ns.phase == "capture"
    assert ns.results == "r"


def test_parser_city_agnostic_report_defaults_results() -> None:
    ns = build_parser().parse_args(["city-agnostic", "report"])
    assert ns.command == "city-agnostic"
    assert ns.phase == "report"
    assert ns.results == "results"


def test_parser_has_compare_repeated_subcommand() -> None:
    from crime_risk_analyzer.eval.cli import build_parser

    ns = build_parser().parse_args(
        [
            "compare-repeated",
            "--experiment-a",
            "claude-exp",
            "--experiment-b",
            "groq-exp",
        ]
    )
    assert ns.command == "compare-repeated"
    assert ns.experiment_a == "claude-exp"
    assert ns.experiment_b == "groq-exp"


def test_parser_run_has_repeat_default_one() -> None:
    from crime_risk_analyzer.eval.cli import build_parser

    ns = build_parser().parse_args(["run", "--config", "x.json"])
    assert ns.repeat == 1


def test_parser_run_repeat_accepts_explicit_value() -> None:
    """--repeat 3 (non solo il default) -> ns.repeat==3, come int (non str)."""
    ns = build_parser().parse_args(["run", "--config", "x.json", "--repeat", "3"])
    assert ns.repeat == 3


def test_compare_parsers_accept_force_flag() -> None:
    from crime_risk_analyzer.eval.cli import build_parser

    for cmd in ("compare", "compare-repeated"):
        ns = build_parser().parse_args(
            [cmd, "--experiment-a", "a", "--experiment-b", "b", "--force"]
        )
        assert ns.force is True
    # default assente → False
    ns = build_parser().parse_args(
        ["compare", "--experiment-a", "a", "--experiment-b", "b"]
    )
    assert ns.force is False
