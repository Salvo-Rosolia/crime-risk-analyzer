"""Criterio di vittoria lessicografico (#157), interamente offline."""

from __future__ import annotations

from crime_risk_analyzer.eval.compare import MetricValues
from crime_risk_analyzer.eval.winner import decide_winner


def _mv(
    grounding: float, hallucination: float, latency_ms: float, cost_usd: float
) -> MetricValues:
    return MetricValues(
        grounding=grounding,
        hallucination=hallucination,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
    )


def test_winner_decided_on_hallucination_lower_wins() -> None:
    """Asse primario: vince chi ha hallucination piu' bassa."""
    a = _mv(0.5, 0.10, 3000, 0.01)  # claude
    b = _mv(0.5, 0.20, 1000, 0.001)  # groq
    w = decide_winner(a, b, label_a="claude", label_b="groq")
    assert w.winner == "claude"
    assert w.deciding_axis == "hallucination"
    assert len(w.chain) == 1
    assert w.chain[0].outcome == "a"


def test_winner_tie_on_hallucination_falls_to_grounding_higher_wins() -> None:
    """Pari su hallucination -> decide grounding (piu' alto vince)."""
    a = _mv(0.90, 0.10, 3000, 0.01)
    b = _mv(0.70, 0.10, 1000, 0.001)
    w = decide_winner(a, b, label_a="claude", label_b="groq")
    assert w.winner == "claude"
    assert w.deciding_axis == "grounding"
    assert [c.outcome for c in w.chain] == ["tie", "a"]


def test_winner_falls_to_latency_then_cost() -> None:
    """Pari su hallucination+grounding -> decide latency (piu' bassa vince)."""
    a = _mv(0.80, 0.10, 3000, 0.01)
    b = _mv(0.80, 0.10, 1000, 0.001)
    w = decide_winner(a, b, label_a="claude", label_b="groq")
    assert w.winner == "groq"
    assert w.deciding_axis == "latency_ms"
    assert [c.outcome for c in w.chain] == ["tie", "tie", "b"]


def test_winner_decided_on_cost_when_all_else_tied() -> None:
    """Pari fino a latency -> decide cost (piu' basso vince)."""
    a = _mv(0.80, 0.10, 1000, 0.02)
    b = _mv(0.80, 0.10, 1000, 0.001)
    w = decide_winner(a, b, label_a="claude", label_b="groq")
    assert w.winner == "groq"
    assert w.deciding_axis == "cost_usd"
    assert [c.outcome for c in w.chain] == ["tie", "tie", "tie", "b"]


def test_total_tie_declares_no_winner() -> None:
    """Parita' su tutti e 4 gli assi (a precisione di stampa) -> pareggio."""
    a = _mv(0.80, 0.10, 1000, 0.001)
    b = _mv(0.80, 0.10, 1000, 0.001)
    w = decide_winner(a, b, label_a="claude", label_b="groq")
    assert w.winner is None
    assert w.deciding_axis is None
    assert len(w.chain) == 4
    assert all(c.outcome == "tie" for c in w.chain)


def test_tie_tolerance_at_print_precision() -> None:
    """0.1013 vs 0.1014 -> pari (3 decimali); 0.101 vs 0.104 -> decide."""
    tied = decide_winner(
        _mv(0.8, 0.1013, 1000, 0.001),
        _mv(0.8, 0.1014, 1000, 0.001),
        label_a="claude",
        label_b="groq",
    )
    assert tied.chain[0].outcome == "tie"  # hallucination pari a 3 decimali
    decided = decide_winner(
        _mv(0.8, 0.101, 1000, 0.001),
        _mv(0.8, 0.104, 1000, 0.001),
        label_a="claude",
        label_b="groq",
    )
    assert decided.deciding_axis == "hallucination"
    assert decided.winner == "claude"
