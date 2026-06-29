from crime_risk_analyzer.eval.schema import (
    ExperimentConfig,
    Metrics,
    Provenance,
    RunCase,
    RunRecord,
    RunStatus,
)


def test_run_record_roundtrip() -> None:
    rec = RunRecord(
        run_id="exp__roma__centro__analyze__claude",
        experiment="exp",
        citta="Roma",
        zona="Centro",
        mode="analyze",
        model_id="claude-sonnet-4-6",
        status=RunStatus.OK,
        metrics=Metrics(
            grounding=1.0, hallucination=0.0, latency_ms=120, cost_usd=0.003
        ),
        narrativa="Analisi.",
        n_poi=3,
        provenance=Provenance(
            code_commit="abc123",
            ontology_hash="def456",
            snapshot_id="snap1",
            model_id="claude-sonnet-4-6",
            prompt_hash="ph",
            temperature=0.0,
            seed=0,
            experiment="exp",
        ),
    )
    dumped = rec.model_dump_json()
    assert RunRecord.model_validate_json(dumped).run_id == rec.run_id
    assert rec.annotazione_manuale is None


def test_metrics_bounds_validation() -> None:
    import pytest

    with pytest.raises(ValueError):
        Metrics(grounding=1.5, hallucination=0.0, latency_ms=1, cost_usd=0.0)


def test_experiment_config() -> None:
    cfg = ExperimentConfig(
        name="ablation",
        mode="baseline",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    assert cfg.cases[0].zona == "Centro"
