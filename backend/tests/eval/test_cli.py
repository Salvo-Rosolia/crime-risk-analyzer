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
