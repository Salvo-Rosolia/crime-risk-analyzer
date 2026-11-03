"""CLI of the evaluation foundation (#34).

Subcommands: capture/run/aggregate/compare/city-agnostic/gold-sample/gold-report.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import subprocess
from pathlib import Path

from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.eval.schema import ExperimentConfig
from crime_risk_analyzer.llm.client import LLMClient, build_llm_client


def load_config(path: Path) -> ExperimentConfig:
    """Load an ExperimentConfig from a JSON file."""
    return ExperimentConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))


def code_commit() -> str:
    """git rev-parse HEAD (empty if not available)."""
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
    """sha256 of the configured ontology file (empty if not found)."""
    settings = get_settings()
    path = Path(settings.ontology_path)
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_llm_eval_client(config: ExperimentConfig) -> LLMClient:
    """LLM client with temperature=0 for determinism in the eval pipeline.

    Honours ``config.model`` as provider override, so the ``run_id`` reports
    the provider actually used (fix I1). Call only when
    ``config.mode != 'baseline'`` (fix T9): baseline does not use the LLM.
    """
    return build_llm_client(get_settings(), provider=config.model).with_temperature(
        0.0, 0
    )


def _seconds(text: str) -> float:
    """Seconds of ``--pausa``: finite, non-negative number (#357).

    ``float`` alone accepts ``nan`` (which would silently switch the pause off) and
    ``inf`` (which would block the run after the first case): here they come out
    as a usage error, before loading ontology and client.
    """
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"non e' un numero: {text!r}") from exc
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError(
            f"deve essere un numero finito >= 0, ricevuto {text!r}"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    """Parser for all the evaluation subcommands."""
    parser = argparse.ArgumentParser(prog="crime_risk_analyzer.eval")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("capture", "run"):
        p = sub.add_parser(name)
        p.add_argument("--config", required=True)
        p.add_argument("--results", default="results")
        if name == "capture":
            # Idempotent by default (skip-if-exists, #110 M2); --force re-captures.
            p.add_argument(
                "--force",
                action="store_true",
                help="ri-cattura anche se lo snapshot (citta, zona) esiste già",
            )
        if name == "run":
            p.add_argument(
                "--repeat",
                type=int,
                default=1,
                help="K ripetizioni per stimare la varianza (#157); default 1",
            )
            p.add_argument(
                "--pausa",
                type=_seconds,
                default=0.0,
                help=(
                    "secondi di attesa prima di ogni chiamata al modello, prima "
                    "compresa (#357), per il tetto di token al minuto del provider; "
                    "default 0"
                ),
            )
            p.add_argument(
                "--clean-stale",
                action="store_true",
                help="rimuove le run legacy pre-#157 (senza __rep) prima di eseguire",
            )
    agg = sub.add_parser("aggregate")
    agg.add_argument("--experiment", required=True)
    agg.add_argument("--results", default="results")
    # compare (#32): generic two-arm comparison (A vs B), reused by #33.
    cmp_parser = sub.add_parser("compare")
    cmp_parser.add_argument("--experiment-a", required=True)
    cmp_parser.add_argument("--experiment-b", required=True)
    cmp_parser.add_argument("--label-a", default=None)
    cmp_parser.add_argument("--label-b", default=None)
    cmp_parser.add_argument("--out", default=None, help="stem dei file di output")
    cmp_parser.add_argument("--results", default="results")
    cmp_parser.add_argument(
        "--force", action="store_true", help="sovrascrive i file di output esistenti"
    )
    # compare-repeated (#157): extended report with K repetitions (variance) + winner.
    rep_parser = sub.add_parser("compare-repeated")
    rep_parser.add_argument("--experiment-a", required=True)
    rep_parser.add_argument("--experiment-b", required=True)
    rep_parser.add_argument("--label-a", default=None)
    rep_parser.add_argument("--label-b", default=None)
    rep_parser.add_argument("--out", default=None, help="stem dei file di output")
    rep_parser.add_argument("--results", default="results")
    rep_parser.add_argument(
        "--force", action="store_true", help="sovrascrive i file di output esistenti"
    )
    ca_parser = sub.add_parser("city-agnostic")
    ca_parser.add_argument("phase", choices=["capture", "report"])
    ca_parser.add_argument("--results", default="results")
    # Per-risk gold annotation (#152): two phases, two verbs.
    gold_sample = sub.add_parser("gold-sample")
    gold_sample.add_argument("--results", default="results")
    gold_sample.add_argument("--experiment", default=None)
    # choices constrained: the mechanism is defined on the [ONTOLOGIA] block of the
    # product arm, so a typo (or --mode baseline) would silently produce an empty
    # or meaningless worksheet instead of an error.
    gold_sample.add_argument("--mode", default="analyze", choices=["analyze"])
    gold_sample.add_argument(
        "--force",
        action="store_true",
        help="sovrascrive il foglio esistente (perde le annotazioni manuali)",
    )
    gold_report = sub.add_parser("gold-report")
    gold_report.add_argument("--results", default="results")
    gold_report.add_argument("--worksheet", default=None)
    return parser
