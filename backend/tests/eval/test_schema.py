import pytest
from pydantic import ValidationError

from crime_risk_analyzer.eval.schema import (
    ExperimentConfig,
    Metrics,
    Mode,
    Provenance,
    RunCase,
    RunRecord,
    RunStatus,
)
from crime_risk_analyzer.llm.client import GROQ_MODEL
from crime_risk_analyzer.rag.generation import RiskModel


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
    assert deserialized.risk_models == []


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
    """Controlled vocabulary (``Mode`` Literal): the casing is binding.
    ``"Baseline"`` (capitalized) is NOT ``"baseline"`` -> ValidationError."""
    with pytest.raises(ValidationError):
        ExperimentConfig(
            name="ablation",
            mode="Baseline",  # pyright: ignore[reportArgumentType]
            model="claude",
            cases=[RunCase(citta="Roma", zona="Centro")],
        )


def test_experiment_config_rejects_wrong_case_model() -> None:
    """Controlled vocabulary (``ModelChoice`` Literal): capitalized ``"Claude"``
    is outside the lowercase vocabulary -> ValidationError."""
    with pytest.raises(ValidationError):
        ExperimentConfig(
            name="ablation",
            mode="baseline",
            model="Claude",  # pyright: ignore[reportArgumentType]
            cases=[RunCase(citta="Roma", zona="Centro")],
        )


def test_experiment_config_rejects_unknown_mode() -> None:
    """A value outside the vocabulary (invented level) is rejected."""
    with pytest.raises(ValidationError):
        ExperimentConfig(
            name="ablation",
            mode="dry-run",  # pyright: ignore[reportArgumentType]
            model="claude",
            cases=[RunCase(citta="Roma", zona="Centro")],
        )


def test_experiment_config_accepts_the_no_ontology_arm() -> None:
    """#236: third arm of the vocabulary -- same LLM, prompt without ontology.

    Without the value in ``Mode`` there would be no way to CONFIGURE the variant
    that isolates the C3 contribution: `analyze` vs `baseline` compares the presence
    of the LLM, not that of the ontology.
    """
    cfg = ExperimentConfig(
        name="ablation-no-ontology-groq",
        mode="no_ontology_prompt",
        model="groq",
        cases=[RunCase(citta="Roma", zona="Colosseo")],
    )
    assert cfg.mode == "no_ontology_prompt"


def test_no_ontology_arm_rejects_the_grouped_context_format() -> None:
    """The per-class format (#273) does not exist in the ablated arm.

    Grouping by class serves to not repeat the set of hazards of every
    point: without hazards there is nothing to group. Accepting it silently
    would write a ``Provenance`` that describes a prompt never built.
    """
    with pytest.raises(ValidationError):
        ExperimentConfig(
            name="ablation-no-ontology-groq",
            mode="no_ontology_prompt",
            model="groq",
            cases=[RunCase(citta="Roma", zona="Colosseo")],
            context_format="per_classe",
        )


def test_experiment_config_defaults_to_the_historical_context_format() -> None:
    """#273: the variant is opt-in, so no existing experiment moves."""
    cfg = ExperimentConfig(
        name="exp", mode="analyze", model="groq", cases=[RunCase(citta="R", zona="C")]
    )
    assert cfg.context_format == "per_poi"


def test_provenance_labels_a_legacy_record_as_per_poi() -> None:
    """A record written before #273 does not have the field, and must be read for what
    it is.

    The default is not a convenience: those runs WERE produced with the per-POI
    format, so labelling them so is the only truthful reading. Without a default
    the mandatory field would make the existing corpus unreadable.

    The ``model_id`` stays the Llama literal, not ``GROQ_MODEL``: it is the model
    that those legacy runs really used, before Groq removed it from the
    catalogue (#316). Replacing it would make the fixture a false period record.
    """
    legacy = {
        "code_commit": "abc",
        "ontology_hash": "def",
        "snapshot_id": "roma__centro",
        "model_id": "llama-3.3-70b-versatile",
        "prompt_hash": "h",
        "temperature": 0.0,
        "seed": 0,
        "experiment": "exp",
    }
    assert Provenance.model_validate(legacy).context_format == "per_poi"


def test_provenance_records_the_grouped_format() -> None:
    """Two runs that differ only by the format must be distinguishable.

    ``prompt_hash`` covers only the system prompt, and #273 changes the user_content:
    without this field the two arms of an A/B would be indistinguishable in the
    results.
    """
    prov = Provenance(
        code_commit="abc",
        ontology_hash="def",
        snapshot_id="roma__centro",
        model_id=GROQ_MODEL,
        prompt_hash="h",
        temperature=0.0,
        seed=0,
        experiment="exp",
        context_format="per_classe",
    )
    assert prov.context_format == "per_classe"
    assert "per_classe" in prov.model_dump_json()


def test_run_record_carries_risk_models() -> None:
    rec = RunRecord(
        run_id="r",
        experiment="exp",
        citta="Roma",
        zona="Centro",
        mode="analyze",
        model_id="claude-sonnet-4-6",
        status=RunStatus.OK,
        metrics=Metrics(grounding=1.0, hallucination=0.0, latency_ms=1, cost_usd=0.0),
        narrativa="x",
        n_poi=1,
        risk_models=[RiskModel(poi_id="node/1", poi="Banca A", risks=[])],
        provenance=Provenance(
            code_commit="a",
            ontology_hash="b",
            snapshot_id="s",
            model_id="m",
            prompt_hash="p",
            temperature=0.0,
            seed=0,
            experiment="exp",
        ),
    )
    assert rec.risk_models[0].poi_id == "node/1"


def test_run_record_risk_models_defaults_to_empty_list() -> None:
    rec = RunRecord(
        run_id="r",
        experiment="exp",
        citta="Roma",
        zona="Centro",
        mode="analyze",
        model_id="m",
        status=RunStatus.ERROR,
        metrics=Metrics(grounding=0.0, hallucination=0.0, latency_ms=0, cost_usd=0.0),
        narrativa="",
        n_poi=0,
        provenance=Provenance(
            code_commit="a",
            ontology_hash="b",
            snapshot_id="s",
            model_id="m",
            prompt_hash="",
            temperature=0.0,
            seed=0,
            experiment="exp",
        ),
    )
    assert rec.risk_models == []


@pytest.mark.parametrize("mode", ["baseline", "no_ontology_prompt"])
def test_istat_only_in_the_full_arm(mode: Mode) -> None:
    """#345 spec 4.9: ISTAT makes sense only where the ontology is in the prompt and
    there is the LLM."""
    with pytest.raises(ValidationError, match="istat"):
        ExperimentConfig(name="x", mode=mode, model="groq", cases=[], istat=True)


def test_istat_off_by_default_and_old_records_valid() -> None:
    cfg = ExperimentConfig(name="x", mode="analyze", model="groq", cases=[])
    assert cfg.istat is False
    old = {
        "code_commit": "c",
        "ontology_hash": "o",
        "snapshot_id": "s",
        "model_id": "m",
        "prompt_hash": "p",
        "temperature": 0.0,
        "seed": 0,
        "experiment": "e",
    }
    prov = Provenance.model_validate(old)
    assert (prov.istat, prov.istat_versione_dati) == (False, None)
