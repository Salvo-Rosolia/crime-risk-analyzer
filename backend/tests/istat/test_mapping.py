"""Hazard -> ISTAT item table (#345, spec 4.2): coverage and pinned counts."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import crime_risk_analyzer.i18n.terminus_labels as _labels
from crime_risk_analyzer.istat.catalog import BREAK_ITEMS_2016, CATALOG
from crime_risk_analyzer.istat.mapping import HAZARD_MAPPING


def _ontology_hazard() -> set[str]:
    data = json.loads(
        (Path(_labels.__file__).parent / "terminus_labels.json").read_text(
            encoding="utf-8"
        )
    )
    return {r["identifier"] for r in data if r["category"] == "hazard"}


def test_every_ontology_hazard_has_a_row() -> None:
    assert set(HAZARD_MAPPING) == _ontology_hazard()
    assert len(HAZARD_MAPPING) == 155


def test_pinned_count_forces_a_review() -> None:
    """Counts of the D3 table: a change of item or match moves them.
    The hazards per item also catch a move between items with the same
    match, which would leave the totals unchanged."""
    mapped_items = [m for m in HAZARD_MAPPING.values() if m.voce_istat]
    assert len(mapped_items) == 100
    assert Counter(m.corrispondenza for m in mapped_items) == Counter(
        {"piu_larga": 89, "esatta": 8, "piu_stretta": 3}
    )
    assert len({m.voce_istat for m in mapped_items}) == 18
    assert Counter(m.voce_istat for m in mapped_items) == Counter(
        {
            "ARSON": 1,
            "ARTTHEF": 2,
            "ATTACK": 2,
            "BAGTHEF": 1,
            "BANKROB": 1,
            "CARTHEF": 1,
            "CULPINJU": 2,
            "CYBERCRIM": 3,
            "DAMAGE": 45,
            "DAMARS": 1,
            "FOREARS": 1,
            "KIDNAPP": 1,
            "POSTROB": 1,
            "ROBBER": 4,
            "SHOPROB": 3,
            "SHOPTHEF": 1,
            "STREETROB": 2,
            "THEFT": 28,
        }
    )


def test_every_item_exists_in_the_dataset_and_is_not_the_total() -> None:
    items = {m.voce_istat for m in HAZARD_MAPPING.values() if m.voce_istat}
    assert items <= set(CATALOG)  # the 56 items are pinned in test_catalog
    assert "TOT" not in items  # D10: the total is only a frame


def test_item_and_match_go_together() -> None:
    for hazard, m in HAZARD_MAPPING.items():
        assert (m.voce_istat is None) == (m.corrispondenza is None), hazard


def test_review_fixes_are_in_the_table() -> None:
    assert HAZARD_MAPPING["Vehicle_Theft"].voce_istat == "CARTHEF"
    assert HAZARD_MAPPING["Vehicle_Theft"].corrispondenza == "piu_stretta"
    for hazard in ("Vandalism", "Property_damage"):
        assert HAZARD_MAPPING[hazard].voce_istat == "DAMAGE"
        assert HAZARD_MAPPING[hazard].corrispondenza == "piu_stretta"
    for hazard in (
        "Crime_explosion",
        "Counterfeiting_of_foodstuffs",
        "Spectator_with_counterfeit_ticket",
        "Traveller_with_counterfeit_ticket",
        "Drone_strike",
    ):
        assert HAZARD_MAPPING[hazard].voce_istat is None, hazard
    assert HAZARD_MAPPING["Traveler_robbery"].voce_istat == "STREETROB"


def test_break_2016_consistent_per_item() -> None:
    by_item: dict[str, set[bool]] = {}
    for m in HAZARD_MAPPING.values():
        if m.voce_istat:
            by_item.setdefault(m.voce_istat, set()).add(m.rottura_2016)
    assert all(len(flag) == 1 for flag in by_item.values())
    used_in_break = {v for v in by_item if v in BREAK_ITEMS_2016}
    assert used_in_break == {"DAMAGE"}


def test_robberies_in_places_separate_from_shops() -> None:
    """D3, review #353: in the SDI (Ministry of the Interior, Rapporto intersettoriale
    sulla criminalita' predatoria 2024) pharmacies and public premises are place
    categories SEPARATE from shops, and for tobacconists the containment in
    SHOPROB is not proven: these robberies go on the robbery total, not on
    SHOPROB."""
    for hazard in (
        "Pharmacy_robbery",
        "Robbery_in_the_cinema",
        "Tobacconist's_shop_robbery",
    ):
        assert HAZARD_MAPPING[hazard].voce_istat == "ROBBER", hazard
        assert HAZARD_MAPPING[hazard].corrispondenza == "piu_larga", hazard
        assert "SDI" in HAZARD_MAPPING[hazard].nota, hazard
    for hazard in (
        "Store_robbery",
        "Robbery_at_the_jewelry_store",
        "Robbery_at_the_mall",
    ):
        assert HAZARD_MAPPING[hazard].voce_istat == "SHOPROB", hazard
    by_item = Counter(m.voce_istat for m in HAZARD_MAPPING.values() if m.voce_istat)
    assert by_item["SHOPROB"] == 3
    assert by_item["ROBBER"] == 4
    assert by_item["SHOPTHEF"] == 1  # Jewelry_theft: jeweller's = shop
