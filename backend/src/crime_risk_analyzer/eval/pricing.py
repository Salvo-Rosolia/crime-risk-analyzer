"""Listino prezzi LLM e calcolo del costo (#34).

Unico punto di verità per i prezzi. Valori in USD per 1M di token,
verificati contro le pagine ufficiali (data indicata per riga sotto).
"""

from __future__ import annotations

from crime_risk_analyzer.llm.client import CLAUDE_MODEL, GROQ_MODEL

#: (prezzo_input, prezzo_output) in USD per 1.000.000 di token.
#:
#: GROQ_MODEL: verificato su console.groq.com/docs/model/openai/gpt-oss-120b
#: (2026-09-11), dopo la rimozione di llama-3.3-70b-versatile dal catalogo
#: Groq (vedi commento su ``GROQ_MODEL`` in ``llm/client.py`` per il motivo
#: del cambio). Chiave sul nome del modello, non su una stringa letterale
#: duplicata, cosi' un futuro cambio di ``GROQ_MODEL`` senza aggiornare questo
#: listino fallisce rumorosamente (``KeyError`` in ``cost_usd``) invece di
#: disallinearsi in silenzio.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    CLAUDE_MODEL: (3.00, 15.00),  # verificato 2026-06-29
    GROQ_MODEL: (0.15, 0.60),  # verificato 2026-09-11
}


def cost_usd(model_id: str, tokens_input: int, tokens_output: int) -> float:
    """Costo stimato in USD per una generazione.

    Solleva ``KeyError`` se il modello non è nel listino (niente costo-zero
    silenzioso che falserebbe le tabelle).
    """
    price_in, price_out = PRICES_USD_PER_MTOK[model_id]
    return tokens_input / 1_000_000 * price_in + tokens_output / 1_000_000 * price_out
