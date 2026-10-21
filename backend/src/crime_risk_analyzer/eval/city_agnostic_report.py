"""Report deterministico della validazione C1 (#31): snapshot → tabelle (#34-style)."""

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
from crime_risk_analyzer.eval.snapshots import describe_configurazione_divergente

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
    # Deriva la cartella snapshots dal path builder condiviso, con una città fittizia
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
    # 3 colonne iniziali (citta, zona, status) + N vuote + 1 finale (pass_all)
    # == len(_COLUMNS)
    n_blank = len(_COLUMNS) - 4
    return [outcome.citta, outcome.zona, "failed", *([""] * n_blank), "False"]


def _avvisi_provenienza(outcomes: list[CaptureOutcome]) -> list[str]:
    """Avvisi sulla provenienza degli esiti (#374); mai solleva.

    Tre casi: provenienza assente (esiti pre-#374), configurazione divergente da
    quella del codice corrente, provenienze diverse fra loro nel roster (una
    ricattura parziale che mescola esiti prodotti con configurazioni diverse).
    La provenienza è la configurazione del CODICE che ha scritto il file, non
    della query: un'assenza di avvisi non prova che i dati siano omogenei sul lato
    OSM.
    """
    avvisi: list[str] = []
    firme: set[str] = set()
    for o in outcomes:
        if o.provenienza is None:
            avvisi.append(f"{o.citta}: esito senza provenienza (pre-#374)")
            firme.add("assente")
            continue
        firme.add(json.dumps(o.provenienza.configurazione_canonica, sort_keys=True))
        divergenza = describe_configurazione_divergente(
            o.provenienza.configurazione_canonica
        )
        if divergenza is not None:
            avvisi.append(f"{o.citta}: {divergenza}")
    if len(firme) > 1:
        avvisi.append(
            "provenienze miste: gli esiti del roster non sono stati scritti con la "
            "stessa configurazione (ricattura parziale?)"
        )
    return avvisi


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
    provenienza = cast("dict[str, str | None]", summary["provenienza"])
    lines.append("")
    lines.append("Provenienza (istante di scrittura dell'esito, per città):")
    for citta, istante in provenienza.items():
        lines.append(f"- {citta}: {istante or 'assente'}")
    for avviso in cast("list[str]", summary["avvisi"]):
        lines.append("")
        lines.append(f"AVVISO: {avviso}")
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
        "provenienza": {
            o.citta: o.provenienza.catturato_il if o.provenienza else None
            for o in outcomes
        },
        "avvisi": _avvisi_provenienza(outcomes),
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
