"""LLM price list and cost computation (#34).

Single source of truth for prices. Values in USD per 1M tokens, with the
verification status noted line by line below: the Groq line was verified on the
official page, the Claude one still carries the date of the original value and
has not been re-verified.
"""

from __future__ import annotations

#: (input_price, output_price) in USD per 1,000,000 tokens.
#:
#: The keys are **literals**, not the ``CLAUDE_MODEL``/``GROQ_MODEL`` constants
#: of ``llm/client.py``: if they were the constants, changing the model id would
#: silently re-key the price list onto the new model leaving it the OLD price, and
#: nothing would fail. With the literal, a model change not accompanied by a
#: price-list row makes ``cost_usd`` fail loudly (``KeyError``) instead of
#: producing wrong cost tables silently. The constant -> literal pin is
#: verified in ``tests/eval/test_pricing.py``.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    # to be confirmed on the official page (value of 2026-06-29, not
    # re-verified at the Groq model change).
    "claude-sonnet-4-6": (3.00, 15.00),
    # verified 2026-09-11 on console.groq.com/docs/model/openai/gpt-oss-120b,
    # after llama-3.3-70b-versatile was removed from the Groq catalogue (the reason
    # for the change is in the comment on ``GROQ_MODEL`` in ``llm/client.py``).
    "openai/gpt-oss-120b": (0.15, 0.60),
}


def cost_usd(model_id: str, tokens_input: int, tokens_output: int) -> float:
    """Estimated cost in USD for one generation.

    Raises ``KeyError`` if the model is not in the price list (no silent
    zero cost that would falsify the tables).
    """
    price_in, price_out = PRICES_USD_PER_MTOK[model_id]
    return tokens_input / 1_000_000 * price_in + tokens_output / 1_000_000 * price_out
