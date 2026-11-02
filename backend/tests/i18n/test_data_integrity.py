from __future__ import annotations

import json
from pathlib import Path

import crime_risk_analyzer.i18n.terminus_labels as _tl_mod

_ALLOWED = {"poi", "hazard", "critical_event", "vulnerability", "stakeholder"}
_JSON_PATH = Path(_tl_mod.__file__).parent / "terminus_labels.json"


def _data() -> list[dict[str, str]]:
    return json.loads(_JSON_PATH.read_text(encoding="utf-8"))


def test_vocabulary_is_not_empty() -> None:
    assert _data(), "the committed vocabulary must not be empty"


def test_every_record_is_fully_curated() -> None:
    for rec in _data():
        assert rec["identifier"], "missing identifier"
        assert rec["label_en"], f"missing label_en for {rec['identifier']}"
        assert rec["label_it"], f"missing label_it for {rec['identifier']}"
        assert rec["category"] in _ALLOWED, f"invalid category: {rec['category']}"


def test_identifiers_are_unique() -> None:
    ids = [rec["identifier"] for rec in _data()]
    assert len(ids) == len(set(ids)), "duplicate identifiers"
