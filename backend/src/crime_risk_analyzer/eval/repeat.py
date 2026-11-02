"""Fold of the K repetitions of an arm (#157, evaluation-spec section 2).

Receives the K RunRecords of an experiment (K runs for each (citta, zona), produced
by run_experiment --repeat K) and folds them into ONE mean-record per zone + the
standard deviation (population) per metric. The mean-record feeds the
existing compare.compare_records (reuse #33); the variance goes into the
extended report (repeated_comparison).

Exclusion policy (consistent with compare.py, #163): repetitions in ERROR
AND in FALLBACK do not enter mean/std (metrics not representative of
quality: zeroed by the harness for ERROR, empty narrative for FALLBACK). They are
counted in ZoneVariance.n_dropped, the FALLBACK ones alone also in n_fallback; if
NO repetition of a zone is valid (OK), the mean-record inherits
status=ERROR (zeroed metrics) so that compare_records collects that zone
among the excluded ones.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from pydantic import BaseModel

from crime_risk_analyzer.eval.compare import MetricValues
from crime_risk_analyzer.eval.istat_metrics import sum_istat_metrics
from crime_risk_analyzer.eval.schema import (
    IstatMetrics,
    Metrics,
    RunRecord,
    RunStatus,
)


class ZoneVariance(BaseModel):
    """Standard deviation (population) of the K repetitions of a zone."""

    citta: str
    zona: str
    std: MetricValues
    n_reps: int  # valid repetitions (OK) used for mean/std
    n_dropped: int  # excluded repetitions (everything that is not OK)
    n_fallback: int  # of which FALLBACK (subset of n_dropped), reliability


class FoldedArm(BaseModel):
    """Outcome of the fold of an arm: mean-record per zone + variance per zone.

    ``mean_records`` has EXACTLY one record per (citta, zona) -> consumable
    by compare.compare_records without violating the "one run per zone" constraint.
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
    # quality_vacuous (#240) is NOT propagated/averaged here: it stays the default
    # None of Metrics, even if one or more valid repetitions were vacuous. There is
    # no declared aggregation rule for a boolean over K
    # repetitions (all vacuous? at least one? majority?) and picking one without
    # an explicit decision would be arbitrary. compare.py::_record_quality_vacuous
    # treats None as "data not available" and falls back on has_narrative for
    # these mean-records, so compare-repeated does not regress: the signal
    # is simply less precise here than on the single-run path, by
    # construction, not because of a bug.
    n = len(valid)
    return Metrics(
        grounding=sum(r.metrics.grounding for r in valid) / n,
        hallucination=sum(r.metrics.hallucination for r in valid) / n,
        # latency rounded to int = precision at which latency is
        # compared/reported (section 2.3 of the spec). In the multi-zone case the
        # cross-zone mean (compare._mean) however starts from these values ALREADY
        # rounded per-zone, not from the raw latencies: the resulting
        # deviation is sub-ms, irrelevant for the verdict when the
        # latencies of the arms differ appreciably.
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


def _representative_narrative(group: list[RunRecord]) -> str:
    """Narrative of ONE repetition of the group, not an average (#231).

    The average of several texts does not exist, but the AVAILABILITY of text does,
    and it is
    information that the mean-record must keep: downstream it is what
    tells apart a zone on which the arm produced prose (gradable) from one on
    which it stayed mute, where ``grounding``/``hallucination`` are 1.0/0.0 by
    vacuity. Zeroing it would make EVERY folded arm read as mute.

    Returns the text of the first repetition that produced one; empty string
    if none spoke. It is not a statistical sample: it serves to answer
    "did this zone produce a narrative?", not to represent its content.
    """
    return next((rec.narrativa for rec in group if rec.narrativa.strip()), "")


def _consistent_poi_in_prompt(
    citta: str, zona: str, valid: list[RunRecord]
) -> list[str] | None:
    """The POIs in the prompt common to the valid repetitions of a zone (#349).

    The POI selection is deterministic, so the K repetitions of one
    experiment have the same set: if they diverge, or if some have the field
    and others not (pre-#349 records mixed with new ones), the experiment
    mixes different versions of the prompt. Raises :class:`ValueError`, like
    ``compare_records`` on malformed input (duplicate zones, diverging
    ``snapshot_id``) and like the harness on legacy records (#165.4): a warning
    would still leave an average that mixes a repetition with 9-12 POIs and two
    with 20, and downstream nobody would tell it apart. All without the field =
    ``None``,
    and the comparison will say that parity is not verifiable.
    """
    values = [r.poi_nel_prompt for r in valid]
    if all(v is None for v in values):
        return None
    present = [v for v in values if v is not None]
    if len(present) < len(values):
        raise ValueError(
            f"fold_arm: ripetizioni di {citta}/{zona} con e senza poi_nel_prompt "
            "(record precedenti a #349 mescolati a record nuovi): non si mediano "
            "prompt con insiemi di POI diversi; rigirare tutte le ripetizioni"
        )
    if len({frozenset(v) for v in present}) > 1:
        raise ValueError(
            f"fold_arm: ripetizioni di {citta}/{zona} con poi_nel_prompt diversi: "
            "non si mediano prompt con insiemi di POI diversi; rigirare tutte le "
            "ripetizioni con lo stesso codice"
        )
    return present[0]


def _mean_record(
    source: RunRecord,
    metrics: Metrics,
    status: RunStatus,
    narrativa: str = "",
    istat_metrics: IstatMetrics | None = None,
    poi_nel_prompt: list[str] | None = None,
) -> RunRecord:
    """Mean-record of a zone; reuses the provenance (snapshot_id) of ``source``.

    ``narrativa`` is representative, not averaged: see
    :func:`_representative_narrative`. ``istat_metrics`` (#345) is instead the
    SUM of the K repetitions (``istat_metrics.sum_istat_metrics``): counts,
    not an average, so summing it across repetitions stays correct.

    Of the record's ISTAT fields ONLY ``istat_metrics`` is folded:
    ``istat_frasi_scartate``, ``narrativa_grezza``, ``frasi_escluse_m1`` and
    ``frasi_escluse_senza_voce`` stay at the defaults (0 and ``None``) on the
    mean-record. The removed sentences and those excluded from M1 (#369, #378) are
    already
    counted in the sum (``IstatMetrics.frasi_scartabili``,
    ``IstatMetrics.frasi_escluse_m1``,
    ``IstatMetrics.frasi_escluse_senza_voce``), and the raw text, like the
    narrative, is not averaged; whoever wants them per repetition reads them on the
    repetition records.
    A zone whose repetitions have ISTAT metrics of different versions is not
    folded: the sum rejects it.

    ``poi_nel_prompt`` (#349) is the single one of the valid repetitions
    (:func:`_consistent_poi_in_prompt`): it serves ``compare_records`` to
    verify POI parity between the arms also on the K path.
    """
    return RunRecord(
        run_id=f"{source.experiment}__{source.citta}__{source.zona}__mean".lower(),
        experiment=source.experiment,
        citta=source.citta,
        zona=source.zona,
        mode=source.mode,
        model_id=source.model_id,
        status=status,
        metrics=metrics,
        narrativa=narrativa,
        n_poi=source.n_poi,
        poi_nel_prompt=poi_nel_prompt,
        istat_metrics=istat_metrics,
        provenance=source.provenance,
    )


def fold_arm(records: list[RunRecord]) -> FoldedArm:
    """Fold the K repetitions per zone into mean-record + variance.

    Raises :class:`ValueError` if ``records`` is empty, or if the valid repetitions
    of a zone have different or mixed present/absent ``poi_nel_prompt``
    (#349, :func:`_consistent_poi_in_prompt`).
    """
    if not records:
        raise ValueError("fold_arm: nessun record da ripiegare")
    groups = _group_by_zone(records)
    mean_records: list[RunRecord] = []
    variances: list[ZoneVariance] = []
    for citta, zona in sorted(groups):
        group = groups[(citta, zona)]
        # Only OK enters mean/std, expressed positively and not as a list of
        # statuses to exclude: a new value of the enum (``HARNESS_ERROR``)
        # is born with zeroed metrics, and a forgotten exclusion list would
        # make it be averaged as if it were a measure. The criterion is verified
        # on the whole enum in ``test_repeat.py``.
        valid = [r for r in group if r.status is RunStatus.OK]
        n_fallback = sum(1 for r in group if r.status == RunStatus.FALLBACK)
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
                    n_fallback=n_fallback,
                )
            )
            continue
        # The mean-record takes status OK even if the group contained FALLBACK:
        # the fallbacks are already excluded from mean/std (#163) and their signal
        # travels via ZoneVariance.n_fallback (made visible in the report, #165.3).
        # Changing the status here would alter the zone selection of compare_records.
        mean_records.append(
            _mean_record(
                valid[0],
                _mean_metrics(valid),
                RunStatus.OK,
                _representative_narrative(valid),
                sum_istat_metrics(r.istat_metrics for r in valid),
                _consistent_poi_in_prompt(citta, zona, valid),
            )
        )
        variances.append(
            ZoneVariance(
                citta=citta,
                zona=zona,
                std=_std_metrics(valid),
                n_reps=len(valid),
                n_dropped=n_dropped,
                n_fallback=n_fallback,
            )
        )
    return FoldedArm(mean_records=mean_records, variances=variances)
