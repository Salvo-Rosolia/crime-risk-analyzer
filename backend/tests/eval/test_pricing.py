"""Tests of the LLM price list (#34).

The keys of ``PRICES_USD_PER_MTOK`` are literals and NOT the
``CLAUDE_MODEL``/``GROQ_MODEL`` constants: if they were the constants, changing the
model id would silently re-key the price list onto the new model leaving it the OLD
price, without anything failing. The constant -> price-list-row link is
therefore verified here, with the model ids and prices written by hand in the test
(re-read from the module it would be a circular check).
"""

import pytest

from crime_risk_analyzer.eval.pricing import PRICES_USD_PER_MTOK, cost_usd
from crime_risk_analyzer.llm.client import CLAUDE_MODEL, GROQ_MODEL

#: Expected model ids: they are the pin, not a re-reading of the code under test.
_CLAUDE_ID = "claude-sonnet-4-6"
_GROQ_ID = "openai/gpt-oss-120b"


def test_constants_model_ids_are_the_listed_ones() -> None:
    """Changing ``GROQ_MODEL``/``CLAUDE_MODEL`` without updating the price list
    breaks here, in CI, instead of blowing up a live run with ``KeyError``."""
    assert CLAUDE_MODEL == _CLAUDE_ID
    assert GROQ_MODEL == _GROQ_ID
    assert _CLAUDE_ID in PRICES_USD_PER_MTOK
    assert _GROQ_ID in PRICES_USD_PER_MTOK


def test_prices_pinned_to_verified_values() -> None:
    """USD per 1M tokens, (input, output).

    Groq: verified 2026-09-11 on console.groq.com/docs/model/openai/gpt-oss-120b.
    Claude: historical value not re-verified (see docstring of ``pricing.py``).
    """
    assert PRICES_USD_PER_MTOK[_GROQ_ID] == (0.15, 0.60)
    assert PRICES_USD_PER_MTOK[_CLAUDE_ID] == (3.00, 15.00)


def test_cost_claude() -> None:
    # 1M input @3.00 + 1M output @15.00 = 18.00
    assert cost_usd(_CLAUDE_ID, 1_000_000, 1_000_000) == pytest.approx(18.0)


def test_cost_zero_tokens() -> None:
    assert cost_usd(_GROQ_ID, 0, 0) == 0.0


def test_cost_groq() -> None:
    # 1M input @0.15 + 1M output @0.60 = 0.75
    assert cost_usd(_GROQ_ID, 1_000_000, 1_000_000) == pytest.approx(0.75)


def test_cost_unknown_model_raises() -> None:
    with pytest.raises(KeyError):
        cost_usd("modello-inesistente", 1, 1)
