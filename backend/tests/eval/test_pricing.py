"""Test del listino prezzi LLM (#34).

Le chiavi di ``PRICES_USD_PER_MTOK`` sono letterali e NON le costanti
``CLAUDE_MODEL``/``GROQ_MODEL``: se fossero le costanti, cambiare model id
ri-chiaverebbe da solo il listino sul modello nuovo lasciandogli il prezzo
VECCHIO, senza che nulla fallisca. Il legame costante -> riga di listino e'
quindi verificato qui, con i model id e i prezzi scritti a mano nel test
(riletti dal modulo sarebbe una verifica circolare).
"""

import pytest

from crime_risk_analyzer.eval.pricing import PRICES_USD_PER_MTOK, cost_usd
from crime_risk_analyzer.llm.client import CLAUDE_MODEL, GROQ_MODEL

#: Model id attesi: sono il pin, non una rilettura del codice sotto test.
_CLAUDE_ID = "claude-sonnet-4-6"
_GROQ_ID = "openai/gpt-oss-120b"


def test_model_id_delle_costanti_sono_quelli_a_listino() -> None:
    """Cambiare ``GROQ_MODEL``/``CLAUDE_MODEL`` senza aggiornare il listino
    rompe qui, in CI, invece di far esplodere una run live con ``KeyError``."""
    assert CLAUDE_MODEL == _CLAUDE_ID
    assert GROQ_MODEL == _GROQ_ID
    assert _CLAUDE_ID in PRICES_USD_PER_MTOK
    assert _GROQ_ID in PRICES_USD_PER_MTOK


def test_prezzi_pinnati_ai_valori_verificati() -> None:
    """USD per 1M token, (input, output).

    Groq: verificato 2026-09-11 su console.groq.com/docs/model/openai/gpt-oss-120b.
    Claude: valore storico non riverificato (vedi docstring di ``pricing.py``).
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
