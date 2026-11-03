"""Fold of the K repetitions per arm (#157), entirely offline."""

from __future__ import annotations

import pytest

from crime_risk_analyzer.eval.repeat import fold_arm
from crime_risk_analyzer.eval.schema import (
    Metrics,
    Provenance,
    RunRecord,
    RunStatus,
)
from crime_risk_analyzer.llm.client import GROQ_MODEL


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
    poi_nel_prompt: list[str] | None = None,
) -> RunRecord:
    return RunRecord(
        run_id=f"exp__{citta}__{zona}__analyze__groq__rep{rep:02d}".lower(),
        experiment="exp",
        citta=citta,
        zona=zona,
        mode="analyze",
        model_id=GROQ_MODEL,
        status=status,
        metrics=Metrics(
            grounding=grounding,
            hallucination=hallucination,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        ),
        narrativa="x",
        n_poi=1,
        poi_nel_prompt=poi_nel_prompt,
        provenance=Provenance(
            code_commit="c",
            ontology_hash="o",
            snapshot_id=f"{citta}__{zona}".lower(),
            model_id=GROQ_MODEL,
            prompt_hash="p",
            temperature=0.0,
            seed=rep,
            experiment="exp",
        ),
    )


def test_fold_computes_mean_and_population_std_per_metric() -> None:
    """3 repetitions -> correct population mean/std; latency rounded to int."""
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
    assert mr.metrics.latency_ms == 1100  # rounded int
    assert mr.metrics.cost_usd == pytest.approx(0.0006)
    assert mr.status == RunStatus.OK
    zv = folded.variances[0]
    # pstdev([0.6,0.7,0.8]) = sqrt(0.02/3) ≈ 0.081649658
    assert zv.std.grounding == pytest.approx(0.081649658)
    assert zv.std.latency_ms == pytest.approx(81.6496580927726)
    assert zv.n_reps == 3
    assert zv.n_dropped == 0


def test_fold_k1_has_zero_std() -> None:
    """K=1 -> std = 0 on every axis, mean = single value."""
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


def test_fold_leaves_quality_vacuous_unset_on_mean_record() -> None:
    """#240: no declared aggregation rule for a boolean over K
    repetitions (documented in ``_mean_metrics``) -- the mean-record stays
    ``None``, even when the single valid repetition was vacuous."""
    folded = fold_arm(
        [
            _rec(
                "Milano",
                "Duomo",
                rep=0,
                grounding=1.0,
                hallucination=0.0,
                latency_ms=900,
                cost_usd=0.0,
            )
        ]
    )
    assert folded.mean_records[0].metrics.quality_vacuous is None


@pytest.mark.parametrize(
    "status", [s for s in RunStatus if s is not RunStatus.OK], ids=lambda s: s.value
)
def test_every_non_ok_repetition_is_dropped_from_the_mean(status: RunStatus) -> None:
    """The fold drops EVERY failure status, not just today's two.

    Parametrized on the enum: a new value (``HARNESS_ERROR``) carries zeroed
    metrics by construction, and including it in the mean of K repetitions
    would halve the grounding of a zone because of an instrumentation bug, without
    anything signalling it.
    """
    recs = [
        _rec(
            "Napoli",
            "Piazza Garibaldi",
            rep=0,
            grounding=1.0,
            hallucination=0.0,
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
            status=status,
        ),
    ]
    folded = fold_arm(recs)
    assert folded.mean_records[0].metrics.grounding == pytest.approx(1.0)
    assert folded.variances[0].n_reps == 1
    assert folded.variances[0].n_dropped == 1


def test_fold_excludes_error_reps_and_counts_dropped() -> None:
    """ERROR repetitions do not enter mean/std; n_dropped counts them."""
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
    assert mr.metrics.grounding == pytest.approx(0.7)  # mean of 0.6 and 0.8, not 0.0
    zv = folded.variances[0]
    assert zv.n_reps == 2
    assert zv.n_dropped == 1


def test_fold_all_error_zone_becomes_error_record() -> None:
    """If ALL repetitions are ERROR -> mean-record status=ERROR, zero metrics."""
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
    # all 4 metrics zeroed (not just latency_ms).
    assert mr.metrics.grounding == 0.0
    assert mr.metrics.hallucination == 0.0
    assert mr.metrics.latency_ms == 0
    assert mr.metrics.cost_usd == 0.0
    zv = folded.variances[0]
    assert zv.n_reps == 0
    assert zv.n_dropped == 2
    # all 4 std axes zeroed.
    assert zv.std.grounding == 0.0
    assert zv.std.hallucination == 0.0
    assert zv.std.latency_ms == 0.0
    assert zv.std.cost_usd == 0.0


def test_fold_rounds_latency_mean_to_nearest_int() -> None:
    """Non-integer mean (1000.333...) -> latency_ms=1000 (round, not floor/crash).

    Locks that round() is functional: Metrics.latency_ms:int would raise on a
    fractional float if round() were removed or replaced by an int() cast.
    """
    recs = [
        _rec(
            "Roma",
            "Colosseo",
            rep=r,
            grounding=0.5,
            hallucination=0.5,
            latency_ms=lat,
            cost_usd=0.001,
        )
        for r, lat in enumerate([1000, 1000, 1001])
    ]
    mr = fold_arm(recs).mean_records[0]
    assert mr.metrics.latency_ms == 1000
    assert isinstance(mr.metrics.latency_ms, int)


def test_fold_preserves_snapshot_id_for_iso_input() -> None:
    """The mean-record inherits the snapshot_id of the repetitions (iso-input
    compare)."""
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


def test_fold_excludes_fallback_reps_and_counts_them() -> None:
    """FALLBACK repetitions do not enter mean/std; n_fallback counts them."""
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
            grounding=1.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.FALLBACK,
        ),
        _rec(
            "Roma",
            "Colosseo",
            rep=2,
            grounding=1.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.FALLBACK,
        ),
    ]
    folded = fold_arm(recs)
    mr = folded.mean_records[0]
    assert mr.status == RunStatus.OK
    # mean of the OK repetition ONLY, not of the "perfect" fallbacks.
    assert mr.metrics.grounding == pytest.approx(0.6)
    assert mr.metrics.hallucination == pytest.approx(0.4)
    zv = folded.variances[0]
    assert zv.n_reps == 1
    assert zv.n_dropped == 2
    assert zv.n_fallback == 2


def test_fold_all_fallback_zone_becomes_error_record() -> None:
    """All-FALLBACK zone -> ERROR mean-record (excluded downstream); n_fallback
    counts."""
    recs = [
        _rec(
            "Torino",
            "Porta Nuova",
            rep=r,
            grounding=1.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.FALLBACK,
        )
        for r in range(2)
    ]
    folded = fold_arm(recs)
    assert folded.mean_records[0].status == RunStatus.ERROR
    zv = folded.variances[0]
    assert zv.n_reps == 0
    assert zv.n_dropped == 2
    assert zv.n_fallback == 2


def test_fold_counts_error_and_fallback_separately() -> None:
    """n_dropped = ERROR + FALLBACK; n_fallback isolates the FALLBACK ones only."""
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
            grounding=1.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.FALLBACK,
        ),
    ]
    zv = fold_arm(recs).variances[0]
    assert zv.n_reps == 1
    assert zv.n_dropped == 2
    assert zv.n_fallback == 1


def test_fold_sums_the_istat_metrics_of_the_repetitions() -> None:
    from crime_risk_analyzer.eval.schema import IstatMetrics

    def _m(confronti_coerenti: int) -> IstatMetrics:
        return IstatMetrics(
            versione=2,
            cifre_totali=2,
            cifre_istat=1,
            confronti_totali=2,
            confronti_coerenti=confronti_coerenti,
            frasi_scartabili=0,
            voci_fornite=1,
            voci_citate=1,
            frasi_istat=1,
            frasi_istat_con_luogo=1,
            direzioni_totali=0,
            direzioni_coerenti=0,
            corrispondenze_non_dichiarate=0,
            numeri_in_lettere=0,
        )

    a = _rec(
        "Roma",
        "Colosseo",
        rep=0,
        grounding=1,
        hallucination=0,
        latency_ms=1,
        cost_usd=0,
    )
    b = _rec(
        "Roma",
        "Colosseo",
        rep=1,
        grounding=1,
        hallucination=0,
        latency_ms=1,
        cost_usd=0,
    )
    folded = fold_arm(
        [
            a.model_copy(update={"istat_metrics": _m(2)}),
            b.model_copy(update={"istat_metrics": _m(1)}),
        ]
    )
    summed = folded.mean_records[0].istat_metrics
    assert summed is not None
    assert (
        summed.versione,
        summed.cifre_totali,
        summed.cifre_istat,
        summed.confronti_totali,
        summed.confronti_coerenti,
    ) == (2, 4, 2, 4, 3)


# --- #349: the POIs in the prompt are not averaged across different repetitions ---


def _rep(
    rep: int, poi: list[str] | None, status: RunStatus = RunStatus.OK
) -> RunRecord:
    return _rec(
        "Roma",
        "Colosseo",
        rep=rep,
        grounding=0.5,
        hallucination=0.5,
        latency_ms=1000,
        cost_usd=0.0,
        status=status,
        poi_nel_prompt=poi,
    )


def test_fold_carries_the_poi_in_prompt_of_consistent_repetitions() -> None:
    """Same set in every repetition: the mean-record carries it, so
    ``compare_records`` can verify the parity also on the K path."""
    folded = fold_arm([_rep(0, ["1", "2"]), _rep(1, ["2", "1"]), _rep(2, ["1", "2"])])
    assert folded.mean_records[0].poi_nel_prompt == ["1", "2"]


def test_fold_refuses_repetitions_mixing_present_and_missing_poi() -> None:
    """One new repetition (with ``poi_nel_prompt``) and two old ones (without):
    averaging them would mix prompts with 9-12 POIs and prompts with 20, without
    warnings."""
    with pytest.raises(ValueError, match="Roma/Colosseo"):
        fold_arm([_rep(0, ["1", "2"]), _rep(1, None), _rep(2, None)])


def test_fold_refuses_repetitions_with_different_poi_sets() -> None:
    with pytest.raises(ValueError, match="poi_nel_prompt"):
        fold_arm([_rep(0, ["1", "2"]), _rep(1, ["1", "2", "3"])])


def test_fold_ignores_the_poi_of_dropped_repetitions() -> None:
    """A FALLBACK does not enter the mean (no generation, ``poi_nel_prompt``
    None): it does not count for POI consistency either."""
    folded = fold_arm(
        [_rep(0, ["1"]), _rep(1, None, status=RunStatus.FALLBACK), _rep(2, ["1"])]
    )
    assert folded.mean_records[0].poi_nel_prompt == ["1"]


def test_fold_keeps_legacy_repetitions_without_poi_as_none() -> None:
    """All old: no error, the mean-record stays without POIs and the
    comparison will say that parity is not verifiable."""
    folded = fold_arm([_rep(0, None), _rep(1, None)])
    assert folded.mean_records[0].poi_nel_prompt is None
