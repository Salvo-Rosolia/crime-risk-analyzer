"""Una frase nomina una voce delle righe ISTAT del prompt? (#378)

Serve a separare, fra le frasi ISTAT escluse da M1, quelle che non nominano
nessuna voce passata al modello: sono le candidate a un rischio scritto con le
parole del dato ISTAT ma fuori dalle righe.
"""

from __future__ import annotations

import pytest

from crime_risk_analyzer.istat.cifre import nomina_voce_delle_righe
from tests.istat._fattorie import RAPINE_IN_BANCA, collegamento, cornice, riga

_RIGHE = (cornice(), riga(), RAPINE_IN_BANCA)


@pytest.mark.parametrize(
    "frase",
    [
        # Etichetta della voce, anche al singolare (#392) e in grassetto.
        "Secondo i dati ISTAT del Comune di Roma i furti sono in calo",
        "Secondo l'ISTAT il **furto** e' in calo",
        # Etichetta del rischio collegato alla riga (C1).
        "Secondo l'ISTAT il furto di beni ha un tasso piu' alto",
        # Codice della voce.
        "Secondo l'ISTAT la voce BANKROB e' in calo",
        "Secondo l'ISTAT le rapine in banca sono in calo",
        # La voce renderizzata, anche dentro una frase sui "delitti denunciati".
        "Secondo l'ISTAT i delitti denunciati per furti a Roma sono in calo",
    ],
)
def test_frase_che_nomina_una_voce_delle_righe(frase: str) -> None:
    assert nomina_voce_delle_righe(frase, _RIGHE) is True


@pytest.mark.parametrize(
    "frase",
    [
        # Il caso dell'issue: un rischio che non e' nelle righe.
        "Secondo i dati ISTAT a Roma sono in aumento i sequestri di persona",
        # Falso segnale dichiarato: frase sul dato in generale, senza voce.
        "I dati ISTAT si riferiscono al Comune di Roma",
    ],
)
def test_frase_senza_voce_delle_righe(frase: str) -> None:
    assert nomina_voce_delle_righe(frase, _RIGHE) is False


def test_delitti_denunciati_non_bastano_a_nominare_una_voce() -> None:
    """Il totale (cornice) c'e' sempre fra le righe e il prompt contiene la
    locuzione: non conta, la frase con un rischio fuori dalle righe e' candidata."""
    frase = (
        "Secondo i dati ISTAT del Comune di Roma i delitti denunciati per "
        "sequestro di persona sono in aumento"
    )
    assert nomina_voce_delle_righe(frase, _RIGHE) is False


def test_rischio_collegato_alla_riga_nomina_la_voce() -> None:
    """C1: «scippi» non e' l'etichetta della voce («furti con strappo») ma il
    rischio «Scippo» collegato alla riga."""
    righe = (
        cornice(),
        riga(
            "BAGTHEF",
            label="furti con strappo",
            collegamenti=(collegamento("Purse_snatching", "Scippo", "esatta"),),
        ),
    )
    frase = "Secondo l'ISTAT gli scippi sono in aumento"
    assert nomina_voce_delle_righe(frase, righe) is True


def test_codice_di_una_voce_che_non_e_nelle_righe() -> None:
    assert nomina_voce_delle_righe("Secondo l'ISTAT BANKROB cala", (riga(),)) is False
