"""Does a sentence name an item of the ISTAT rows of the prompt? (#378)

It serves to separate, among the ISTAT sentences excluded from M1, those that name
no item passed to the model: they are the candidates for a risk written with the
words of the ISTAT datum but outside the rows.
"""

from __future__ import annotations

import pytest

from crime_risk_analyzer.istat.figures import names_item_of_rows
from tests.istat._factories import BANK_ROBBERIES, make_frame, make_link, make_row

_ROWS = (make_frame(), make_row(), BANK_ROBBERIES)


@pytest.mark.parametrize(
    "sentence",
    [
        # Label of the item, also in the singular (#392) and in bold.
        "Secondo i dati ISTAT del Comune di Roma i furti sono in calo",
        "Secondo l'ISTAT il **furto** e' in calo",
        # Label of the risk linked to the row (C1).
        "Secondo l'ISTAT il furto di beni ha un tasso piu' alto",
        # Code of the item.
        "Secondo l'ISTAT la voce BANKROB e' in calo",
        "Secondo l'ISTAT le rapine in banca sono in calo",
        # The rendered item, also inside a sentence about the "delitti denunciati".
        "Secondo l'ISTAT i delitti denunciati per furti a Roma sono in calo",
    ],
)
def test_sentence_that_names_an_item_of_the_rows(sentence: str) -> None:
    assert names_item_of_rows(sentence, _ROWS) is True


@pytest.mark.parametrize(
    "sentence",
    [
        # The issue's case: a risk that is not in the rows.
        "Secondo i dati ISTAT a Roma sono in aumento i sequestri di persona",
        # Declared false signal: sentence about the datum in general, without an item.
        "I dati ISTAT si riferiscono al Comune di Roma",
    ],
)
def test_sentence_without_an_item_of_the_rows(sentence: str) -> None:
    assert names_item_of_rows(sentence, _ROWS) is False


def test_reported_offences_do_not_suffice_to_name_an_item() -> None:
    """The total (frame) is always among the rows and the prompt contains the
    phrase: it does not count, a sentence with a risk outside the rows is a
    candidate."""
    sentence = (
        "Secondo i dati ISTAT del Comune di Roma i delitti denunciati per "
        "sequestro di persona sono in aumento"
    )
    assert names_item_of_rows(sentence, _ROWS) is False


def test_risk_linked_to_the_row_names_the_item() -> None:
    """C1: «scippi» is not the label of the item («furti con strappo») but the
    risk «Scippo» linked to the row."""
    rows = (
        make_frame(),
        make_row(
            "BAGTHEF",
            label="furti con strappo",
            links=(make_link("Purse_snatching", "Scippo", "esatta"),),
        ),
    )
    sentence = "Secondo l'ISTAT gli scippi sono in aumento"
    assert names_item_of_rows(sentence, rows) is True


def test_code_of_an_item_that_is_not_in_the_rows() -> None:
    assert names_item_of_rows("Secondo l'ISTAT BANKROB cala", (make_row(),)) is False
