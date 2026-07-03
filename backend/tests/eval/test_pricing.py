import pytest

from crime_risk_analyzer.eval.pricing import cost_usd


def test_cost_claude() -> None:
    # 1M input @3.00 + 1M output @15.00 = 18.00
    assert cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000) == pytest.approx(18.0)


def test_cost_zero_tokens() -> None:
    assert cost_usd("llama-3.3-70b-versatile", 0, 0) == 0.0


def test_cost_unknown_model_raises() -> None:
    with pytest.raises(KeyError):
        cost_usd("modello-inesistente", 1, 1)
