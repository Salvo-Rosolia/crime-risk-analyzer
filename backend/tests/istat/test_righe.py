"""Righe ISTAT (#345, spec 4.4): variazione, formato, dati reali, righe di un POI."""

from __future__ import annotations

import pytest

from crime_risk_analyzer.istat import righe as righe_mod
from crime_risk_analyzer.istat.dati import dati_istat
from crime_risk_analyzer.istat.luoghi import luogo_di
from crime_risk_analyzer.istat.righe import (
    MOTIVO_ANNO_MANCANTE,
    MOTIVO_ROTTURA_2016,
    MOTIVO_SOTTO_SOGLIA,
    formatta_decimale,
    formatta_intero,
    formatta_riga,
    istat_per_poi,
    riga_istat,
    variazione,
)
from tests.istat._fattorie import collegamento, cornice, riga


@pytest.mark.parametrize(
    ("attuale", "passato", "rottura", "atteso"),
    [
        (134169, 148910, False, (-10, None)),
        (812, 701, False, (16, None)),
        (20, 20, False, (0, None)),
        (1005, 1000, False, (1, None)),  # +0,5% -> 1: mezzo arrotonda via da zero
        (995, 1000, False, (-1, None)),
        (19, 100, False, (None, MOTIVO_SOTTO_SOGLIA)),
        (100, 19, False, (None, MOTIVO_SOTTO_SOGLIA)),
        (None, 100, False, (None, MOTIVO_ANNO_MANCANTE)),
        (100, None, False, (None, MOTIVO_ANNO_MANCANTE)),
        (19843, 16417, True, (None, MOTIVO_ROTTURA_2016)),
    ],
)
def test_variazione_sui_conteggi(
    attuale: int | None,
    passato: int | None,
    rottura: bool,
    atteso: tuple[int | None, str | None],
) -> None:
    assert variazione(attuale, passato, rottura_2016=rottura) == atteso


def test_formati_numerici_italiani() -> None:
    assert formatta_intero(134169) == "134.169"
    assert formatta_intero(17) == "17"
    assert formatta_decimale(1162.7) == "1.162,7"
    assert formatta_decimale(7829.0) == "7.829,0"
    assert formatta_decimale(0.6) == "0,6"


def test_formato_della_riga_di_una_voce() -> None:
    assert formatta_riga(riga(), poi_coinvolti=7) == (
        "- [Comune di Roma, 2024] furti (voce ISTAT THEFT): 134.169 delitti "
        "denunciati (2014: 148.910), 4.876,4 ogni 100.000 abitanti (Italia: "
        "1.788,7); variazione 2014-2024: -10%. Collegata a: Furto di beni (voce "
        "più ampia del rischio). POI coinvolti: 7."
    )


def test_formato_della_cornice() -> None:
    assert formatta_riga(cornice()) == (
        "- [Comune di Roma, 2024] totale dei delitti denunciati (contesto "
        "generale, non legato a un rischio): 217.536 delitti denunciati (2014: "
        "216.750), 7.906,3 ogni 100.000 abitanti (Italia: 4.069,6); variazione "
        "2014-2024: 0%."
    )


def test_collegamenti_raggruppati_per_corrispondenza() -> None:
    r = riga(
        collegamenti=(
            collegamento("Vehicle_Theft", "Furto di veicolo", "piu_stretta"),
            collegamento("Property_theft", "Furto di beni", "piu_larga"),
            collegamento("ATM_removal", "Asportazione del bancomat", "piu_larga"),
            collegamento("Purse_snatching", "Scippo", "esatta"),
        )
    )
    atteso = (
        "Collegata a: Scippo (corrispondenza esatta); Asportazione del "
        "bancomat, Furto di beni (voce più ampia del rischio); Furto di veicolo "
        "(voce che copre solo una parte del rischio)."
    )
    assert atteso in formatta_riga(r)


def test_formato_con_valori_mancanti_e_sotto_soglia() -> None:
    r = riga(
        delitti=None,
        confronto=None,
        tasso=None,
        sotto_soglia=False,
        italia=None,
        variazione=None,
        motivo=MOTIVO_ANNO_MANCANTE,
    )
    testo = formatta_riga(r)
    assert (
        "delitti denunciati nel 2024 non disponibili (2014: non disponibile)" in testo
    )
    assert (
        "tasso ogni 100.000 abitanti non disponibile (Italia: non disponibile)" in testo
    )
    assert f"variazione 2014-2024 non calcolata ({MOTIVO_ANNO_MANCANTE})" in testo
    sotto = formatta_riga(riga(tasso=None, sotto_soglia=True))
    assert "meno di 0,1 ogni 100.000 abitanti" in sotto


def test_riga_reale_furti_comune_di_roma() -> None:
    """Valori ISTAT estratti il 2026-10-06: un aggiornamento dei dati puo' cambiarli."""
    dati = dati_istat()
    roma = luogo_di(41.8902, 12.4922, dati=dati)
    assert roma is not None
    r = riga_istat(dati, roma, "THEFT", collegamenti=(collegamento(),))
    valori = (r.delitti, r.delitti_confronto, r.tasso, r.tasso_italia, r.variazione_pct)
    assert valori == (
        134169,
        148910,
        4876.4,
        1788.7,
        -10,
    )
    assert formatta_riga(r, poi_coinvolti=7) == formatta_riga(riga(), poi_coinvolti=7)


def test_riga_reale_tasso_sotto_soglia_e_rottura() -> None:
    dati = dati_istat()
    rho = luogo_di(45.5306, 9.0402, dati=dati)  # Rho, Provincia di Milano
    assert rho is not None and rho.codice == "ITC45"
    incendi = riga_istat(dati, rho, "FOREARS")
    assert incendi.tasso is None and incendi.tasso_sotto_soglia
    assert incendi.motivo_senza_variazione == MOTIVO_SOTTO_SOGLIA
    roma = luogo_di(41.8902, 12.4922, dati=dati)
    assert roma is not None
    danni = riga_istat(dati, roma, "DAMAGE")
    assert danni.rottura_2016 and danni.variazione_pct is None
    assert danni.motivo_senza_variazione == MOTIVO_ROTTURA_2016


def test_righe_di_un_poi_raggruppano_gli_hazard_per_voce() -> None:
    istat = istat_per_poi(
        41.8902, 12.4922, ["Bank_robbery", "Property_theft", "ATM_removal", "Landslide"]
    )
    assert istat is not None
    assert [r.voce for r in istat.righe] == ["BANKROB", "THEFT"]
    furti = istat.righe[1]
    assert {c.hazard for c in furti.collegamenti} == {"Property_theft", "ATM_removal"}
    assert {c.hazard_label_it for c in furti.collegamenti} == {
        "Furto di beni",
        "Asportazione del bancomat",
    }
    assert (istat.cornice.voce, istat.cornice.luogo_codice) == ("TOT", "058091")
    assert istat.cornice.collegamenti == ()


def test_nessuna_riga_fuori_dai_poligoni_o_senza_voci() -> None:
    assert istat_per_poi(41.0, 12.0, ["Bank_robbery"]) is None  # mare
    assert istat_per_poi(41.8902, 12.4922, ["Landslide", "Crime_explosion"]) is None
    assert istat_per_poi(41.8902, 12.4922, []) is None


def test_nessuna_riga_senza_dati(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(righe_mod, "dati_istat_o_none", lambda: None)
    assert istat_per_poi(41.8902, 12.4922, ["Bank_robbery"]) is None
