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
from crime_risk_analyzer.eval.snapshots import configurazione_canonica_corrente
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


_METRIC_KEYS = ("n_citta", "n_pass_all", "n_failed", "ontology_hash")


def _prov(
    config: dict[str, object] | None = None, istante: str = "2026-10-21T09:30:00+00:00"
) -> ca.EsitoProvenienza:
    return ca.EsitoProvenienza(
        catturato_il=istante,
        configurazione_canonica=(
            dict(configurazione_canonica_corrente()) if config is None else config
        ),
    )


def _seed_with_provenance(
    results_dir: Path,
    roma: ca.EsitoProvenienza | None,
    napoli: ca.EsitoProvenienza | None,
) -> None:
    _seed_snapshots(results_dir)
    for citta, prov in (("Roma", roma), ("Napoli", napoli)):
        path = ca.capture_path(results_dir, citta)
        outcome = ca.load_outcome(path).model_copy(update={"provenienza": prov})
        ca.save_outcome(path, outcome)


def _avvisi(records_path: Path) -> list[str]:
    data = json.loads(records_path.read_text(encoding="utf-8"))
    return data["summary"]["avvisi"]


def test_report_warns_when_provenienza_missing(tmp_path: Path) -> None:
    _seed_snapshots(tmp_path)
    records_path, _csv, md_path = build_report(tmp_path, _graph(), "h")
    avvisi = _avvisi(records_path)
    assert any("Roma" in a and "senza provenienza" in a for a in avvisi)
    assert any("Napoli" in a and "senza provenienza" in a for a in avvisi)
    md = md_path.read_text(encoding="utf-8")
    assert "AVVISO" in md
    assert "- Roma: assente" in md
    assert "- Napoli: assente" in md
    summary = json.loads(records_path.read_text(encoding="utf-8"))["summary"]
    assert summary["provenienza"]["Roma"] is None
    assert summary["provenienza"]["Napoli"] is None


def test_snapshot_committati_hanno_provenienza_e_config_unica() -> None:
    """Guardia sui file veri: gli esiti C1 versionati sono tutti ``ok``, con
    provenienza, e scritti con UNA sola configurazione canonica. Non si confronta
    con la config corrente (ogni modifica ai selettori romperebbe la CI): solo
    l'omogeneità fra file."""
    cartella = Path(__file__).parents[2] / "results" / "city_agnostic" / "snapshots"
    file = sorted(cartella.glob("*.json"))
    assert file, "attesi gli esiti C1 versionati in results/city_agnostic/snapshots/"
    firme: dict[str, str] = {}
    for f in file:
        outcome = ca.load_outcome(f)
        assert outcome.status == "ok", f"esito non ok: {f.name}"
        assert outcome.provenienza is not None, f"senza provenienza: {f.name}"
        firme[f.name] = json.dumps(
            outcome.provenienza.configurazione_canonica, sort_keys=True
        )
    assert len(set(firme.values())) == 1, (
        "configurazioni canoniche miste fra gli snapshot versionati "
        f"({sorted(firme)}): una ricattura parziale va ripetuta per l'INTERO "
        "roster, altrimenti gli esiti non sono confrontabili"
    )


def test_report_warns_when_config_diverges(tmp_path: Path) -> None:
    corrente = dict(configurazione_canonica_corrente())
    vecchia = {**corrente, "tipi_elemento": ["node", "way"]}
    _seed_with_provenance(tmp_path, _prov(vecchia), _prov(vecchia))
    records_path, _csv, md_path = build_report(tmp_path, _graph(), "h")
    avvisi = _avvisi(records_path)
    assert any("Roma" in a and "tipi_elemento" in a for a in avvisi)
    assert "tipi_elemento" in md_path.read_text(encoding="utf-8")


def test_report_warns_when_provenienze_are_mixed(tmp_path: Path) -> None:
    corrente = dict(configurazione_canonica_corrente())
    vecchia = {**corrente, "tipi_elemento": ["node", "way"]}
    _seed_with_provenance(tmp_path, _prov(), _prov(vecchia))
    records_path, _csv, _md = build_report(tmp_path, _graph(), "h")
    assert any("miste" in a for a in _avvisi(records_path))


def test_report_warns_when_some_have_provenienza_and_some_not(tmp_path: Path) -> None:
    _seed_with_provenance(tmp_path, _prov(), None)
    records_path, _csv, _md = build_report(tmp_path, _graph(), "h")
    avvisi = _avvisi(records_path)
    assert any("miste" in a for a in avvisi)
    assert any("Napoli" in a and "senza provenienza" in a for a in avvisi)


def test_report_no_warning_when_all_consistent(tmp_path: Path) -> None:
    _seed_with_provenance(tmp_path, _prov(), _prov(istante="2026-10-21T09:31:00+00:00"))
    records_path, _csv, md_path = build_report(tmp_path, _graph(), "h")
    data = json.loads(records_path.read_text(encoding="utf-8"))
    assert data["summary"]["avvisi"] == []
    assert data["summary"]["provenienza"] == {
        "Napoli": "2026-10-21T09:31:00+00:00",
        "Roma": "2026-10-21T09:30:00+00:00",
    }
    md = md_path.read_text(encoding="utf-8")
    assert "AVVISO" not in md
    assert "2026-10-21T09:30:00+00:00" in md


def test_load_outcomes_reads_all(tmp_path: Path) -> None:
    _seed_snapshots(tmp_path)
    outcomes = load_outcomes(tmp_path)
    assert {o.citta for o in outcomes} == {"Roma", "Napoli"}


def test_build_report_writes_tables_and_records(tmp_path: Path) -> None:
    _seed_snapshots(tmp_path)
    records_path, csv_path, md_path = build_report(tmp_path, _graph(), "hashZ")

    data = json.loads(records_path.read_text(encoding="utf-8"))
    summary = data["summary"]
    assert {k: summary[k] for k in _METRIC_KEYS} == {
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
