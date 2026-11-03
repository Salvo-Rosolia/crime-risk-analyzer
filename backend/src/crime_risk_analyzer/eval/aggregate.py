"""Aggregation of RunRecords into tables for the thesis (#34)."""

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
    "quality_vacuous",
    "latency_ms",
    "cost_usd",
]


def _vacuous_cell(quality_vacuous: bool | None) -> str:
    """Vacuity-marker cell (#240): empty string when not available.

    A pre-#240 record has no ``quality_vacuous`` (``None``): leaving the cell
    empty, instead of printing "false", avoids making a value that simply was
    not recorded read as "not vacuous".
    """
    if quality_vacuous is None:
        return ""
    return "true" if quality_vacuous else "false"


def load_runs(results_dir: Path, experiment: str | None = None) -> list[RunRecord]:
    """Load RunRecords from results/runs/, optionally filtered by experiment."""
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
        _vacuous_cell(rec.metrics.quality_vacuous),
        str(rec.metrics.latency_ms),
        f"{rec.metrics.cost_usd:.6f}",
    ]


def to_csv(records: list[RunRecord]) -> str:
    """Serialize the records to CSV (header + one row per run)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_COLUMNS)
    for rec in records:
        writer.writerow(_row(rec))
    return buf.getvalue()


def to_markdown(records: list[RunRecord]) -> str:
    """Serialize the records to a markdown table."""
    lines = [
        "| " + " | ".join(_COLUMNS) + " |",
        "| " + " | ".join("---" for _ in _COLUMNS) + " |",
    ]
    for rec in records:
        lines.append("| " + " | ".join(_row(rec)) + " |")
    return "\n".join(lines) + "\n"


def write_tables(results_dir: Path, experiment: str) -> tuple[Path, Path]:
    """Write results/<experiment>.csv and .md from the experiment's records."""
    records = load_runs(results_dir, experiment=experiment)
    csv_path = results_dir / f"{experiment}.csv"
    md_path = results_dir / f"{experiment}.md"
    # newline="": to_csv() already emits \r\n via csv.writer; without this,
    # write_text's text mode would re-translate \n->\r\n on Windows (spurious rows).
    # See the same fix in city_agnostic_report.build_report (#31/#103).
    csv_path.write_text(to_csv(records), encoding="utf-8", newline="")
    md_path.write_text(to_markdown(records), encoding="utf-8")
    return csv_path, md_path
