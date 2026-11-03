"""Lexicographic winning criterion (#157), entirely offline."""

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
    """Primary axis: the one with the lower hallucination wins."""
    a = _mv(0.5, 0.10, 3000, 0.01)  # claude
    b = _mv(0.5, 0.20, 1000, 0.001)  # groq
    w = decide_winner(a, b, label_a="claude", label_b="groq")
    assert w.winner == "claude"
    assert w.deciding_axis == "hallucination"
    assert len(w.chain) == 1
    assert w.chain[0].outcome == "a"


def test_winner_tie_on_hallucination_falls_to_grounding_higher_wins() -> None:
    """Tie on hallucination -> grounding decides (higher wins)."""
    a = _mv(0.90, 0.10, 3000, 0.01)
    b = _mv(0.70, 0.10, 1000, 0.001)
    w = decide_winner(a, b, label_a="claude", label_b="groq")
    assert w.winner == "claude"
    assert w.deciding_axis == "grounding"
    assert [c.outcome for c in w.chain] == ["tie", "a"]


def test_winner_falls_to_latency_then_cost() -> None:
    """Tie on hallucination+grounding -> latency decides (lower wins)."""
    a = _mv(0.80, 0.10, 3000, 0.01)
    b = _mv(0.80, 0.10, 1000, 0.001)
    w = decide_winner(a, b, label_a="claude", label_b="groq")
    assert w.winner == "groq"
    assert w.deciding_axis == "latency_ms"
    assert [c.outcome for c in w.chain] == ["tie", "tie", "b"]


def test_winner_decided_on_cost_when_all_else_tied() -> None:
    """Tie up to latency -> cost decides (lower wins)."""
    a = _mv(0.80, 0.10, 1000, 0.02)
    b = _mv(0.80, 0.10, 1000, 0.001)
    w = decide_winner(a, b, label_a="claude", label_b="groq")
    assert w.winner == "groq"
    assert w.deciding_axis == "cost_usd"
    assert [c.outcome for c in w.chain] == ["tie", "tie", "tie", "b"]


def test_total_tie_declares_no_winner() -> None:
    """Tie on all 4 axes (at print precision) -> draw."""
    a = _mv(0.80, 0.10, 1000, 0.001)
    b = _mv(0.80, 0.10, 1000, 0.001)
    w = decide_winner(a, b, label_a="claude", label_b="groq")
    assert w.winner is None
    assert w.deciding_axis is None
    assert len(w.chain) == 4
    assert all(c.outcome == "tie" for c in w.chain)


def test_tie_tolerance_at_print_precision() -> None:
    """0.1013 vs 0.1014 -> tie (3 decimals); 0.101 vs 0.104 -> decides."""
    tied = decide_winner(
        _mv(0.8, 0.1013, 1000, 0.001),
        _mv(0.8, 0.1014, 1000, 0.001),
        label_a="claude",
        label_b="groq",
    )
    assert tied.chain[0].outcome == "tie"  # hallucination tied at 3 decimals
    decided = decide_winner(
        _mv(0.8, 0.101, 1000, 0.001),
        _mv(0.8, 0.104, 1000, 0.001),
        label_a="claude",
        label_b="groq",
    )
    assert decided.deciding_axis == "hallucination"
    assert decided.winner == "claude"


def test_tie_tolerance_at_print_precision_for_cost_usd() -> None:
    """cost_usd (6 decimals): they differ at the 6th digit -> decides; tie up
    to the 6th -> draw. Values chosen so that with ndigits=3 (mutation)
    both would be tied (round(x,3)==0.0), catching the 6->3 shrink."""
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
    assert decided.winner == "claude"  # lower cost wins


def test_tie_tolerance_at_print_precision_for_latency_ms() -> None:
    """latency_ms (0 decimals): 1000.4 vs 1000.6 -> decides (round 1000 vs 1001);
    1000.4 vs 1000.3 -> tie (both round 1000)."""
    tied = decide_winner(
        _mv(0.8, 0.10, 1000.4, 0.001),
        _mv(0.8, 0.10, 1000.3, 0.001),
        label_a="claude",
        label_b="groq",
    )
    # cost_usd is also tied (0.001==0.001): the chain goes on to the
    # end, so the latency_ms axis is looked up explicitly (not the last).
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


# --- #236: on a pair of arms speed and cost are not valid tie-breaks ---


def test_operational_axes_are_not_a_tiebreak_when_excluded() -> None:
    """With the operational tie-break excluded, a tie on quality = no winner.

    On the with/without-ontology pair the ablated arm receives a structurally
    shorter prompt (no hazard, vulnerability or citations):
    it is faster and cheaper BY CONSTRUCTION. A verdict decided by latency or
    cost would say that removing the ontology "wins", measuring the prompt
    length -- therefore here the tie stays a tie, declared.
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
    # The chain lists the EVALUATED axes: latency and cost did not take part,
    # so they do not appear as if they were tied results.
    assert [c.axis for c in w.chain] == ["hallucination", "grounding"]
    assert w.no_winner_reason == NO_OPERATIONAL_TIEBREAK_REASON
    assert "non decidibile" in w.no_winner_reason


def test_quality_axes_still_decide_when_the_operational_tiebreak_is_excluded() -> None:
    """The exclusion touches the TIE-BREAK: on quality the verdict stays full."""
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
    """Non-regression: the 4-axis tie of #157 carries no added reasons."""
    w = decide_winner(
        _mv(0.80, 0.10, 1000, 0.001),
        _mv(0.80, 0.10, 1000, 0.001),
        label_a="claude",
        label_b="groq",
    )
    assert w.winner is None
    assert w.no_winner_reason == ""


def test_module_docstring_declares_grounding_is_not_independent() -> None:
    """#164-D: the docstring declares that grounding is NOT an independent axis."""
    import crime_risk_analyzer.eval.winner as winner_mod

    doc = (winner_mod.__doc__ or "").lower()
    assert "redundan" in doc  # grounding is redundant with hallucination
    assert "1 - grounding" in doc or "1-grounding" in doc or "1 − grounding" in doc
