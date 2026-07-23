from __future__ import annotations

import pytest

from crime_risk_analyzer import orchestrator
from crime_risk_analyzer.orchestrator import PoiOut
from crime_risk_analyzer.rag import generation
from crime_risk_analyzer.rag.generation import RiskItem


@pytest.fixture(autouse=True)
def _stub_labels(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    it: dict[str, str] = {"Bank_robbery": "Rapina in banca", "Bank": "Banca"}
    en: dict[str, str] = {"Bank_robbery": "Bank robbery", "Bank": "Bank"}

    def _it(k: str) -> str:
        return it.get(k, k)

    def _en(k: str) -> str:
        return en.get(k, k)

    monkeypatch.setattr(generation, "label_it", _it)
    monkeypatch.setattr(generation, "label_en", _en)
    monkeypatch.setattr(orchestrator, "label_it", _it)
    monkeypatch.setattr(orchestrator, "label_en", _en)


def test_risk_item_autofills_it_and_en_labels() -> None:
    item = RiskItem(hazard="Bank_robbery", confidence="verificato", tag="ONTOLOGIA")
    assert item.hazard_label_it == "Rapina in banca"
    assert item.hazard_label_en == "Bank robbery"


def test_risk_item_keeps_explicit_labels() -> None:
    item = RiskItem(
        hazard="Bank_robbery",
        confidence="verificato",
        tag="ONTOLOGIA",
        hazard_label_it="Custom",
        hazard_label_en="Custom EN",
    )
    assert item.hazard_label_it == "Custom"


def test_poi_out_autofills_terminus_labels() -> None:
    poi = PoiOut(
        id="1",
        name="Banca X",
        terminus_class="Bank",
        lat=1.0,
        lon=2.0,
        confidence="verificato",
    )
    assert poi.terminus_label_it == "Banca"
    assert poi.terminus_label_en == "Bank"
