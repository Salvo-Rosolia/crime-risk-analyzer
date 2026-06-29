"""CLI della fondazione di valutazione: capture/run/aggregate (#34)."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path

from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.eval.schema import ExperimentConfig
from crime_risk_analyzer.llm.client import LLMClient, build_llm_client


def load_config(path: Path) -> ExperimentConfig:
    """Carica un ExperimentConfig da file JSON."""
    return ExperimentConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))


def code_commit() -> str:
    """git rev-parse HEAD (vuoto se non disponibile)."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def ontology_hash() -> str:
    """sha256 del file ontologia configurato (vuoto se non trovato)."""
    settings = get_settings()
    path = Path(settings.ontology_path)
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_llm_eval_client(config: ExperimentConfig) -> LLMClient:
    """Client LLM con temperature=0 per il determinismo nella pipeline eval.

    Rispetta ``config.model`` come provider override, cosi' il ``run_id``
    riporta il provider effettivamente usato (fix I1). Chiamare solo quando
    ``config.mode != 'baseline'`` (fix T9): baseline non usa l'LLM.
    """
    return build_llm_client(get_settings(), provider=config.model).with_temperature(
        0.0, 0
    )


def build_parser() -> argparse.ArgumentParser:
    """Parser con i sottocomandi capture/run/aggregate."""
    parser = argparse.ArgumentParser(prog="crime_risk_analyzer.eval")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("capture", "run"):
        p = sub.add_parser(name)
        p.add_argument("--config", required=True)
        p.add_argument("--results", default="results")
    agg = sub.add_parser("aggregate")
    agg.add_argument("--experiment", required=True)
    agg.add_argument("--results", default="results")
    return parser
