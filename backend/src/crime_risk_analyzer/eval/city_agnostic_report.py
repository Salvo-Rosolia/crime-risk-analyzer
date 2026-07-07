"""Report deterministico della validazione C1 (#31): snapshot → tabelle (#34-style)."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from rdflib import Graph

from crime_risk_analyzer.eval.city_agnostic import (
    CaptureOutcome,
    CityAgnosticRecord,
    build_record,
    capture_path,
)

_COLUMNS = [
    "citta",
    "zona",
    "status",
    "n_poi",
    "coverage_verbatim",
    "pass_verbatim",
    "coverage_derived",
    "pass_derived",
    "pois_in_boundary",
    "pass_boundary",
    "bbox_valid",
    "switch_ms",
    "pass_switch",
    "pass_all",
]


def load_outcomes(results_dir: Path) -> list[CaptureOutcome]:
    """Carica tutti gli esiti di cattura da results/city_agnostic/snapshots/."""
    snapshots_dir = capture_path(results_dir, "x").parent
    outcomes: list[CaptureOutcome] = []
    if not snapshots_dir.exists():
        return outcomes
    for path in sorted(snapshots_dir.glob("*.json")):
        outcomes.append(
            CaptureOutcome.model_validate_json(path.read_text(encoding="utf-8"))
        )
    return outcomes


def _pass_all(rec: CityAgnosticRecord) -> bool:
    return (
        rec.pass_verbatim and rec.pass_derived and rec.pass_switch and rec.pass_boundary
    )


def _ok_row(rec: CityAgnosticRecord) -> list[str]:
    return [
        rec.citta,
        rec.zona,
        "ok",
        str(rec.n_poi),
        f"{rec.coverage_verbatim:.3f}",
        str(rec.pass_verbatim),
        f"{rec.coverage_derived:.3f}",
        str(rec.pass_derived),
        f"{rec.pois_in_boundary:.3f}",
        str(rec.pass_boundary),
        str(rec.bbox_valid),
        str(rec.switch_ms),
        str(rec.pass_switch),
        str(_pass_all(rec)),
    ]


def _failed_row(outcome: CaptureOutcome) -> list[str]:
    return [outcome.citta, outcome.zona, "failed", *([""] * 10), "False"]


def _to_csv(rows: list[list[str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_COLUMNS)
    writer.writerows(rows)
    return buf.getvalue()


def _to_markdown(rows: list[list[str]], summary: dict[str, object]) -> str:
    lines = [
        "| " + " | ".join(_COLUMNS) + " |",
        "| " + " | ".join("---" for _ in _COLUMNS) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append(
        f"città: {summary['n_citta']} · promosse (pass_all): "
        f"{summary['n_pass_all']} · fallite: {summary['n_failed']} · "
        f"ontology_hash: {summary['ontology_hash']}"
    )
    return "\n".join(lines) + "\n"


def build_report(
    results_dir: Path, graph: Graph, ontology_hash: str
) -> tuple[Path, Path, Path]:
    """Aggrega gli snapshot in records.json + report.csv + report.md."""
    outcomes = load_outcomes(results_dir)
    rows: list[list[str]] = []
    records: list[CityAgnosticRecord] = []
    failures: list[dict[str, str]] = []
    for outcome in outcomes:
        if outcome.status == "ok" and outcome.capture is not None:
            rec = build_record(outcome.capture, graph, ontology_hash)
            records.append(rec)
            rows.append(_ok_row(rec))
        else:
            failures.append(
                {
                    "citta": outcome.citta,
                    "zona": outcome.zona,
                    "error_type": outcome.error_type or "",
                    "error": outcome.error or "",
                }
            )
            rows.append(_failed_row(outcome))

    summary: dict[str, object] = {
        "n_citta": len(outcomes),
        "n_pass_all": sum(1 for r in records if _pass_all(r)),
        "n_failed": len(failures),
        "ontology_hash": ontology_hash,
    }

    out_dir = results_dir / "city_agnostic"
    out_dir.mkdir(parents=True, exist_ok=True)
    records_path = out_dir / "records.json"
    records_path.write_text(
        json.dumps(
            {
                "summary": summary,
                "records": [r.model_dump() for r in records],
                "failures": failures,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    csv_path = out_dir / "report.csv"
    csv_path.write_text(_to_csv(rows), encoding="utf-8")
    md_path = out_dir / "report.md"
    md_path.write_text(_to_markdown(rows, summary), encoding="utf-8")
    return records_path, csv_path, md_path
