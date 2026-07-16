"""Fold delle K ripetizioni di un braccio (#157, spec-valutazione §2).

Riceve i K RunRecord di un esperimento (K run per ogni (citta, zona), prodotte
da run_experiment --repeat K) e li ripiega in UN record-media per zona + la
deviazione standard (popolazione) per metrica. Il record-media alimenta
l'esistente compare.compare_records (riuso #33); la varianza va nel report
esteso (repeated_comparison).

Politica ERROR (coerente con compare.py): le ripetizioni in ERROR non entrano in
media/std e sono contate in ZoneVariance.n_dropped; se TUTTE le ripetizioni di
una zona sono ERROR, il record-media eredita status=ERROR (metriche azzerate)
cosi' compare_records raccoglie quella zona tra le escluse.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from pydantic import BaseModel

from crime_risk_analyzer.eval.compare import MetricValues
from crime_risk_analyzer.eval.schema import (
    Metrics,
    RunRecord,
    RunStatus,
)


class ZoneVariance(BaseModel):
    """Deviazione standard (popolazione) delle K ripetizioni di una zona."""

    citta: str
    zona: str
    std: MetricValues
    n_reps: int  # ripetizioni valide (non-ERROR) usate per media/std
    n_dropped: int  # ripetizioni ERROR escluse


class FoldedArm(BaseModel):
    """Esito del fold di un braccio: record-media per zona + varianza per zona.

    ``mean_records`` ha ESATTAMENTE un record per (citta, zona) → consumabile
    da compare.compare_records senza violare il vincolo "una run per zona".
    """

    mean_records: list[RunRecord]
    variances: list[ZoneVariance]


_ZERO_METRICS = Metrics(grounding=0.0, hallucination=0.0, latency_ms=0, cost_usd=0.0)
_ZERO_STD = MetricValues(grounding=0.0, hallucination=0.0, latency_ms=0.0, cost_usd=0.0)


def _group_by_zone(
    records: list[RunRecord],
) -> dict[tuple[str, str], list[RunRecord]]:
    groups: dict[tuple[str, str], list[RunRecord]] = defaultdict(list)
    for rec in records:
        groups[(rec.citta, rec.zona)].append(rec)
    return groups


def _mean_metrics(valid: list[RunRecord]) -> Metrics:
    n = len(valid)
    return Metrics(
        grounding=sum(r.metrics.grounding for r in valid) / n,
        hallucination=sum(r.metrics.hallucination for r in valid) / n,
        # latency arrotondata a int = precisione a cui la latenza viene
        # confrontata/riportata (§2.3 spec). Nel caso multi-zona la media
        # cross-zona (compare._mean) parte pero' da questi valori GIA'
        # arrotondati per-zona, non dalle latenze grezze: lo scostamento
        # risultante e' sub-ms, irrilevante ai fini del verdetto quando le
        # latenze dei bracci differiscono in modo apprezzabile.
        latency_ms=round(sum(r.metrics.latency_ms for r in valid) / n),
        cost_usd=sum(r.metrics.cost_usd for r in valid) / n,
    )


def _std_metrics(valid: list[RunRecord]) -> MetricValues:
    return MetricValues(
        grounding=statistics.pstdev([r.metrics.grounding for r in valid]),
        hallucination=statistics.pstdev([r.metrics.hallucination for r in valid]),
        latency_ms=statistics.pstdev([float(r.metrics.latency_ms) for r in valid]),
        cost_usd=statistics.pstdev([r.metrics.cost_usd for r in valid]),
    )


def _mean_record(source: RunRecord, metrics: Metrics, status: RunStatus) -> RunRecord:
    """Record-media di una zona; riusa la provenienza (snapshot_id) di ``source``."""
    return RunRecord(
        run_id=f"{source.experiment}__{source.citta}__{source.zona}__mean".lower(),
        experiment=source.experiment,
        citta=source.citta,
        zona=source.zona,
        mode=source.mode,
        model_id=source.model_id,
        status=status,
        metrics=metrics,
        narrativa="",
        n_poi=source.n_poi,
        provenance=source.provenance,
    )


def fold_arm(records: list[RunRecord]) -> FoldedArm:
    """Ripiega le K ripetizioni per zona in record-media + varianza.

    Solleva :class:`ValueError` se ``records`` e' vuoto.
    """
    if not records:
        raise ValueError("fold_arm: nessun record da ripiegare")
    groups = _group_by_zone(records)
    mean_records: list[RunRecord] = []
    variances: list[ZoneVariance] = []
    for citta, zona in sorted(groups):
        group = groups[(citta, zona)]
        valid = [r for r in group if r.status != RunStatus.ERROR]
        n_dropped = len(group) - len(valid)
        if not valid:
            mean_records.append(_mean_record(group[0], _ZERO_METRICS, RunStatus.ERROR))
            variances.append(
                ZoneVariance(
                    citta=citta,
                    zona=zona,
                    std=_ZERO_STD,
                    n_reps=0,
                    n_dropped=n_dropped,
                )
            )
            continue
        mean_records.append(_mean_record(valid[0], _mean_metrics(valid), RunStatus.OK))
        variances.append(
            ZoneVariance(
                citta=citta,
                zona=zona,
                std=_std_metrics(valid),
                n_reps=len(valid),
                n_dropped=n_dropped,
            )
        )
    return FoldedArm(mean_records=mean_records, variances=variances)
