"""Catalogo delle 56 voci ISTAT 73_67 (#353): completezza, gerarchia, uso, motivi."""

from __future__ import annotations

import json
from pathlib import Path

import crime_risk_analyzer.istat as _pacchetto
from crime_risk_analyzer.istat.catalogo import (
    CATALOGO,
    VOCI_ROTTURA_2016,
    hazard_per_voce,
    usata,
)
from crime_risk_analyzer.istat.dati import VOCE_TOTALE
from crime_risk_analyzer.istat.mappatura import MAPPATURA

#: Codici di TYPE_CRIME disponibili in 73_67 (CL_REATI_PS v1.0, estratti via SDMX
#: il 2026-10-08), totale compreso. Fissati qui: una voce in piu' o in meno nel
#: catalogo fa fallire il test.
_CODICI = frozenset(
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


def test_il_catalogo_ha_esattamente_le_56_voci_del_dataset() -> None:
    assert len(_CODICI) == 56
    assert set(CATALOGO) == _CODICI
    assert all(codice == voce.codice for codice, voce in CATALOGO.items())


def test_ogni_voce_ha_un_etichetta() -> None:
    assert all(voce.etichetta.strip() for voce in CATALOGO.values())


def test_ogni_voce_della_mappatura_e_nel_catalogo() -> None:
    voci = {m.voce_istat for m in MAPPATURA.values() if m.voce_istat}
    assert voci <= set(CATALOGO)


def test_l_uso_e_derivato_dalla_mappatura() -> None:
    per_voce = hazard_per_voce()
    for hazard, m in MAPPATURA.items():
        if m.voce_istat:
            assert hazard in per_voce[m.voce_istat], hazard
    assert all(per_voce[codice] for codice in per_voce)
    assert set(per_voce) <= set(CATALOGO)
    assert {codice for codice in CATALOGO if usata(codice)} == set(per_voce)
    # Stesso numero di voci distinte fissato in test_mappatura (D3).
    assert len(per_voce) == 18


def test_le_voci_usate_non_hanno_stato_ne_motivo() -> None:
    for codice, voce in CATALOGO.items():
        if usata(codice):
            assert voce.stato is None, codice
            assert voce.motivo == "", codice


def test_ogni_voce_non_usata_ha_stato_e_motivo() -> None:
    for codice, voce in CATALOGO.items():
        if usata(codice) or codice == VOCE_TOTALE:
            continue
        assert voce.stato in ("usabile", "esclusa"), codice
        assert voce.motivo.strip(), codice


def test_il_totale_e_la_cornice() -> None:
    """D10: il totale entra solo come cornice del luogo, mai collegato a un rischio."""
    totale = CATALOGO[VOCE_TOTALE]
    assert not usata(VOCE_TOTALE)
    assert totale.stato == "cornice"
    assert totale.motivo.strip()
    assert [c for c, v in CATALOGO.items() if v.stato == "cornice"] == [VOCE_TOTALE]


def _figlie(madre: str) -> set[str]:
    return {c for c, v in CATALOGO.items() if v.madre == madre}


def test_gerarchia_della_codelist() -> None:
    assert _figlie("THEFT") == {
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
    assert _figlie("ROBBER") == {
        "HOUSEROB",
        "BANKROB",
        "POSTROB",
        "SHOPROB",
        "STREETROB",
    }
    assert _figlie("INTENHOM") == {"ROBBHOM", "MAFIAHOM", "TERRORHOM"}
    assert _figlie("UNINTHOM") == {"ROADHOM"}
    assert _figlie("ARSON") == {"FOREARS"}
    assert CATALOGO["DAMARS"].madre is None  # radice, non figlia di DAMAGE
    assert CATALOGO["DAMAGE"].madre is None


def test_le_madri_sono_radici_del_catalogo() -> None:
    """Gerarchia a un livello: ogni madre esiste ed e' a sua volta una radice."""
    for codice, voce in CATALOGO.items():
        if voce.madre is not None:
            assert voce.madre in CATALOGO, codice
            assert CATALOGO[voce.madre].madre is None, codice


def test_voci_legate_al_luogo() -> None:
    """Solo le sottovoci di furti e rapine che indicano un luogo (spec §2-§3)."""
    assert {c for c, v in CATALOGO.items() if v.legata_al_luogo} == {
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
        CATALOGO[c].madre in ("THEFT", "ROBBER")
        for c, v in CATALOGO.items()
        if v.legata_al_luogo
    )


def test_le_sottovoci_di_luogo_non_usate_dicono_perche() -> None:
    for codice in ("BURGTHEF", "VEHITHEF", "HOUSEROB"):
        assert not usata(codice), codice
        assert CATALOGO[codice].stato == "esclusa", codice


def test_le_corrispondenze_parziali_sono_escluse() -> None:
    """Spec §7: niente corrispondenza parziale per truffe e contraffazione."""
    for codice in ("SWINCYB", "COUNTER"):
        assert CATALOGO[codice].stato == "esclusa", codice
        assert "TERMINUS" in CATALOGO[codice].motivo, codice


def test_le_etichette_coincidono_con_il_file_dati() -> None:
    dati = json.loads(
        (Path(_pacchetto.__file__).parent / "delitti.json").read_text(encoding="utf-8")
    )
    voci: dict[str, str] = dati["voci"]
    assert voci  # il confronto non e' vacuo
    for codice, etichetta in voci.items():
        assert CATALOGO[codice].etichetta == etichetta, codice


def test_rottura_2016_dal_catalogo() -> None:
    """Fra le voci dei rischi solo i danneggiamenti (come su main 35acc46); in
    piu' il totale della cornice (#353) e due voci mai mostrate."""
    assert VOCI_ROTTURA_2016 == frozenset({"DAMAGE", "OFFENCE", "OTHCRIM", "TOT"})
    assert VOCI_ROTTURA_2016 == {c for c, v in CATALOGO.items() if v.rottura_2016}
    assert {c for c in VOCI_ROTTURA_2016 if usata(c)} == {"DAMAGE"}
    assert VOCE_TOTALE in VOCI_ROTTURA_2016


def test_la_rottura_della_mappatura_coincide_con_quella_del_catalogo() -> None:
    for hazard, m in MAPPATURA.items():
        if m.voce_istat:
            assert m.rottura_2016 is CATALOGO[m.voce_istat].rottura_2016, hazard
