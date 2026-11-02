"""Tests for the typed confidence/tag vocabulary (#59).

The vocabulary centralizes the canonical values of ``confidence`` (lowercase:
``verificato``/``da_confermare``) and ``tag`` (uppercase:
``ONTOLOGIA``/``CONTESTO``/``SPECULATIVO``) used by the citation layer, plus the
:class:`ConfidenceSummary` model that replaces the old ``dict[str, int]``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crime_risk_analyzer.models.vocab import ConfidenceSummary


def test_confidence_summary_defaults_to_zero() -> None:
    summary = ConfidenceSummary()

    assert summary.verificato == 0
    assert summary.da_confermare == 0


def test_confidence_summary_accepts_counts() -> None:
    summary = ConfidenceSummary(verificato=2, da_confermare=1)

    assert summary.verificato == 2
    assert summary.da_confermare == 1


def test_confidence_summary_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        ConfidenceSummary(verificato=-1)


def test_confidence_literal_rejects_unknown_value() -> None:
    # A value outside the vocabulary (e.g. wrong casing or an invented level)
    # must fail validation when applied to the Confidence type.
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
        RiskItem(hazard="x", confidence="verificato", tag="alto")  # pyright: ignore[reportArgumentType]


def test_confidence_summary_has_no_numeric_danger_scoring_field() -> None:
    """Anti-scoring guard extended to the /analyze contract (#184, following
    the pattern of #118 on ``PoiRiskProfile``). ``ConfidenceSummary`` consists
    only of numeric fields, but they are coverage COUNTS per confidence level
    (evidential strength), NOT a danger score — which is exactly why it is the
    place most exposed to a numeric risk aggregate (e.g.
    ``punteggio_totale``/``livello_rischio``). The exact set pins it and turns
    the test red, forcing a conscious review (_project.md §Vincoli)."""
    assert set(ConfidenceSummary.model_fields) == {
        "verificato",
        "da_confermare",
    }
