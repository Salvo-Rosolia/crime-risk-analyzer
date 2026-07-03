"""Aggregazione dei RunRecord in tabelle per la tesi (#34)."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from crime_risk_analyzer.eval.schema import RunRecord

_COLUMNS = [
    "run_id",
    "citta",
    "zona",
    "mode",
    "model_id",
    "status",
    "grounding",
    "hallucination",
    "latency_ms",
    "cost_usd",
]


def load_runs(results_dir: Path, experiment: str | None = None) -> list[RunRecord]:
    """Carica i RunRecord da results/runs/, opz. filtrati per esperimento."""
    runs_dir = results_dir / "runs"
    records: list[RunRecord] = []
    if not runs_dir.exists():
        return records
    for path in sorted(runs_dir.glob("*.json")):
        rec = RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
        if experiment is None or rec.experiment == experiment:
            records.append(rec)
    return records


def _row(rec: RunRecord) -> list[str]:
    return [
        rec.run_id,
        rec.citta,
        rec.zona,
        rec.mode,
        rec.model_id,
        rec.status.value,
        f"{rec.metrics.grounding:.3f}",
        f"{rec.metrics.hallucination:.3f}",
        str(rec.metrics.latency_ms),
        f"{rec.metrics.cost_usd:.6f}",
    ]


def to_csv(records: list[RunRecord]) -> str:
    """Serializza i record in CSV (header + una riga per run)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_COLUMNS)
    for rec in records:
        writer.writerow(_row(rec))
    return buf.getvalue()


def to_markdown(records: list[RunRecord]) -> str:
    """Serializza i record in tabella markdown."""
    lines = [
        "| " + " | ".join(_COLUMNS) + " |",
        "| " + " | ".join("---" for _ in _COLUMNS) + " |",
    ]
    for rec in records:
        lines.append("| " + " | ".join(_row(rec)) + " |")
    return "\n".join(lines) + "\n"


def write_tables(results_dir: Path, experiment: str) -> tuple[Path, Path]:
    """Scrive results/<experiment>.csv e .md dai record dell'esperimento."""
    records = load_runs(results_dir, experiment=experiment)
    csv_path = results_dir / f"{experiment}.csv"
    md_path = results_dir / f"{experiment}.md"
    csv_path.write_text(to_csv(records), encoding="utf-8")
    md_path.write_text(to_markdown(records), encoding="utf-8")
    return csv_path, md_path
