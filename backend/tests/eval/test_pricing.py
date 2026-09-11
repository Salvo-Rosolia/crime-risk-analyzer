import pytest

from crime_risk_analyzer.eval.pricing import cost_usd
from crime_risk_analyzer.llm.client import GROQ_MODEL


def test_cost_claude() -> None:
    # 1M input @3.00 + 1M output @15.00 = 18.00
    assert cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000) == pytest.approx(18.0)


def test_cost_zero_tokens() -> None:
    assert cost_usd(GROQ_MODEL, 0, 0) == 0.0


def test_cost_groq() -> None:
    # 1M input @0.15 + 1M output @0.60 = 0.75
    assert cost_usd(GROQ_MODEL, 1_000_000, 1_000_000) == pytest.approx(0.75)


def test_cost_unknown_model_raises() -> None:
    with pytest.raises(KeyError):
        cost_usd("modello-inesistente", 1, 1)
