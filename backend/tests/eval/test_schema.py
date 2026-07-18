import pytest
from pydantic import ValidationError

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
    deserialized = RunRecord.model_validate_json(dumped)
    assert deserialized.run_id == rec.run_id
    assert deserialized.status is RunStatus.OK
    assert deserialized.annotazione_manuale is None


def test_metrics_bounds_validation() -> None:
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


def test_experiment_config_rejects_wrong_case_mode() -> None:
    """Vocabolario controllato (``Mode`` Literal): il casing e' vincolante.
    ``"Baseline"`` (capitalizzato) NON e' ``"baseline"`` → ValidationError."""
    with pytest.raises(ValidationError):
        ExperimentConfig(
            name="ablation",
            mode="Baseline",  # pyright: ignore[reportArgumentType]
            model="claude",
            cases=[RunCase(citta="Roma", zona="Centro")],
        )


def test_experiment_config_rejects_wrong_case_model() -> None:
    """Vocabolario controllato (``ModelChoice`` Literal): ``"Claude"`` capitalizzato
    e' fuori dal vocabolario minuscolo → ValidationError."""
    with pytest.raises(ValidationError):
        ExperimentConfig(
            name="ablation",
            mode="baseline",
            model="Claude",  # pyright: ignore[reportArgumentType]
            cases=[RunCase(citta="Roma", zona="Centro")],
        )


def test_experiment_config_rejects_unknown_mode() -> None:
    """Un valore fuori dal vocabolario (livello inventato) e' rifiutato."""
    with pytest.raises(ValidationError):
        ExperimentConfig(
            name="ablation",
            mode="dry-run",  # pyright: ignore[reportArgumentType]
            model="claude",
            cases=[RunCase(citta="Roma", zona="Centro")],
        )
