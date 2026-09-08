"""Criterio di vittoria lessicografico (#157), interamente offline."""

from __future__ import annotations

from crime_risk_analyzer.eval.compare import MetricValues
from crime_risk_analyzer.eval.winner import (
    NO_OPERATIONAL_TIEBREAK_REASON,
    decide_winner,
)


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


def test_tie_tolerance_at_print_precision_for_cost_usd() -> None:
    """cost_usd (6 decimali): differiscono alla 6a cifra -> decide; pari fino
    alla 6a -> pareggio. Valori scelti cosi' che con ndigits=3 (mutazione)
    risulterebbero entrambi pari (round(x,3)==0.0), catturando lo shrink 6→3."""
    tied = decide_winner(
        _mv(0.8, 0.10, 1000, 0.0000011),
        _mv(0.8, 0.10, 1000, 0.0000009),
        label_a="claude",
        label_b="groq",
    )
    assert tied.chain[-1].axis == "cost_usd"
    assert tied.chain[-1].outcome == "tie"
    assert tied.winner is None

    decided = decide_winner(
        _mv(0.8, 0.10, 1000, 0.0000010),
        _mv(0.8, 0.10, 1000, 0.0000020),
        label_a="claude",
        label_b="groq",
    )
    assert decided.deciding_axis == "cost_usd"
    assert decided.winner == "claude"  # costo piu' basso vince


def test_tie_tolerance_at_print_precision_for_latency_ms() -> None:
    """latency_ms (0 decimali): 1000.4 vs 1000.6 -> decide (round 1000 vs 1001);
    1000.4 vs 1000.3 -> pari (entrambi round 1000)."""
    tied = decide_winner(
        _mv(0.8, 0.10, 1000.4, 0.001),
        _mv(0.8, 0.10, 1000.3, 0.001),
        label_a="claude",
        label_b="groq",
    )
    # cost_usd e' anch'esso pari (0.001==0.001): la catena prosegue fino in
    # fondo, quindi si cerca l'asse latency_ms esplicitamente (non l'ultimo).
    latency_comparison = next(c for c in tied.chain if c.axis == "latency_ms")
    assert latency_comparison.outcome == "tie"
    assert tied.winner is None

    decided = decide_winner(
        _mv(0.8, 0.10, 1000.4, 0.001),
        _mv(0.8, 0.10, 1000.6, 0.001),
        label_a="claude",
        label_b="groq",
    )
    assert decided.deciding_axis == "latency_ms"
    assert decided.winner == "claude"  # 1000 < 1001


# --- #236: su una coppia di bracci velocita' e costo non sono spareggi validi ---


def test_operational_axes_are_not_a_tiebreak_when_excluded() -> None:
    """Escluso lo spareggio operativo, pari sulla qualita' = nessun vincitore.

    Sulla coppia con/senza ontologia il braccio ablato riceve un prompt
    strutturalmente piu' corto (niente hazard, vulnerabilita' e citazioni):
    e' piu' veloce ed economico PER COSTRUZIONE. Un verdetto deciso da latenza o
    costo direbbe che togliere l'ontologia «vince», misurando la lunghezza del
    prompt — percio' qui il pareggio resta un pareggio, dichiarato.
    """
    w = decide_winner(
        _mv(0.80, 0.10, 3000, 0.010),
        _mv(0.80, 0.10, 1000, 0.001),
        label_a="con-ontologia",
        label_b="senza-ontologia",
        operational_tiebreak=False,
    )
    assert w.winner is None
    assert w.deciding_axis is None
    # La catena elenca gli assi VALUTATI: latenza e costo non hanno partecipato,
    # quindi non compaiono come se fossero risultati pari.
    assert [c.axis for c in w.chain] == ["hallucination", "grounding"]
    assert w.no_winner_reason == NO_OPERATIONAL_TIEBREAK_REASON
    assert "non decidibile" in w.no_winner_reason


def test_quality_axes_still_decide_when_the_operational_tiebreak_is_excluded() -> None:
    """L'esclusione tocca lo SPAREGGIO: sulla qualita' il verdetto resta pieno."""
    w = decide_winner(
        _mv(0.90, 0.10, 3000, 0.010),
        _mv(0.50, 0.50, 1000, 0.001),
        label_a="con-ontologia",
        label_b="senza-ontologia",
        operational_tiebreak=False,
    )
    assert w.winner == "con-ontologia"
    assert w.deciding_axis == "hallucination"
    assert w.no_winner_reason == ""


def test_total_tie_between_models_reports_no_special_reason() -> None:
    """Non-regressione: il pareggio a 4 assi di #157 non porta ragioni aggiunte."""
    w = decide_winner(
        _mv(0.80, 0.10, 1000, 0.001),
        _mv(0.80, 0.10, 1000, 0.001),
        label_a="claude",
        label_b="groq",
    )
    assert w.winner is None
    assert w.no_winner_reason == ""


def test_module_docstring_declares_grounding_is_not_independent() -> None:
    """#164-D: la docstring dichiara che grounding NON e' un asse indipendente."""
    import crime_risk_analyzer.eval.winner as winner_mod

    doc = (winner_mod.__doc__ or "").lower()
    assert "ridond" in doc  # grounding e' ridondante con hallucination
    assert "1 - grounding" in doc or "1-grounding" in doc or "1 − grounding" in doc
