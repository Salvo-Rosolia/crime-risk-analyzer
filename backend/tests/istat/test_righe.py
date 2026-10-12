"""Righe ISTAT (#345, spec 4.4): variazione, formato, dati reali, righe di un POI."""

from __future__ import annotations

import re

import pytest

from crime_risk_analyzer.istat import righe as righe_mod
from crime_risk_analyzer.istat.dati import dati_istat
from crime_risk_analyzer.istat.luoghi import luogo_di
from crime_risk_analyzer.istat.righe import (
    MOTIVO_ANNO_MANCANTE,
    MOTIVO_ROTTURA_2016,
    MOTIVO_SOTTO_SOGLIA,
    ConfrontoItalia,
    RigaIstat,
    confronto_italia,
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


def test_formato_della_riga_di_una_voce() -> None:
    """#365 D7: a parole, niente cifre, codici, parentesi quadre, POI coinvolti."""
    assert formatta_riga(riga()) == (
        "- Comune di Roma, 2024: furti: tasso più alto di quello italiano; in calo "
        "dal 2014. Collegata a: Furto di beni (voce più ampia del rischio)."
    )


def test_formato_della_cornice() -> None:
    assert formatta_riga(cornice()) == (
        "- Comune di Roma, 2024: totale dei delitti denunciati: tasso più alto di "
        "quello italiano; contesto generale, non legato a un rischio."
    )


@pytest.mark.parametrize(
    ("variazione_pct", "motivo", "atteso"),
    [
        (-10, None, "; in calo dal 2014."),
        (16, None, "; in crescita dal 2014."),
        (0, None, "; stabile dal 2014."),
        (
            None,
            MOTIVO_SOTTO_SOGLIA,
            f"; tendenza non calcolata: {MOTIVO_SOTTO_SOGLIA}.",
        ),
        (None, None, "; tendenza non calcolata."),
    ],
)
def test_tendenza_a_parole(
    variazione_pct: int | None, motivo: str | None, atteso: str
) -> None:
    assert atteso in formatta_riga(riga(variazione=variazione_pct, motivo=motivo))


@pytest.mark.parametrize(
    "r",
    [
        riga(),
        riga(variazione=16),
        riga(
            tasso=None, sotto_soglia=True, variazione=None, motivo=MOTIVO_ANNO_MANCANTE
        ),
        cornice(),
    ],
)
def test_nessuna_cifra_ne_codice_nella_riga(r: RigaIstat) -> None:
    """Il modello non puo' riportare cifre che non vede (D7): restano solo gli anni
    (e il riferimento di legge nel motivo della serie interrotta)."""
    testo = formatta_riga(r).replace("d.lgs. 7/2016", "")
    assert set(re.findall(r"\d+", testo)) <= {"2014", "2016", "2024"}
    assert r.voce not in testo and "[" not in testo and "%" not in testo
    assert "POI coinvolti" not in testo


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


def test_formato_senza_confronto() -> None:
    assert "confronto con il tasso italiano non disponibile" in formatta_riga(
        riga(tasso=None, italia=None)
    )


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
    assert formatta_riga(r) == formatta_riga(riga())


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


def test_la_cornice_non_calcola_la_variazione_per_la_rottura_2016() -> None:
    """Il totale comprende fatti depenalizzati dal d.lgs. 7/2016 (ingiurie,
    danneggiamento semplice, ...): come per i danneggiamenti la variazione
    decennale non si calcola e la riga dice perche' (#353). La regola viene dal
    catalogo, non da un elenco a parte."""
    dati = dati_istat()
    milano = luogo_di(45.4642, 9.19, dati=dati)
    assert milano is not None
    totale = riga_istat(dati, milano, "TOT")
    # Il caso non e' vacuo: senza rottura la variazione sarebbe calcolabile.
    assert variazione(totale.delitti, totale.delitti_confronto, rottura_2016=False) == (
        -13,
        None,
    )
    assert totale.rottura_2016
    assert totale.variazione_pct is None
    assert totale.motivo_senza_variazione == MOTIVO_ROTTURA_2016

    istat = istat_per_poi(45.4642, 9.19, ["Property_theft"])
    assert istat is not None
    assert istat.cornice.variazione_pct is None
    assert istat.cornice.motivo_senza_variazione == MOTIVO_ROTTURA_2016


@pytest.mark.parametrize(
    ("tasso", "sotto_soglia", "italia", "italia_sotto_soglia", "atteso"),
    [
        (110.0, False, 100.0, False, "piu_alto"),  # bordo 1,10 compreso
        (109.9, False, 100.0, False, "simile"),
        (3.3, False, 3.0, False, "piu_alto"),  # 1,1 esatto anche se in float no
        (90.0, False, 100.0, False, "piu_basso"),  # bordo 0,90 compreso
        (90.1, False, 100.0, False, "simile"),
        (100.0, False, 100.0, False, "simile"),
        (None, False, 100.0, False, None),  # tasso mancante
        (100.0, False, None, False, None),  # nazionale mancante
        (100.0, False, 0.0, False, None),  # nazionale 0
        (None, True, 100.0, False, "piu_basso"),  # "meno di 0,1" vale 0
        (100.0, False, None, True, None),  # nazionale "meno di 0,1" vale 0
        (None, True, None, True, None),
    ],
)
def test_confronto_col_tasso_italiano(
    tasso: float | None,
    sotto_soglia: bool,
    italia: float | None,
    italia_sotto_soglia: bool,
    atteso: ConfrontoItalia | None,
) -> None:
    """#365 D2: una sola classificazione, riusata dal blocco e dal controllo."""
    r = riga(tasso=tasso, sotto_soglia=sotto_soglia, italia=italia).model_copy(
        update={"tasso_italia_sotto_soglia": italia_sotto_soglia}
    )
    assert confronto_italia(r) == atteso


@pytest.mark.parametrize(
    ("tasso", "italia", "frase"),
    [
        (4876.4, 1788.7, ": tasso più alto di quello italiano;"),
        (100.0, 200.0, ": tasso più basso di quello italiano;"),
        (100.0, 105.0, ": tasso simile a quello italiano;"),
    ],
)
def test_la_riga_della_voce_porta_il_confronto(
    tasso: float, italia: float, frase: str
) -> None:
    assert frase in formatta_riga(riga(tasso=tasso, italia=italia))


def test_anche_il_totale_ha_il_confronto() -> None:
    """D7: la riga del totale dice il confronto, quindi il controllo lo verifica."""
    assert confronto_italia(cornice()) == "piu_alto"
