"""Criterio di vittoria lessicografico (#157, spec-valutazione §2).

Decide il vincitore del confronto tra due modelli sulle MEDIE delle K
ripetizioni, in ordine lessicografico dichiarato a priori:
  1. hallucination (piu' basso vince)
  2. grounding     (piu' alto vince)
  3. latency_ms    (piu' basso vince)
  4. cost_usd      (piu' basso vince)
Due valori sono 'pari' se coincidono alla precisione con cui la metrica viene
stampata (3/3/0/6 decimali) → si passa all'asse successivo. Parita' su tutti e 4
gli assi → nessun vincitore (pareggio esplicito), nessun tie-break artificiale.

Nota di scope (#157): l'asse 'hallucination' e' il PROXY testuale gia' in
Metrics; 'tasso di intervento del filtro' e 'allucinazioni residue' (spec §2)
sono deliverable separati, non implementati qui.
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
    ndigits: int  # precisione di stampa = tolleranza di parita'
    higher_better: bool
    get: Callable[[MetricValues], float]


#: Ordine lessicografico + direzione + precisione. Le precisioni combaciano con
#: i formati di compare.py (grounding/halluc .3f, latency .0f, cost .6f): la
#: parita' e' definita "a cio' che si stampa".
_AXES: tuple[_AxisSpec, ...] = (
    _AxisSpec("hallucination", 3, False, lambda m: m.hallucination),
    _AxisSpec("grounding", 3, True, lambda m: m.grounding),
    _AxisSpec("latency_ms", 0, False, lambda m: m.latency_ms),
    _AxisSpec("cost_usd", 6, False, lambda m: m.cost_usd),
)

#: Precisione di stampa per asse, esposta al renderer (Task 4).
AXIS_PRECISION: dict[str, int] = {spec.name: spec.ndigits for spec in _AXES}


class AxisComparison(BaseModel):
    """Confronto su un singolo asse: valori grezzi + esito a precisione di stampa."""

    axis: str
    value_a: float
    value_b: float
    outcome: Literal["a", "b", "tie"]


class Winner(BaseModel):
    """Verdetto lessicografico con motivazione.

    ``winner`` e ``deciding_axis`` sono ``None`` in caso di pareggio totale.
    ``chain`` elenca gli assi valutati fino al decisivo incluso (o tutti e 4 se
    pareggio): rende la decisione auditabile.
    """

    label_a: str
    label_b: str
    winner: str | None
    deciding_axis: str | None
    chain: list[AxisComparison]


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
) -> Winner:
    """Applica il lessicografico §2 sulle medie; ritorna il verdetto motivato."""
    chain: list[AxisComparison] = []
    for spec in _AXES:
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
    )
