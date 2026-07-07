from __future__ import annotations

import json
from pathlib import Path

import pytest

from crime_risk_analyzer.i18n import terminus_labels as tl


@pytest.fixture()
def _fake_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:  # pyright: ignore[reportUnusedFunction]
    data = [
        {
            "identifier": "Bank_robbery",
            "label_en": "Bank robbery",
            "label_it": "Rapina in banca",
            "category": "hazard",
        },
        {
            "identifier": "Empty_it",
            "label_en": "Empty it",
            "label_it": "",
            "category": "hazard",
        },
    ]
    path = tmp_path / "terminus_labels.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(tl, "_DATA_PATH", path)
    tl._records.cache_clear()  # pyright: ignore[reportPrivateUsage]
    return path


def test_label_it_returns_curated_value(_fake_data: Path) -> None:
    assert tl.label_it("Bank_robbery") == "Rapina in banca"


def test_label_it_falls_back_to_label_en_when_it_empty(_fake_data: Path) -> None:
    assert tl.label_it("Empty_it") == "Empty it"


def test_label_it_falls_back_to_normalized_identifier_when_absent(
    _fake_data: Path,
) -> None:
    assert tl.label_it("Unknown_class") == "Unknown class"


def test_label_en_returns_corrected_value(_fake_data: Path) -> None:
    assert tl.label_en("Bank_robbery") == "Bank robbery"


def test_label_en_falls_back_to_normalized_identifier(_fake_data: Path) -> None:
    assert tl.label_en("Unknown_class") == "Unknown class"


def test_controlled_vocab_for_is_deduped_and_stable(_fake_data: Path) -> None:
    vocab = tl.controlled_vocab_for(["Bank_robbery", "Bank_robbery", "Empty_it"])
    assert vocab == ["Rapina in banca", "Empty it"]


def test_missing_data_file_yields_empty_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tl, "_DATA_PATH", tmp_path / "does_not_exist.json")
    tl._records.cache_clear()  # pyright: ignore[reportPrivateUsage]
    assert tl.label_it("Whatever_class") == "Whatever class"
