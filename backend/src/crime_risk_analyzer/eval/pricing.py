"""Listino prezzi LLM e calcolo del costo (#34).

Unico punto di verità per i prezzi. Valori in USD per 1M di token,
da confermare contro le pagine ufficiali (data: 2026-06-29).
"""

from __future__ import annotations

#: (prezzo_input, prezzo_output) in USD per 1.000.000 di token.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "llama-3.3-70b-versatile": (0.59, 0.79),
}


def cost_usd(model_id: str, tokens_input: int, tokens_output: int) -> float:
    """Costo stimato in USD per una generazione.

    Solleva ``KeyError`` se il modello non è nel listino (niente costo-zero
    silenzioso che falserebbe le tabelle).
    """
    price_in, price_out = PRICES_USD_PER_MTOK[model_id]
    return tokens_input / 1_000_000 * price_in + tokens_output / 1_000_000 * price_out
