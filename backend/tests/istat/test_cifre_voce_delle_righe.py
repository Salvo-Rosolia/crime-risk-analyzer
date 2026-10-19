"""Una frase nomina una voce delle righe ISTAT del prompt? (#378)

Serve a separare, fra le frasi ISTAT escluse da M1, quelle che non nominano
nessuna voce passata al modello: sono le candidate a un rischio scritto con le
parole del dato ISTAT ma fuori dalle righe.
"""

from __future__ import annotations

import pytest

from crime_risk_analyzer.istat.cifre import nomina_voce_delle_righe
from tests.istat._fattorie import RAPINE_IN_BANCA, cornice, riga

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
        # Il totale come "delitti denunciati", con la cornice nelle righe.
        "Secondo l'ISTAT i delitti denunciati a Roma sono in calo",
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


def test_delitti_denunciati_senza_la_cornice_non_nominano_una_voce() -> None:
    """Il totale vale solo se la riga del totale e' fra quelle del prompt."""
    frase = "Secondo l'ISTAT i delitti denunciati a Roma sono in calo"
    assert nomina_voce_delle_righe(frase, (riga(),)) is False


def test_codice_di_una_voce_che_non_e_nelle_righe() -> None:
    assert nomina_voce_delle_righe("Secondo l'ISTAT BANKROB cala", (riga(),)) is False
