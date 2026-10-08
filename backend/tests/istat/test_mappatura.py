"""Tabella hazard -> voce ISTAT (#345, spec 4.2): copertura e conteggi fissati."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import crime_risk_analyzer.i18n.terminus_labels as _labels
from crime_risk_analyzer.istat.catalogo import CATALOGO, VOCI_ROTTURA_2016
from crime_risk_analyzer.istat.mappatura import MAPPATURA


def _hazard_dell_ontologia() -> set[str]:
    dati = json.loads(
        (Path(_labels.__file__).parent / "terminus_labels.json").read_text(
            encoding="utf-8"
        )
    )
    return {r["identifier"] for r in dati if r["category"] == "hazard"}


def test_ogni_hazard_dell_ontologia_ha_una_riga() -> None:
    assert set(MAPPATURA) == _hazard_dell_ontologia()
    assert len(MAPPATURA) == 155


def test_conteggio_fissato_forza_una_revisione() -> None:
    """Conteggi della tabella D3: un cambio di voce o di corrispondenza li sposta.
    Gli hazard per voce colgono anche lo spostamento fra voci con la stessa
    corrispondenza, che lascerebbe invariati i totali."""
    mappati = [m for m in MAPPATURA.values() if m.voce_istat]
    assert len(mappati) == 100
    assert Counter(m.corrispondenza for m in mappati) == Counter(
        {"piu_larga": 89, "esatta": 8, "piu_stretta": 3}
    )
    assert len({m.voce_istat for m in mappati}) == 18
    assert Counter(m.voce_istat for m in mappati) == Counter(
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


def test_ogni_voce_esiste_nel_dataset_e_non_e_il_totale() -> None:
    voci = {m.voce_istat for m in MAPPATURA.values() if m.voce_istat}
    assert voci <= set(CATALOGO)  # le 56 voci sono fissate in test_catalogo
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
    usate_in_rottura = {v for v in per_voce if v in VOCI_ROTTURA_2016}
    assert usate_in_rottura == {"DAMAGE"}


def test_rapine_in_luoghi_separati_dagli_esercizi_commerciali() -> None:
    """D3, review #353: nello SDI (Ministero dell'Interno, Rapporto intersettoriale
    sulla criminalita' predatoria 2024) farmacie e locali ed esercizi pubblici sono
    categorie di luogo SEPARATE dagli esercizi commerciali, e per le tabaccherie
    il contenimento in SHOPROB non e' provato: queste rapine vanno sul totale
    rapine, non su SHOPROB."""
    for hazard in (
        "Pharmacy_robbery",
        "Robbery_in_the_cinema",
        "Tobacconist's_shop_robbery",
    ):
        assert MAPPATURA[hazard].voce_istat == "ROBBER", hazard
        assert MAPPATURA[hazard].corrispondenza == "piu_larga", hazard
        assert "SDI" in MAPPATURA[hazard].nota, hazard
    for hazard in (
        "Store_robbery",
        "Robbery_at_the_jewelry_store",
        "Robbery_at_the_mall",
    ):
        assert MAPPATURA[hazard].voce_istat == "SHOPROB", hazard
    per_voce = Counter(m.voce_istat for m in MAPPATURA.values() if m.voce_istat)
    assert per_voce["SHOPROB"] == 3
    assert per_voce["ROBBER"] == 4
    assert (
        per_voce["SHOPTHEF"] == 1
    )  # Jewelry_theft: gioielleria = esercizio commerciale
