"""Deterministic report of the C1 validation (#31): snapshots -> tables (#34)."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import cast

from rdflib import Graph

from crime_risk_analyzer.eval.city_agnostic import (
    CaptureOutcome,
    CityAgnosticRecord,
    build_record,
    capture_path,
)
from crime_risk_analyzer.eval.snapshots import describe_config_divergence

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
    """Load all the capture outcomes from results/city_agnostic/snapshots/."""
    # Derive the snapshots folder from the shared path builder, with a dummy city
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
    # 3 initial columns (citta, zona, status) + N blank + 1 final (pass_all)
    # == len(_COLUMNS)
    n_blank = len(_COLUMNS) - 4
    return [outcome.citta, outcome.zona, "failed", *([""] * n_blank), "False"]


def _provenance_warnings(outcomes: list[CaptureOutcome]) -> list[str]:
    """Warnings on the provenance of the outcomes (#374); never raises.

    Three cases: provenance absent (pre-#374 outcomes), configuration diverging from
    that of the current code, different provenances among themselves in the roster (a
    partial re-capture that mixes outcomes produced with different configurations).
    The provenance is the configuration of the CODE that wrote the file, not
    of the query: an absence of warnings does not prove that the data are homogeneous
    on the OSM side.
    """
    warnings: list[str] = []
    signatures: set[str] = set()
    for o in outcomes:
        if o.provenienza is None:
            warnings.append(f"{o.citta}: esito senza provenienza (pre-#374)")
            signatures.add("assente")
            continue
        signatures.add(
            json.dumps(o.provenienza.configurazione_canonica, sort_keys=True)
        )
        divergence = describe_config_divergence(o.provenienza.configurazione_canonica)
        if divergence is not None:
            warnings.append(f"{o.citta}: {divergence}")
    if len(signatures) > 1:
        warnings.append(
            "provenienze miste: gli esiti del roster non sono stati scritti con la "
            "stessa configurazione (ricattura parziale?)"
        )
    return warnings


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
    provenance = cast("dict[str, str | None]", summary["provenienza"])
    lines.append("")
    lines.append("Provenienza (istante di scrittura dell'esito, per città):")
    for citta, instant in provenance.items():
        lines.append(f"- {citta}: {instant or 'assente'}")
    for warning in cast("list[str]", summary["avvisi"]):
        lines.append("")
        lines.append(f"AVVISO: {warning}")
    return "\n".join(lines) + "\n"


def build_report(
    results_dir: Path, graph: Graph, ontology_hash: str
) -> tuple[Path, Path, Path]:
    """Aggregate the snapshots into records.json + report.csv + report.md."""
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
        "provenienza": {
            o.citta: o.provenienza.catturato_il if o.provenienza else None
            for o in outcomes
        },
        "avvisi": _provenance_warnings(outcomes),
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
    csv_path.write_text(_to_csv(rows), encoding="utf-8", newline="")
    md_path = out_dir / "report.md"
    md_path.write_text(_to_markdown(rows, summary), encoding="utf-8")
    return records_path, csv_path, md_path
