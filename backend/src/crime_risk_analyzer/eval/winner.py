"""Lexicographic winning criterion (#157, evaluation-spec section 2).

Decides the winner of the comparison between two models on the MEANS of the K
repetitions, in a lexicographic order declared a priori:
  1. hallucination (lower wins)
  2. grounding     (higher wins)
  3. latency_ms    (lower wins)
  4. cost_usd      (lower wins)
Two values are 'tied' if they coincide at the precision with which the metric is
printed (3/3/0/6 decimals) -> move on to the next axis. A tie on all 4
axes -> no winner (explicit draw), no artificial tie-break.

Axes 3 and 4 are SWITCHABLE TIE-BREAKS (#236, ``operational_tiebreak``): on
a pair of arms whose prompts differ in length by construction -- the
arm without ontology receives no hazard, vulnerability or citations -- lower latency
and cost are not a merit, and a verdict decided by them would measure
the prompt length. There the chain stops at quality and the draw stays
declared. Between two MODELS, which receive the same prompt, they remain
legitimate tie-breaks: the default does not change.

LIMIT (#164-D): 'grounding' is a redundant axis, NOT a second independent
criterion. It is the linear complement of 'hallucination' over the same
denominator (the assertions): ``hallucination == 1 - grounding`` when the
assertions are > 0 (see metrics.py). So the tie-break on 'grounding' in fact
never decides: when 'hallucination' ties (same rounding grid) 'grounding'
ties too; and in the degenerate corners (empty narrative vs full-without-assertions)
it is 'hallucination' that decides (0.0 vs 1.0).
'grounding' stays in the chain for transparency, it adds no orthogonal
information. A truly orthogonal 2nd axis (coverage/integrity, section 2) is a
future improvement, not implemented here so as not to alter the semantics of the
verdict before the real data.

Scope note (#157): the 'hallucination' axis is the textual PROXY already in
Metrics; 'filter intervention rate' and 'residual hallucinations' (spec section 2)
are separate deliverables, not implemented here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from crime_risk_analyzer.eval.compare import MetricValues


@dataclass(frozen=True)
class _AxisSpec:
    name: str
    ndigits: int  # print precision = tie tolerance
    higher_better: bool
    get: Callable[[MetricValues], float]


#: QUALITY axes (the two textual proxies): valid on any pair of arms.
_QUALITY_AXES: tuple[_AxisSpec, ...] = (
    _AxisSpec("hallucination", 3, False, lambda m: m.hallucination),
    _AxisSpec("grounding", 3, True, lambda m: m.grounding),
)

#: OPERATIONAL axes (direct measures), used ONLY as a tie-break after quality.
#: Kept apart from the above because they are not a merit on every pair: when the
#: two arms receive prompts of different length by construction, the one with the
#: shorter prompt is faster and cheaper regardless of what it says
#: (#236) -- see ``operational_tiebreak`` in :func:`decide_winner`.
_OPERATIONAL_AXES: tuple[_AxisSpec, ...] = (
    _AxisSpec("latency_ms", 0, False, lambda m: m.latency_ms),
    _AxisSpec("cost_usd", 6, False, lambda m: m.cost_usd),
)

#: Lexicographic order + direction + precision. The precisions match the
#: formats of compare.py (grounding/halluc .3f, latency .0f, cost .6f): a
#: tie is defined "at what is printed".
_AXES: tuple[_AxisSpec, ...] = _QUALITY_AXES + _OPERATIONAL_AXES

#: Reason printed when quality ties and the operational tie-break is
#: excluded (#236). The withheld verdict must be JUSTIFIED: a mute ``winner=None``
#: would be indistinguishable from the four-axis tie of #157, which is another
#: fact (there latency and cost coincide too). Real accents and not apostrophes:
#: this string ends up in the Markdown report next to ``PROMPT_LENGTH_SIDE_EFFECT``
#: and ``verdict_na_markdown``, which use them -- the rest of the module, which the
#: report reader does not see, stays as it is.
NO_OPERATIONAL_TIEBREAK_REASON = (
    "verdetto non decidibile: le metriche di qualità pareggiano e velocità/"
    "costo non sono spareggi validi su questa coppia, perché il prompt del "
    "braccio senza ontologia è strutturalmente più corto"
)

#: Print precision per axis, exposed to the renderer (Task 4).
AXIS_PRECISION: dict[str, int] = {spec.name: spec.ndigits for spec in _AXES}


class AxisComparison(BaseModel):
    """Comparison on a single axis: raw values + outcome at print precision."""

    axis: str
    value_a: float
    value_b: float
    outcome: Literal["a", "b", "tie"]


class Winner(BaseModel):
    """Lexicographic verdict with justification.

    ``winner`` and ``deciding_axis`` are ``None`` in case of a total tie.
    ``chain`` lists the axes evaluated up to and including the deciding one (or all
    ADMITTED ones on a tie): it makes the decision auditable. An axis excluded from
    the tie-break does not appear in ``chain`` -- it produced no "tie", it was not
    looked at.
    """

    label_a: str
    label_b: str
    winner: str | None
    deciding_axis: str | None
    chain: list[AxisComparison]
    #: Why there is no winner, when the reason is not the plain
    #: tie on all admitted axes (#236: operational tie-break excluded).
    #: Empty in the #157 case, so the report does not change where it must not.
    no_winner_reason: str = ""


def _axis_outcome(spec: _AxisSpec, a: float, b: float) -> Literal["a", "b", "tie"]:
    ra = round(a, spec.ndigits)
    rb = round(b, spec.ndigits)
    if ra == rb:
        return "tie"
    if spec.higher_better:
        return "a" if ra > rb else "b"
    return "a" if ra < rb else "b"


def decide_winner(
    mean_a: MetricValues,
    mean_b: MetricValues,
    *,
    label_a: str,
    label_b: str,
    operational_tiebreak: bool = True,
) -> Winner:
    """Apply the lexicographic section 2 on the means; return the justified verdict.

    ``operational_tiebreak=False`` restricts the chain to the QUALITY axes only
    (:data:`_QUALITY_AXES`): if they tie, the verdict is "no winner" with
    :data:`NO_OPERATIONAL_TIEBREAK_REASON`, not a silent winner on
    latency or cost. It serves the with/without-ontology pair (#236), in which the
    ablated arm receives a structurally shorter prompt -- no hazard,
    vulnerability or citations -- and is therefore faster and cheaper BY
    CONSTRUCTION: a tie-break on those axes would reward prompt
    length. The default stays ``True``, so the comparison between two MODELS
    (#157), where the prompt is the same and a lower latency is a merit
    of the model, does not change behaviour.
    """
    axes = _AXES if operational_tiebreak else _QUALITY_AXES
    chain: list[AxisComparison] = []
    for spec in axes:
        a = spec.get(mean_a)
        b = spec.get(mean_b)
        outcome = _axis_outcome(spec, a, b)
        chain.append(
            AxisComparison(axis=spec.name, value_a=a, value_b=b, outcome=outcome)
        )
        if outcome != "tie":
            winner = label_a if outcome == "a" else label_b
            return Winner(
                label_a=label_a,
                label_b=label_b,
                winner=winner,
                deciding_axis=spec.name,
                chain=chain,
            )
    return Winner(
        label_a=label_a,
        label_b=label_b,
        winner=None,
        deciding_axis=None,
        chain=chain,
        no_winner_reason=(
            "" if operational_tiebreak else NO_OPERATIONAL_TIEBREAK_REASON
        ),
    )
