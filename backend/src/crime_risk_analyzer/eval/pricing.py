"""Listino prezzi LLM e calcolo del costo (#34).

Unico punto di verità per i prezzi. Valori in USD per 1M di token, con lo stato
di verifica indicato riga per riga sotto: la riga Groq è stata verificata sulla
pagina ufficiale, quella Claude porta ancora la data del valore originale e non
è stata riverificata.
"""

from __future__ import annotations

#: (prezzo_input, prezzo_output) in USD per 1.000.000 di token.
#:
#: Le chiavi sono **letterali**, non le costanti ``CLAUDE_MODEL``/``GROQ_MODEL``
#: di ``llm/client.py``: se fossero le costanti, cambiare model id ri-chiaverebbe
#: da solo il listino sul modello nuovo lasciandogli il prezzo VECCHIO, e nulla
#: fallirebbe. Con il letterale, un cambio di modello non accompagnato da una
#: riga di listino fa fallire rumorosamente ``cost_usd`` (``KeyError``) invece di
#: produrre tabelle di costo sbagliate in silenzio. Il pin costante -> letterale
#: è verificato in ``tests/eval/test_pricing.py``.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    # da confermare sulla pagina ufficiale (valore del 2026-06-29, non
    # riverificato al cambio di modello Groq).
    "claude-sonnet-4-6": (3.00, 15.00),
    # verificato 2026-09-11 su console.groq.com/docs/model/openai/gpt-oss-120b,
    # dopo la rimozione di llama-3.3-70b-versatile dal catalogo Groq (il motivo
    # del cambio è nel commento su ``GROQ_MODEL`` in ``llm/client.py``).
    "openai/gpt-oss-120b": (0.15, 0.60),
}


def cost_usd(model_id: str, tokens_input: int, tokens_output: int) -> float:
    """Costo stimato in USD per una generazione.

    Solleva ``KeyError`` se il modello non è nel listino (niente costo-zero
    silenzioso che falserebbe le tabelle).
    """
    price_in, price_out = PRICES_USD_PER_MTOK[model_id]
    return tokens_input / 1_000_000 * price_in + tokens_output / 1_000_000 * price_out
