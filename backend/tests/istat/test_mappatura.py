"""Tabella hazard -> voce ISTAT (#345, spec 4.2): copertura e conteggi fissati."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import crime_risk_analyzer.i18n.terminus_labels as _labels
from crime_risk_analyzer.istat.mappatura import MAPPATURA, VOCI_ROTTURA_2016

#: Le 56 voci del dataset ISTAT 73_67 (codelist CL_REATI_PS, verificata il
#: 2026-10-06), totale compreso.
_VOCI_DATASET = frozenset(
    {
        "OTHCRIM",
        "MAFIASS",
        "CRIMASS",
        "ATTACK",
        "RAPEUN18",
        "SMUGGL",
        "COUNTER",
        "CORRUPUN18",
        "DAMAGE",
        "DAMARS",
        "CYBERCRIM",
        "EXTORT",
        "THEFT",
        "PICKTHEF",
        "BAGTHEF",
        "TRUCKTHEF",
        "CARTHEF",
        "MOPETHEF",
        "MOTORTHEF",
        "ARTTHEF",
        "BURGTHEF",
        "VEHITHEF",
        "SHOPTHEF",
        "ARSON",
        "FOREARS",
        "INFANTHOM",
        "OFFENCE",
        "CULPINJU",
        "MENACE",
        "DRUG",
        "UNINTHOM",
        "ROADHOM",
        "MANSHOM",
        "INTENHOM",
        "ROBBHOM",
        "TERRORHOM",
        "MAFIAHOM",
        "BLOWS",
        "PORNO",
        "ROBBER",
        "HOUSEROB",
        "BANKROB",
        "SHOPROB",
        "STREETROB",
        "POSTROB",
        "RECEIV",
        "MONEYLAU",
        "KIDNAPP",
        "PROSTI",
        "MASSMURD",
        "ATTEMPHOM",
        "TOT",
        "SWINCYB",
        "USURY",
        "INTPROP",
        "RAPE",
    }
)


def _hazard_dell_ontologia() -> set[str]:
    dati = json.loads(
        (Path(_labels.__file__).parent / "terminus_labels.json").read_text(
            encoding="utf-8"
        )
    )
    return {r["identifier"] for r in dati if r["category"] == "hazard"}


def test_ogni_hazard_dell_ontologia_ha_una_riga() -> None:
    assert len(_VOCI_DATASET) == 56
    assert set(MAPPATURA) == _hazard_dell_ontologia()
    assert len(MAPPATURA) == 155


def test_conteggio_fissato_forza_una_revisione() -> None:
    """Cambiare anche una sola riga fa fallire questo test: la tabella e' D3."""
    mappati = [m for m in MAPPATURA.values() if m.voce_istat]
    assert len(mappati) == 100
    assert Counter(m.corrispondenza for m in mappati) == Counter(
        {"piu_larga": 89, "esatta": 8, "piu_stretta": 3}
    )
    assert len({m.voce_istat for m in mappati}) == 18


def test_ogni_voce_esiste_nel_dataset_e_non_e_il_totale() -> None:
    voci = {m.voce_istat for m in MAPPATURA.values() if m.voce_istat}
    assert voci <= _VOCI_DATASET
    assert "TOT" not in voci  # D10: il totale e' solo cornice


def test_voce_e_corrispondenza_vanno_insieme() -> None:
    for hazard, m in MAPPATURA.items():
        assert (m.voce_istat is None) == (m.corrispondenza is None), hazard


def test_correzioni_della_review_sono_nella_tabella() -> None:
    assert MAPPATURA["Vehicle_Theft"].voce_istat == "CARTHEF"
    assert MAPPATURA["Vehicle_Theft"].corrispondenza == "piu_stretta"
    for hazard in ("Vandalism", "Property_damage"):
        assert MAPPATURA[hazard].voce_istat == "DAMAGE"
        assert MAPPATURA[hazard].corrispondenza == "piu_stretta"
    for hazard in (
        "Crime_explosion",
        "Counterfeiting_of_foodstuffs",
        "Spectator_with_counterfeit_ticket",
        "Traveller_with_counterfeit_ticket",
        "Drone_strike",
    ):
        assert MAPPATURA[hazard].voce_istat is None, hazard
    assert MAPPATURA["Traveler_robbery"].voce_istat == "STREETROB"


def test_rottura_2016_coerente_per_voce() -> None:
    per_voce: dict[str, set[bool]] = {}
    for m in MAPPATURA.values():
        if m.voce_istat:
            per_voce.setdefault(m.voce_istat, set()).add(m.rottura_2016)
    assert all(len(flag) == 1 for flag in per_voce.values())
    assert VOCI_ROTTURA_2016 == frozenset({"DAMAGE"})
