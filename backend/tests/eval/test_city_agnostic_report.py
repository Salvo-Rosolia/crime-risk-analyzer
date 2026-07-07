from __future__ import annotations

import csv
import json
from pathlib import Path

from rdflib import OWL, RDF, Graph

from crime_risk_analyzer.eval import city_agnostic as ca
from crime_risk_analyzer.eval.city_agnostic_report import (
    _COLUMNS,  # pyright: ignore[reportPrivateUsage]
    build_report,
    load_outcomes,
)
from crime_risk_analyzer.eval.geometry import CityBoundary
from crime_risk_analyzer.ontology_namespaces import TERMINUS
from crime_risk_analyzer.overpass_client import Poi

_BOUNDARY = CityBoundary(
    polygons=[[[(11.0, 40.0), (13.0, 40.0), (13.0, 42.0), (11.0, 42.0)]]]
)


def _poi(name: str, terminus_class: str) -> Poi:
    return {
        "id": name,
        "name": name,
        "lat": 41.0,
        "lon": 12.0,
        "osm_tags": "amenity=bank",
        "terminus_class": terminus_class,
        "citta": "Roma",
    }


def _graph() -> Graph:
    g = Graph()
    g.add((TERMINUS["Bank"], RDF.type, OWL.Class))
    return g


def _seed_snapshots(results_dir: Path) -> None:
    ok = ca.CaptureOutcome(
        status="ok",
        citta="Roma",
        zona="Colosseo",
        capture=ca.CityCapture(
            citta="Roma",
            zona="Colosseo",
            lat=41.0,
            lon=12.0,
            bbox=(41.0, 12.0, 41.5, 12.5),
            switch_ms=800,
            pois=[_poi("a", "Bank")],
            boundary=_BOUNDARY,
        ),
    )
    failed = ca.CaptureOutcome(
        status="failed",
        citta="Napoli",
        zona="Garibaldi",
        error_type="ZoneNotFoundError",
        error="zona non trovata",
    )
    ca.save_outcome(ca.capture_path(results_dir, "Roma"), ok)
    ca.save_outcome(ca.capture_path(results_dir, "Napoli"), failed)


def test_load_outcomes_reads_all(tmp_path: Path) -> None:
    _seed_snapshots(tmp_path)
    outcomes = load_outcomes(tmp_path)
    assert {o.citta for o in outcomes} == {"Roma", "Napoli"}


def test_build_report_writes_tables_and_records(tmp_path: Path) -> None:
    _seed_snapshots(tmp_path)
    records_path, csv_path, md_path = build_report(tmp_path, _graph(), "hashZ")

    data = json.loads(records_path.read_text(encoding="utf-8"))
    assert data["summary"] == {
        "n_citta": 2,
        "n_pass_all": 1,
        "n_failed": 1,
        "ontology_hash": "hashZ",
    }
    assert len(data["records"]) == 1
    assert data["records"][0]["citta"] == "Roma"
    assert len(data["failures"]) == 1
    assert data["failures"][0]["error_type"] == "ZoneNotFoundError"

    csv_text = csv_path.read_text(encoding="utf-8")
    assert "citta,zona,status" in csv_text.replace(" ", "")
    assert "Roma" in csv_text and "Napoli" in csv_text
    assert "failed" in csv_text

    md_text = md_path.read_text(encoding="utf-8")
    assert "| citta | zona | status |" in md_text
    assert "città: 2" in md_text


def test_build_report_csv_has_no_double_crlf(tmp_path: Path) -> None:
    _seed_snapshots(tmp_path)
    _records_path, csv_path, _md_path = build_report(tmp_path, _graph(), "hashZ")

    content = csv_path.read_bytes()
    assert b"\r\r\n" not in content


def test_build_report_csv_rows_are_well_formed(tmp_path: Path) -> None:
    _seed_snapshots(tmp_path)
    _records_path, csv_path, _md_path = build_report(tmp_path, _graph(), "hashZ")

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    assert len(rows) == 3  # header + Roma (ok) + Napoli (failed)
    n_columns = len(_COLUMNS)
    for row in rows:
        assert len(row) == n_columns
