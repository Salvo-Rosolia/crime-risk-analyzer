"""Catalog of the 56 ISTAT 73_67 items (#353): completeness, hierarchy, use, reasons."""

from __future__ import annotations

import json
from pathlib import Path

import crime_risk_analyzer.istat as _package
from crime_risk_analyzer.istat.catalog import (
    BREAK_ITEMS_2016,
    CATALOG,
    hazards_by_item,
    is_used,
)
from crime_risk_analyzer.istat.data import TOTAL_ITEM
from crime_risk_analyzer.istat.mapping import HAZARD_MAPPING

#: TYPE_CRIME codes available in 73_67 (CL_REATI_PS v1.0, extracted via SDMX
#: on 2026-10-08), total included. Pinned here: one item more or less in the
#: catalog makes the test fail.
_CODES = frozenset(
    {
        "MASSMURD",
        "INTENHOM",
        "ROBBHOM",
        "MAFIAHOM",
        "TERRORHOM",
        "ATTEMPHOM",
        "INFANTHOM",
        "MANSHOM",
        "UNINTHOM",
        "ROADHOM",
        "BLOWS",
        "CULPINJU",
        "MENACE",
        "KIDNAPP",
        "OFFENCE",
        "RAPE",
        "RAPEUN18",
        "CORRUPUN18",
        "PROSTI",
        "PORNO",
        "THEFT",
        "BAGTHEF",
        "PICKTHEF",
        "BURGTHEF",
        "SHOPTHEF",
        "VEHITHEF",
        "ARTTHEF",
        "TRUCKTHEF",
        "MOPETHEF",
        "MOTORTHEF",
        "CARTHEF",
        "ROBBER",
        "HOUSEROB",
        "BANKROB",
        "POSTROB",
        "SHOPROB",
        "STREETROB",
        "EXTORT",
        "SWINCYB",
        "CYBERCRIM",
        "COUNTER",
        "INTPROP",
        "RECEIV",
        "MONEYLAU",
        "USURY",
        "DAMAGE",
        "ARSON",
        "FOREARS",
        "DAMARS",
        "DRUG",
        "ATTACK",
        "CRIMASS",
        "MAFIASS",
        "SMUGGL",
        "OTHCRIM",
        "TOT",
    }
)


def test_the_catalog_has_exactly_the_56_items_of_the_dataset() -> None:
    assert len(_CODES) == 56
    assert set(CATALOG) == _CODES
    assert all(code == item.codice for code, item in CATALOG.items())


def test_every_item_has_a_label() -> None:
    assert all(item.etichetta.strip() for item in CATALOG.values())


def test_every_item_of_the_mapping_is_in_the_catalog() -> None:
    items = {m.voce_istat for m in HAZARD_MAPPING.values() if m.voce_istat}
    assert items <= set(CATALOG)


def test_the_use_is_derived_from_the_mapping() -> None:
    by_item = hazards_by_item()
    for hazard, m in HAZARD_MAPPING.items():
        if m.voce_istat:
            assert hazard in by_item[m.voce_istat], hazard
    assert all(by_item[code] for code in by_item)
    assert set(by_item) <= set(CATALOG)
    assert {code for code in CATALOG if is_used(code)} == set(by_item)
    # Same number of distinct items pinned in test_mapping (D3).
    assert len(by_item) == 18


def test_used_items_have_neither_status_nor_reason() -> None:
    for code, item in CATALOG.items():
        if is_used(code):
            assert item.stato is None, code
            assert item.motivo == "", code


def test_every_unused_item_has_status_and_reason() -> None:
    for code, item in CATALOG.items():
        if is_used(code) or code == TOTAL_ITEM:
            continue
        assert item.stato in ("usabile", "esclusa"), code
        assert item.motivo.strip(), code


def test_the_total_is_the_frame() -> None:
    """D10: the total only enters as the frame of the place, never linked to a risk."""
    total = CATALOG[TOTAL_ITEM]
    assert not is_used(TOTAL_ITEM)
    assert total.stato == "cornice"
    assert total.motivo.strip()
    assert [c for c, v in CATALOG.items() if v.stato == "cornice"] == [TOTAL_ITEM]


def _children(parent: str) -> set[str]:
    return {c for c, v in CATALOG.items() if v.madre == parent}


def test_codelist_hierarchy() -> None:
    assert _children("THEFT") == {
        "BAGTHEF",
        "PICKTHEF",
        "BURGTHEF",
        "SHOPTHEF",
        "VEHITHEF",
        "ARTTHEF",
        "TRUCKTHEF",
        "MOPETHEF",
        "MOTORTHEF",
        "CARTHEF",
    }
    assert _children("ROBBER") == {
        "HOUSEROB",
        "BANKROB",
        "POSTROB",
        "SHOPROB",
        "STREETROB",
    }
    assert _children("INTENHOM") == {"ROBBHOM", "MAFIAHOM", "TERRORHOM"}
    assert _children("UNINTHOM") == {"ROADHOM"}
    assert _children("ARSON") == {"FOREARS"}
    assert CATALOG["DAMARS"].madre is None  # root, not a child of DAMAGE
    assert CATALOG["DAMAGE"].madre is None


def test_the_parents_are_roots_of_the_catalog() -> None:
    """One-level hierarchy: every parent exists and is itself a root."""
    for code, item in CATALOG.items():
        if item.madre is not None:
            assert item.madre in CATALOG, code
            assert CATALOG[item.madre].madre is None, code


def test_place_related_items() -> None:
    """Only the sub-items of thefts and robberies that indicate a place (spec §2-§3)."""
    assert {c for c, v in CATALOG.items() if v.legata_al_luogo} == {
        "BURGTHEF",
        "SHOPTHEF",
        "VEHITHEF",
        "HOUSEROB",
        "BANKROB",
        "POSTROB",
        "SHOPROB",
        "STREETROB",
    }
    assert all(
        CATALOG[c].madre in ("THEFT", "ROBBER")
        for c, v in CATALOG.items()
        if v.legata_al_luogo
    )


def test_the_unused_place_subitems_say_why() -> None:
    for code in ("BURGTHEF", "VEHITHEF", "HOUSEROB"):
        assert not is_used(code), code
        assert CATALOG[code].stato == "esclusa", code


def test_partial_matches_are_excluded() -> None:
    """Spec §7: no partial match for frauds and counterfeiting."""
    for code in ("SWINCYB", "COUNTER"):
        assert CATALOG[code].stato == "esclusa", code
        assert "TERMINUS" in CATALOG[code].motivo, code


def test_the_labels_match_the_data_file() -> None:
    data = json.loads(
        (Path(_package.__file__).parent / "delitti.json").read_text(encoding="utf-8")
    )
    items: dict[str, str] = data["voci"]
    assert items  # the comparison is not vacuous
    for code, label_text in items.items():
        assert CATALOG[code].etichetta == label_text, code


def test_break_2016_from_the_catalog() -> None:
    """Among the risk items only damage (as on main 35acc46); in
    addition the frame total (#353) and two items never shown."""
    assert BREAK_ITEMS_2016 == frozenset({"DAMAGE", "OFFENCE", "OTHCRIM", "TOT"})
    assert BREAK_ITEMS_2016 == {c for c, v in CATALOG.items() if v.rottura_2016}
    assert {c for c in BREAK_ITEMS_2016 if is_used(c)} == {"DAMAGE"}
    assert TOTAL_ITEM in BREAK_ITEMS_2016


def test_the_mapping_break_matches_the_catalog_one() -> None:
    for hazard, m in HAZARD_MAPPING.items():
        if m.voce_istat:
            assert m.rottura_2016 is CATALOG[m.voce_istat].rottura_2016, hazard
