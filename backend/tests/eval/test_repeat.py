"""Fold delle K ripetizioni per braccio (#157), interamente offline."""

from __future__ import annotations

import pytest

from crime_risk_analyzer.eval.repeat import fold_arm
from crime_risk_analyzer.eval.schema import (
    Metrics,
    Provenance,
    RunRecord,
    RunStatus,
)


def _rec(
    citta: str,
    zona: str,
    *,
    rep: int,
    grounding: float,
    hallucination: float,
    latency_ms: int,
    cost_usd: float,
    status: RunStatus = RunStatus.OK,
) -> RunRecord:
    return RunRecord(
        run_id=f"exp__{citta}__{zona}__analyze__groq__rep{rep:02d}".lower(),
        experiment="exp",
        citta=citta,
        zona=zona,
        mode="analyze",
        model_id="llama-3.3-70b-versatile",
        status=status,
        metrics=Metrics(
            grounding=grounding,
            hallucination=hallucination,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        ),
        narrativa="x",
        n_poi=1,
        provenance=Provenance(
            code_commit="c",
            ontology_hash="o",
            snapshot_id=f"{citta}__{zona}".lower(),
            model_id="llama-3.3-70b-versatile",
            prompt_hash="p",
            temperature=0.0,
            seed=rep,
            experiment="exp",
        ),
    )


def test_fold_computes_mean_and_population_std_per_metric() -> None:
    """3 ripetizioni → media/std di popolazione corrette; latency arrotondata a int."""
    recs = [
        _rec(
            "Roma",
            "Colosseo",
            rep=0,
            grounding=0.6,
            hallucination=0.4,
            latency_ms=1000,
            cost_usd=0.0004,
        ),
        _rec(
            "Roma",
            "Colosseo",
            rep=1,
            grounding=0.7,
            hallucination=0.3,
            latency_ms=1100,
            cost_usd=0.0006,
        ),
        _rec(
            "Roma",
            "Colosseo",
            rep=2,
            grounding=0.8,
            hallucination=0.2,
            latency_ms=1200,
            cost_usd=0.0008,
        ),
    ]
    folded = fold_arm(recs)
    assert len(folded.mean_records) == 1
    mr = folded.mean_records[0]
    assert mr.metrics.grounding == pytest.approx(0.7)
    assert mr.metrics.hallucination == pytest.approx(0.3)
    assert mr.metrics.latency_ms == 1100  # int arrotondato
    assert mr.metrics.cost_usd == pytest.approx(0.0006)
    assert mr.status == RunStatus.OK
    zv = folded.variances[0]
    # pstdev([0.6,0.7,0.8]) = sqrt(0.02/3) ≈ 0.081649658
    assert zv.std.grounding == pytest.approx(0.081649658)
    assert zv.std.latency_ms == pytest.approx(81.6496580927726)
    assert zv.n_reps == 3
    assert zv.n_dropped == 0


def test_fold_k1_has_zero_std() -> None:
    """K=1 → std = 0 su ogni asse, media = valore singolo."""
    folded = fold_arm(
        [
            _rec(
                "Milano",
                "Duomo",
                rep=0,
                grounding=0.5,
                hallucination=0.5,
                latency_ms=900,
                cost_usd=0.0005,
            )
        ]
    )
    zv = folded.variances[0]
    assert (
        zv.std.grounding,
        zv.std.hallucination,
        zv.std.latency_ms,
        zv.std.cost_usd,
    ) == (0.0, 0.0, 0.0, 0.0)
    assert folded.mean_records[0].metrics.grounding == pytest.approx(0.5)
    assert zv.n_reps == 1


def test_fold_excludes_error_reps_and_counts_dropped() -> None:
    """Le ripetizioni ERROR non entrano in media/std; n_dropped le conta."""
    recs = [
        _rec(
            "Napoli",
            "Piazza Garibaldi",
            rep=0,
            grounding=0.6,
            hallucination=0.4,
            latency_ms=1000,
            cost_usd=0.0004,
        ),
        _rec(
            "Napoli",
            "Piazza Garibaldi",
            rep=1,
            grounding=0.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.ERROR,
        ),
        _rec(
            "Napoli",
            "Piazza Garibaldi",
            rep=2,
            grounding=0.8,
            hallucination=0.2,
            latency_ms=1200,
            cost_usd=0.0008,
        ),
    ]
    folded = fold_arm(recs)
    mr = folded.mean_records[0]
    assert mr.status == RunStatus.OK
    assert mr.metrics.grounding == pytest.approx(0.7)  # media di 0.6 e 0.8, non 0.0
    zv = folded.variances[0]
    assert zv.n_reps == 2
    assert zv.n_dropped == 1


def test_fold_all_error_zone_becomes_error_record() -> None:
    """Se TUTTE le ripetizioni sono ERROR → record-media status=ERROR, metriche zero."""
    recs = [
        _rec(
            "Torino",
            "Porta Nuova",
            rep=0,
            grounding=0.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.ERROR,
        ),
        _rec(
            "Torino",
            "Porta Nuova",
            rep=1,
            grounding=0.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.ERROR,
        ),
    ]
    folded = fold_arm(recs)
    mr = folded.mean_records[0]
    assert mr.status == RunStatus.ERROR
    assert mr.metrics.latency_ms == 0
    assert folded.variances[0].n_reps == 0
    assert folded.variances[0].n_dropped == 2


def test_fold_preserves_snapshot_id_for_iso_input() -> None:
    """Il record-media eredita lo snapshot_id delle ripetizioni (iso-input compare)."""
    recs = [
        _rec(
            "Roma",
            "Colosseo",
            rep=r,
            grounding=0.6,
            hallucination=0.4,
            latency_ms=1000,
            cost_usd=0.0004,
        )
        for r in range(3)
    ]
    mr = fold_arm(recs).mean_records[0]
    assert mr.provenance.snapshot_id == "roma__colosseo"


def test_fold_empty_raises() -> None:
    with pytest.raises(ValueError):
        fold_arm([])
