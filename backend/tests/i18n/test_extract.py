from __future__ import annotations

from pathlib import Path

from rdflib import Graph

from crime_risk_analyzer.i18n import extract

_FRAGMENT = Path(__file__).parent.parent / "fixtures" / "terminus_labels_fragment.ttl"


def _graph() -> Graph:
    g = Graph()
    g.parse(_FRAGMENT, format="turtle")
    return g


def test_extract_includes_seed_poi() -> None:
    records = extract.extract_records(_graph(), ["Bank"])
    by_id = {r["identifier"]: r for r in records}
    assert by_id["Bank"]["category"] == "poi"
    assert by_id["Bank"]["label_en"] == "Bank"
    assert by_id["Bank"]["label_it"] == ""


def test_extract_follows_hazard_restriction_and_fixes_typo() -> None:
    records = extract.extract_records(_graph(), ["Bank"])
    by_id = {r["identifier"]: r for r in records}
    # identifier reale col refuso preservato; label_en corretta
    assert by_id["Brank_branch"]["category"] == "hazard"
    assert by_id["Brank_branch"]["label_en"] == "Branch robbery"
    assert by_id["Brank_branch"]["label_it"] == ""


def test_extract_follows_vulnerability_restriction() -> None:
    records = extract.extract_records(_graph(), ["Bank"])
    by_id = {r["identifier"]: r for r in records}
    assert by_id["Unmanned_access"]["category"] == "vulnerability"


def test_extract_skips_seeds_absent_from_graph() -> None:
    records = extract.extract_records(_graph(), ["Bank", "Hospital"])
    ids = {r["identifier"] for r in records}
    assert "Hospital" not in ids


def test_merge_preserves_existing_it() -> None:
    new = [
        {
            "identifier": "Brank_branch",
            "label_en": "Branch robbery",
            "label_it": "",
            "category": "hazard",
        }
    ]
    existing = [
        {
            "identifier": "Brank_branch",
            "label_en": "Branch robbery",
            "label_it": "Rapina in filiale",
            "category": "hazard",
        }
    ]
    merged = extract.merge_preserving_it(new, existing)  # type: ignore[arg-type]
    assert merged[0]["label_it"] == "Rapina in filiale"
