"""Test del CLI eval: build_parser e load_config (#34)."""

from __future__ import annotations

import json
from pathlib import Path

from crime_risk_analyzer.eval.cli import build_parser, load_config


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
