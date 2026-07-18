"""Test del vocabolario tipizzato confidence/tag (#59).

Il vocabolario centralizza i valori canonici di ``confidence`` (minuscolo:
``confermato``/``plausibile``/``speculativo``) e ``tag`` (maiuscolo:
``ONTOLOGIA``/``CONTESTO``/``SPECULATIVO``) usati dal citation layer, piu' il
modello :class:`ConfidenceSummary` che sostituisce il vecchio ``dict[str, int]``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crime_risk_analyzer.models.vocab import ConfidenceSummary


def test_confidence_summary_defaults_to_zero() -> None:
    summary = ConfidenceSummary()

    assert summary.confermato == 0
    assert summary.plausibile == 0
    assert summary.speculativo == 0


def test_confidence_summary_accepts_counts() -> None:
    summary = ConfidenceSummary(confermato=2, plausibile=1, speculativo=3)

    assert summary.confermato == 2
    assert summary.plausibile == 1
    assert summary.speculativo == 3


def test_confidence_summary_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        ConfidenceSummary(confermato=-1)


def test_confidence_literal_rejects_unknown_value() -> None:
    # Un valore fuori dal vocabolario (es. casing errato o livello inventato)
    # deve fallire la validazione quando applicato al tipo Confidence.
    from crime_risk_analyzer.rag.generation import RiskItem

    with pytest.raises(ValidationError):
        RiskItem(hazard="x", confidence="alto")  # pyright: ignore[reportArgumentType]


def test_confidence_literal_rejects_capitalized_value() -> None:
    from crime_risk_analyzer.rag.generation import RiskItem

    with pytest.raises(ValidationError):
        RiskItem(hazard="x", confidence="Confermato")  # pyright: ignore[reportArgumentType]


def test_tag_literal_rejects_unknown_value() -> None:
    from crime_risk_analyzer.rag.generation import RiskItem

    with pytest.raises(ValidationError):
        RiskItem(hazard="x", confidence="confermato", tag="alto")  # pyright: ignore[reportArgumentType]


def test_confidence_summary_has_no_numeric_danger_scoring_field() -> None:
    """Guardia anti-scoring estesa al contratto /analyze (#184, sul pattern di
    #118 su ``PoiRiskProfile``). ``ConfidenceSummary`` e' fatto di soli campi
    numerici, ma sono CONTEGGI di copertura per livello di confidenza (forza
    probatoria), NON un punteggio di pericolosita' — proprio per questo e' il
    posto piu' esposto a un aggregato numerico di rischio (es.
    ``punteggio_totale``/``livello_rischio``). L'insieme esatto lo blocca e
    rende il test rosso, forzando una revisione cosciente (_project.md §Vincoli)."""
    assert set(ConfidenceSummary.model_fields) == {
        "confermato",
        "plausibile",
        "speculativo",
    }
