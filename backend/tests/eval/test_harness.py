"""Tests of the experiment execution harness (#34, iso-input #110)."""

from __future__ import annotations

from pathlib import Path

import pytest

from crime_risk_analyzer.eval.harness import (
    _record_from_response,  # pyright: ignore[reportPrivateUsage]
    make_run_id,
    make_snapshot_key,
    run_case,
    run_experiment,
)
from crime_risk_analyzer.eval.schema import (
    ExperimentConfig,
    Mode,
    RunCase,
    RunRecord,
    RunStatus,
)
from crime_risk_analyzer.eval.snapshots import (
    capturing_source,
    load_snapshot,
    snapshot_path,
)
from crime_risk_analyzer.llm.client import GROQ_MODEL
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.vocab import ConfidenceSummary
from crime_risk_analyzer.orchestrator import AnalyzeResponse, GeoZone, PoiOut
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.rag.generation import RiskModel
from tests.eval._doubles import default_llm_response, write_snapshot


def _fake_geocode_fixture(zona: str, citta: str) -> dict[str, object]:
    return {"lat": 41.0, "lon": 12.0, "bbox": Bbox(41.0, 12.0, 41.1, 12.1)}


def _sample_pois() -> list[Poi]:
    """Minimal POI fixture shared by the harness tests."""
    return [
        Poi(
            id="1",
            name="Banca A",
            lat=41.0,
            lon=12.0,
            osm_tags="amenity=bank",
            ontology_class="Bank",
            citta="Roma",
        )
    ]


def test_make_run_id_deterministic() -> None:
    a = make_run_id("ablation", "Roma", "Centro Storico", "analyze", "claude")
    b = make_run_id("ablation", "Roma", "Centro Storico", "analyze", "claude")
    assert a == b
    assert " " not in a


def test_make_run_id_includes_repetition_index() -> None:
    """Distinct repetitions produce distinct run_ids; default rep=0 -> __rep00."""
    r0 = make_run_id("exp", "Roma", "Centro", "analyze", "claude")
    r0_explicit = make_run_id("exp", "Roma", "Centro", "analyze", "claude", 0)
    r1 = make_run_id("exp", "Roma", "Centro", "analyze", "claude", 1)
    assert r0 == r0_explicit
    assert r0.endswith("__rep00")
    assert r1.endswith("__rep01")
    assert r0 != r1


async def test_run_experiment_repeat_writes_k_records_no_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--repeat 3 -> 3 records and 3 distinct JSONs per case (no overwriting)."""
    cfg = ExperimentConfig(
        name="exp",
        mode="analyze",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    write_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    records = await run_experiment(
        cfg,
        executor=FakeProfiler(),
        llm_client=FakeLLMClient(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
        repeat=3,
    )
    assert len(records) == 3
    run_ids = {r.run_id for r in records}
    assert len(run_ids) == 3
    written = list((tmp_path / "runs").glob("*.json"))
    assert len(written) == 3


async def test_run_experiment_writes_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pre-saved snapshot for every case -> offline replay.
    cfg = ExperimentConfig(
        name="exp",
        mode="analyze",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    rid = make_run_id("exp", "Roma", "Centro", "analyze", "claude")
    # Snapshot keyed by (citta, zona), shared by the comparative arms (#110).
    write_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )

    # mocked geocode (replay ignores the bbox but retrieve requires it)
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeLLMClient, FakeProfiler  # see note below

    records = await run_experiment(
        cfg,
        executor=FakeProfiler(),
        llm_client=FakeLLMClient(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )
    assert len(records) == 1
    assert records[0].status == RunStatus.OK
    assert (tmp_path / "runs" / f"{rid}.json").exists()
    assert records[0].metrics.latency_ms >= 0


# --- #267: the run that replays a snapshot reports ITS provenance, not
# just the commit of whoever runs it --- (prevents two different selection
# policies from ending up in the same experiment with no signal)


async def test_run_experiment_reports_the_snapshot_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = ExperimentConfig(
        name="exp",
        mode="analyze",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    write_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )

    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    records = await run_experiment(
        cfg,
        executor=FakeProfiler(),
        llm_client=FakeLLMClient(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )
    prov = records[0].provenance
    assert prov.snapshot_catturato_il is not None
    assert prov.snapshot_configurazione_canonica is not None


async def test_run_experiment_warns_on_snapshot_without_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A pre-#241 fixture (bare list) stays replayable but no longer
    silently: the run logs a warning instead of treating it like any other."""
    import json

    cfg = ExperimentConfig(
        name="exp",
        mode="analyze",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([dict(p) for p in _sample_pois()]), encoding="utf-8")

    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    with caplog.at_level("WARNING"):
        records = await run_experiment(
            cfg,
            executor=FakeProfiler(),
            llm_client=FakeLLMClient(),
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )

    assert records[0].provenance.snapshot_catturato_il is None
    assert records[0].provenance.snapshot_configurazione_canonica is None
    assert any("#267" in rec.message for rec in caplog.records)
    assert any("nessuna provenienza" in rec.message for rec in caplog.records)


async def test_run_experiment_does_not_warn_on_missing_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A snapshot NEVER captured is not a provenance case to report: it
    is a different failure (isolation #252), not to be confused with a warning
    of diverging configuration before even the real error."""
    cfg = ExperimentConfig(
        name="exp",
        mode="analyze",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    # No snapshot written for (Roma, Centro).

    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    with caplog.at_level("WARNING"):
        records = await run_experiment(
            cfg,
            executor=FakeProfiler(),
            llm_client=FakeLLMClient(),
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )

    assert records[0].status == RunStatus.ERROR
    assert not any("#267" in rec.message for rec in caplog.records)


async def test_run_experiment_ignores_wrong_type_catturato_il(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provenance with a non-string ``catturato_il`` (malformed external datum)
    must not make the validation of ``Provenance`` fail, and with it the run."""
    import json

    cfg = ExperimentConfig(
        name="exp",
        mode="analyze",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))
    write_snapshot(path, _sample_pois())
    written = json.loads(path.read_text(encoding="utf-8"))
    written["provenienza"]["catturato_il"] = 12345  # wrong type
    path.write_text(json.dumps(written), encoding="utf-8")

    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    records = await run_experiment(
        cfg,
        executor=FakeProfiler(),
        llm_client=FakeLLMClient(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )

    assert records[0].status == RunStatus.OK
    assert records[0].provenance.snapshot_catturato_il is None


async def test_run_experiment_rejects_non_positive_repeat(tmp_path: Path) -> None:
    """repeat < 1 -> ValueError (no silently empty experiment)."""
    from tests.eval._doubles import FakeProfiler

    cfg = ExperimentConfig(
        name="x",
        mode="baseline",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    with pytest.raises(ValueError):
        await run_experiment(
            cfg,
            executor=FakeProfiler(),
            llm_client=None,
            results_dir=tmp_path,
            code_commit="c",
            ontology_hash="o",
            repeat=0,
        )


async def test_run_experiment_baseline_no_llm_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_experiment with mode='baseline' and llm_client=None -> status=ok (fix T9).

    Baseline does not call the LLM provider: passing None must not fail.
    """
    cfg = ExperimentConfig(
        name="base",
        mode="baseline",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    # Snapshot keyed by (citta, zona) (#110): baseline uses the same fixture.
    write_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )

    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeProfiler

    records = await run_experiment(
        cfg,
        executor=FakeProfiler(),
        llm_client=None,
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )
    assert len(records) == 1
    assert records[0].status == RunStatus.OK


async def test_run_experiment_error_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A case without snapshot -> status=error; the experiment continues."""
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    cfg = ExperimentConfig(
        name="iso",
        mode="analyze",
        model="claude",
        cases=[
            RunCase(citta="Roma", zona="Centro"),
            RunCase(citta="Roma", zona="Prati"),
        ],
    )

    # Only (Roma, Centro) has the snapshot: key by (citta, zona) (#110).
    rid_ok = make_run_id("iso", "Roma", "Centro", "analyze", "claude")
    write_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    # The second case (Prati) has no snapshot -> FileNotFoundError -> status=error.
    rid_err = make_run_id("iso", "Roma", "Prati", "analyze", "claude")

    records = await run_experiment(
        cfg,
        executor=FakeProfiler(),
        llm_client=FakeLLMClient(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )

    assert len(records) == 2
    assert records[0].status == RunStatus.OK
    assert records[1].status == RunStatus.ERROR
    assert (tmp_path / "runs" / f"{rid_ok}.json").exists()
    assert (tmp_path / "runs" / f"{rid_err}.json").exists()


async def test_run_case_does_not_mask_a_metrics_computation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``try`` covers the call to the model, not the downstream metrics.

    A ``model_id`` not in the price list (here: ``KeyError`` from ``pricing.cost_usd``)
    is a code/configuration bug, not a provider failure: it must
    propagate with its traceback instead of becoming a record
    ``status=ERROR`` with zeroed metrics, indistinguishable from "the model
    failed". In a live run the difference is everything: absorbing it would burn the
    day's Groq quota producing 100% ERROR records without a single
    traceback to read.

    It stays true even after ``run_experiment`` learned not to die on a
    broken case: the isolation is one level ABOVE (with traceback and a status
    of its own), not inside this ``try``. Putting it back here would close the
    wrong hole -- and this case would turn red.
    """
    from crime_risk_analyzer.llm.client import LLMResponse
    from crime_risk_analyzer.rag import retrieval
    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    write_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    unpriced_model_response = LLMResponse(
        text="Analisi: Banca A presenta rischio rapina.",
        llm_used="provider/modello-mai-prezzato",
        tokens_input=10,
        tokens_output=20,
        cache_hit=False,
        temperature=0.0,
        seed=0,
        prompt_hash="abc",
    )

    with pytest.raises(KeyError, match="modello-mai-prezzato"):
        await run_case(
            RunCase(citta="Roma", zona="Centro"),
            ExperimentConfig(
                name="exp",
                mode="analyze",
                model="groq",
                cases=[RunCase(citta="Roma", zona="Centro")],
            ),
            executor=FakeProfiler(),
            llm_client=FakeLLMClient(unpriced_model_response),
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )


async def test_run_experiment_rejects_at_once_an_arm_without_client(
    tmp_path: Path,
) -> None:
    """An impossible configuration stops BEFORE running, not case by case.

    The isolation serves the failures that concern ONE case. An arm with a model
    that lacks the client is not that: it would fail identically on all the cases and on
    all the repetitions, leaving N ``HARNESS_ERROR`` records on the ground that the
    comparison would then count as failed zones. There is nothing to save
    by continuing, and the error is known before starting.
    """
    from tests.eval._doubles import FakeProfiler

    with pytest.raises(ValueError, match="llm_client"):
        await run_experiment(
            ExperimentConfig(
                name="senza-client",
                mode="analyze",
                model="groq",
                cases=[RunCase(citta="Roma", zona="Centro")],
            ),
            executor=FakeProfiler(),
            llm_client=None,
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )

    assert not (tmp_path / "runs").exists(), "no record written: the run must not start"


async def test_run_experiment_isolates_a_configuration_error_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A case that blows up OUTSIDE the ``try`` of ``run_case`` does not bring down the
    run.

    The exception that the previous fix let propagate (``KeyError`` from the
    price list on an ``llm_used`` not in the list -- the versioned alias that Groq
    really reports) came out of ``run_case`` and reached the top: the whole
    experiment died on the FIRST case, losing all the following ones. In a live run
    with a daily quota it is the worst damage, because the quota consumed
    up to there does not come back.

    The broken case stays broken (no metric invented), but it is isolated: the
    other cases run, and its record says what it is.
    """
    from crime_risk_analyzer.llm.client import LLMResponse
    from crime_risk_analyzer.rag import retrieval
    from tests.eval._doubles import FakeProfiler, default_llm_response

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    for zona in ("Centro", "Prati"):
        write_snapshot(
            snapshot_path(tmp_path, make_snapshot_key("Roma", zona)), _sample_pois()
        )

    class _FirstCaseUnpriced:
        """First case: model id outside the price list -> KeyError in the metrics."""

        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            self.calls += 1
            if self.calls == 1:
                return default_llm_response().model_copy(
                    update={"llm_used": "provider/modello-mai-prezzato"}
                )
            return default_llm_response()

    cfg = ExperimentConfig(
        name="iso-harness",
        mode="analyze",
        model="groq",
        cases=[
            RunCase(citta="Roma", zona="Centro"),
            RunCase(citta="Roma", zona="Prati"),
        ],
    )

    with caplog.at_level("ERROR"):
        records = await run_experiment(
            cfg,
            executor=FakeProfiler(),
            llm_client=_FirstCaseUnpriced(),
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )

    assert len(records) == 2
    assert records[0].status == RunStatus.HARNESS_ERROR
    assert records[1].status == RunStatus.OK
    # Both records end up on disk: the run is complete and auditable.
    for zona in ("Centro", "Prati"):
        rid = make_run_id("iso-harness", "Roma", zona, "analyze", "groq")
        assert (tmp_path / "runs" / f"{rid}.json").exists()


async def test_a_configuration_error_does_not_go_unnoticed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Isolating is not silencing: the exception must be logged WITH its traceback.

    It is the half that makes the isolation acceptable. An ``except`` that just
    writes a marked record would reproduce the previous blocker moved by
    one level: the run would finish, but whoever reads the results would have no way of
    knowing that it was the code that broke and not the provider.
    """
    from crime_risk_analyzer.llm.client import LLMResponse
    from crime_risk_analyzer.rag import retrieval
    from tests.eval._doubles import FakeProfiler, default_llm_response

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    write_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )

    class _Unpriced:
        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            return default_llm_response().model_copy(
                update={"llm_used": "provider/modello-mai-prezzato"}
            )

    with caplog.at_level("ERROR"):
        await run_experiment(
            ExperimentConfig(
                name="log-harness",
                mode="analyze",
                model="groq",
                cases=[RunCase(citta="Roma", zona="Centro")],
            ),
            executor=FakeProfiler(),
            llm_client=_Unpriced(),
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )

    errors = [rec for rec in caplog.records if rec.levelname == "ERROR"]
    assert errors, "the isolated exception must stay visible in the logs"
    assert any(rec.exc_info is not None for rec in errors), (
        "without a traceback the log says something failed but not where"
    )
    assert any("Centro" in rec.getMessage() for rec in errors)


@pytest.mark.parametrize("mode", ["baseline", "analyze"])
async def test_run_does_not_geocode_when_replaying(
    mode: Mode, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run (replay): 0 geocode on BOTH branches (baseline/analyze), repeat>1 (#169).

    It also covers fail-if-removed on the analyze branch of ``run_case``: if the wiring
    of ``geo_source`` disappeared from the ``run_analysis`` call, the analyze branch
    would go back to geocoding live and this case would fail.
    """
    from crime_risk_analyzer.geocoding import GeoResult
    from crime_risk_analyzer.rag import retrieval

    calls = {"n": 0}

    def _boom(zona: str, citta: str) -> GeoResult:
        calls["n"] += 1
        raise AssertionError("the run must not geocode")

    monkeypatch.setattr(retrieval, "geocode_zone", _boom)

    # Pre-save ONLY the POI snapshot (no geo file exists in #169).
    key = make_snapshot_key("Roma", "Colosseo")
    write_snapshot(snapshot_path(tmp_path, key), _sample_pois())

    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    config = ExperimentConfig(
        name="exp",
        mode=mode,
        model="claude",
        cases=[RunCase(citta="Roma", zona="Colosseo")],
    )
    # analyze requires an llm_client (fake already used in the file); baseline does not.
    llm_client = FakeLLMClient() if mode == "analyze" else None

    records = await run_experiment(
        config,
        executor=FakeProfiler(),
        llm_client=llm_client,
        results_dir=tmp_path,
        code_commit="c",
        ontology_hash="o",
        repeat=2,
    )
    assert calls["n"] == 0
    # The test must not pass through an upstream error swallowed by run_case.
    assert all(r.status == RunStatus.OK for r in records)


def test_make_snapshot_key_ignores_mode_and_model() -> None:
    """The snapshot key depends ONLY on (citta, zona) (#110).

    The comparative arms (analyze/claude, analyze/groq, baseline) share the
    same POI fixture; the run_id instead stays per-run (varies with mode/model).
    """
    key = make_snapshot_key("Roma", "Centro Storico")
    assert key == make_snapshot_key("Roma", "Centro Storico")
    assert " " not in key
    rid_claude = make_run_id("ablation", "Roma", "Centro Storico", "analyze", "claude")
    rid_groq = make_run_id("ablation", "Roma", "Centro Storico", "analyze", "groq")
    rid_baseline = make_run_id(
        "ablation", "Roma", "Centro Storico", "baseline", "claude"
    )
    assert rid_claude != rid_groq != rid_baseline
    assert len({rid_claude, rid_groq, rid_baseline}) == 3


def test_make_snapshot_key_is_canonical() -> None:
    """Canonical key: case and whitespace normalized (#110).

    'Milano' and ' milano ' must not generate separate snapshots.
    """
    assert make_snapshot_key("Milano", "Centro") == make_snapshot_key(
        " milano ", "CENTRO"
    )
    assert make_snapshot_key("Roma", "Centro Storico") == "roma__centro-storico"


async def test_comparative_arms_share_one_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #110: different model/mode on the same (citta, zona) -> SAME snapshot.

    A fixture saved once is replayed by the three arms (analyze/claude,
    analyze/groq, baseline): no POI divergence between the arms.
    """
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    key = make_snapshot_key("Roma", "Centro")
    write_snapshot(snapshot_path(tmp_path, key), _sample_pois())

    cfg_claude = ExperimentConfig(
        name="ablation",
        mode="analyze",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    cfg_groq = ExperimentConfig(
        name="ablation",
        mode="analyze",
        model="groq",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    cfg_baseline = ExperimentConfig(
        name="ablation",
        mode="baseline",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )

    rec_claude = (
        await run_experiment(
            cfg_claude,
            executor=FakeProfiler(),
            llm_client=FakeLLMClient(),
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )
    )[0]
    rec_groq = (
        await run_experiment(
            cfg_groq,
            executor=FakeProfiler(),
            llm_client=FakeLLMClient(),
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )
    )[0]
    rec_baseline = (
        await run_experiment(
            cfg_baseline,
            executor=FakeProfiler(),
            llm_client=None,
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )
    )[0]

    # No arm goes in error for a missing snapshot: they all read the same one.
    assert rec_claude.status == RunStatus.OK
    assert rec_groq.status == RunStatus.OK
    assert rec_baseline.status == RunStatus.OK
    # Auditable provenance: all cite the same snapshot (citta, zona).
    assert rec_claude.provenance.snapshot_id == key
    assert rec_groq.provenance.snapshot_id == key
    assert rec_baseline.provenance.snapshot_id == key
    # Iso-input: same fixture -> same POI count for every arm.
    assert rec_claude.n_poi == rec_groq.n_poi == rec_baseline.n_poi == 1
    # A single snapshot file per (citta, zona): no per-arm copy.
    assert list((tmp_path / "snapshots").glob("*.json")) == [
        snapshot_path(tmp_path, key)
    ]
    # N1: the POI LISTS resolved by the three arms are IDENTICAL (same input, not
    # just same cardinality), loaded from the snapshot cited in provenance.
    pois_by_arm = [
        load_snapshot(snapshot_path(tmp_path, rec.provenance.snapshot_id))
        for rec in (rec_claude, rec_groq, rec_baseline)
    ]
    assert pois_by_arm[0] == pois_by_arm[1] == pois_by_arm[2] == _sample_pois()


async def test_capture_once_replayed_by_other_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #110: live capture ONCE per (citta, zona); the other arm replays.

    With different model/mode no second live query starts: the fixture is shared.
    """
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeProfiler

    calls = 0

    async def counting_inner(bbox: Bbox, citta: str) -> tuple[list[Poi], None]:
        nonlocal calls
        calls += 1
        return _sample_pois(), None

    # Arm A (analyze/claude) captures live -> writes the snapshot at the key.
    key = make_snapshot_key("Roma", "Centro")
    capture = capturing_source(snapshot_path(tmp_path, key), inner=counting_inner)
    await capture(Bbox(41.0, 12.0, 41.1, 12.1), "Roma")
    assert calls == 1

    # Arm B (baseline/groq) replays from the same snapshot: no new query.
    cfg_baseline = ExperimentConfig(
        name="ablation",
        mode="baseline",
        model="groq",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    records = await run_experiment(
        cfg_baseline,
        executor=FakeProfiler(),
        llm_client=None,
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )
    assert records[0].status == RunStatus.OK
    assert calls == 1  # no second live capture
    assert records[0].provenance.snapshot_id == key


async def test_no_ontology_arm_replays_the_snapshot_of_the_complete_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#236: the two arms of the C3 comparison run on the SAME POI snapshot.

    The ablated arm is not a second capture: the snapshot key stays
    ``(citta, zona)`` (#110), so the variable that changes between the arms is only
    the prompt. The test verifies together the two halves of the acceptance criterion:
    iso-input (same ``snapshot_id``, same POIs, a single snapshot file) and
    distinguishable provenance (different ``run_id``, ``mode`` and ``prompt_hash`` --
    the latter because the two arms send the model different system prompts).
    """
    import hashlib

    from crime_risk_analyzer.llm.client import LLMResponse
    from crime_risk_analyzer.models.risk import PoiRiskProfile
    from crime_risk_analyzer.rag import retrieval
    from tests.eval._doubles import FakeProfiler, default_llm_response

    class _HashingLLMClient:
        """Double that hashes the system prompt as the real client does (#114)."""

        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            self.calls.append((system_prompt, user_content))
            return default_llm_response().model_copy(
                update={
                    "prompt_hash": hashlib.sha256(system_prompt.encode()).hexdigest()
                }
            )

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    key = make_snapshot_key("Roma", "Centro")
    write_snapshot(snapshot_path(tmp_path, key), _sample_pois())
    profiler = FakeProfiler(
        {
            "Bank": PoiRiskProfile(
                ontology_class="Bank",
                hazards=["Bank_robbery"],
                sparql_paths=["Bank → havingHazard → Bank_robbery"],
            )
        }
    )

    full_client = _HashingLLMClient()
    ablated_client = _HashingLLMClient()
    full_rec = (
        await run_experiment(
            ExperimentConfig(
                name="ablation-analyze-groq",
                mode="analyze",
                model="groq",
                cases=[RunCase(citta="Roma", zona="Centro")],
            ),
            executor=profiler,
            llm_client=full_client,
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )
    )[0]
    ablated_rec = (
        await run_experiment(
            ExperimentConfig(
                name="ablation-no-ontology-groq",
                mode="no_ontology_prompt",
                model="groq",
                cases=[RunCase(citta="Roma", zona="Centro")],
            ),
            executor=profiler,
            llm_client=ablated_client,
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )
    )[0]

    assert full_rec.status == RunStatus.OK
    assert ablated_rec.status == RunStatus.OK
    # Iso-input: same fixture, a single captured file, same number of POIs.
    assert ablated_rec.provenance.snapshot_id == full_rec.provenance.snapshot_id == key
    assert ablated_rec.n_poi == full_rec.n_poi == 1
    assert list((tmp_path / "snapshots").glob("*.json")) == [
        snapshot_path(tmp_path, key)
    ]
    # Provenance: the two arms stay distinguishable in the results.
    assert ablated_rec.mode == "no_ontology_prompt"
    assert full_rec.mode == "analyze"
    assert ablated_rec.run_id != full_rec.run_id
    assert ablated_rec.provenance.prompt_hash != full_rec.provenance.prompt_hash
    # The isolated variable: the ontology reaches the prompt only in the full arm.
    assert "Bank_robbery" in full_client.calls[0][1]
    assert "Bank_robbery" not in ablated_client.calls[0][1]
    assert "  POI: Banca A (Bank)" in ablated_client.calls[0][1]


def _many_pois(n: int) -> list[Poi]:
    """Dense snapshot: enough points for a reduced budget to cut."""
    return [
        Poi(
            id=str(i),
            name=f"Banca {i:02d}",
            lat=41.0,
            lon=12.0,
            osm_tags="amenity=bank",
            ontology_class="Bank",
            citta="Roma",
        )
        for i in range(n)
    ]


async def test_no_ontology_arm_receives_the_complete_arm_prompt_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#349: the harness passes to the ablated arm the same parameters with which the
    full arm builds the prompt (budget, max_tokens, format,
    ISTAT switch), from a single point (``_run_budget``), and the two records
    save the SAME POIs in the prompt even when the budget really cuts.

    The budget is reduced going through the harness (monkeypatch of its single point of
    computation): a literal in one of the two calls would make the arms diverge and
    this test would see it. Only with ISTAT off: ``ExperimentConfig`` does not
    allow ``istat=True`` outside ``mode="analyze"`` (D6).
    """
    from crime_risk_analyzer.eval import harness
    from crime_risk_analyzer.rag import retrieval
    from crime_risk_analyzer.rag.generation import (
        DEFAULT_MAX_TOKENS,
        SYSTEM_PROMPT,
        _estimate_tokens,  # pyright: ignore[reportPrivateUsage]
    )
    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    seen: dict[str, dict[str, object]] = {}
    real = {
        "run_analysis": harness.run_analysis,
        "run_no_ontology_prompt": harness.run_no_ontology_prompt,
    }

    def _spy(name: str):  # noqa: ANN202 -- test wrapper
        async def _f(*args: object, **kwargs: object) -> object:
            seen[name] = kwargs
            return await real[name](*args, **kwargs)  # type: ignore[arg-type]

        return _f

    reduced_budget = _estimate_tokens(SYSTEM_PROMPT) + DEFAULT_MAX_TOKENS + 200

    def _reduced_budget(config: ExperimentConfig) -> tuple[int | None, int | None]:
        if config.mode == "baseline":
            return None, None
        return reduced_budget, DEFAULT_MAX_TOKENS

    monkeypatch.setattr(harness, "_run_budget", _reduced_budget)
    monkeypatch.setattr(harness, "run_analysis", _spy("run_analysis"))
    monkeypatch.setattr(
        harness, "run_no_ontology_prompt", _spy("run_no_ontology_prompt")
    )
    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    write_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _many_pois(12)
    )
    records: dict[str, RunRecord] = {}
    for mode in ("analyze", "no_ontology_prompt"):
        [records[mode]] = await run_experiment(
            ExperimentConfig(
                name=f"iso-{mode}",
                mode=mode,
                model="groq",
                cases=[RunCase(citta="Roma", zona="Centro")],
            ),
            executor=FakeProfiler(),
            llm_client=FakeLLMClient(),
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )

    keys = ("request_token_budget", "max_tokens", "context_format")
    full, ablated = seen["run_analysis"], seen["run_no_ontology_prompt"]
    assert {k: ablated[k] for k in keys} == {k: full[k] for k in keys}
    assert full["request_token_budget"] == reduced_budget
    assert ablated["istat_context_enabled"] is full["istat_context_enabled"] is False
    full_rec, ablated_rec = records["analyze"], records["no_ontology_prompt"]
    # An ablated arm in error would make the comparison above vacuous.
    assert full_rec.status is RunStatus.OK
    assert ablated_rec.status is RunStatus.OK
    assert full_rec.poi_nel_prompt is not None
    assert ablated_rec.poi_nel_prompt is not None
    assert set(ablated_rec.poi_nel_prompt) == set(full_rec.poi_nel_prompt)
    assert 0 < len(ablated_rec.poi_nel_prompt) < ablated_rec.n_poi == 12
    assert full_rec.provenance.request_token_budget == reduced_budget


async def test_baseline_record_has_no_poi_in_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#349: the baseline builds no prompt, so ``poi_nel_prompt`` is
    ``None`` like on the records prior to #349."""
    from crime_risk_analyzer.rag import retrieval
    from tests.eval._doubles import FakeProfiler

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    write_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    [rec] = await run_experiment(
        ExperimentConfig(
            name="base",
            mode="baseline",
            model="groq",
            cases=[RunCase(citta="Roma", zona="Centro")],
        ),
        executor=FakeProfiler(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )
    assert rec.status is RunStatus.OK
    assert rec.poi_nel_prompt is None


async def test_no_ontology_arm_is_not_a_vacuous_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The arm produces prose: the quality proxies have something to pronounce on.

    It is the defect that #236 closes with respect to ``baseline``, mute by
    construction: an arm without narrative makes ``grounding``/``hallucination`` fall
    into the vacuous branch and downstream the verdict is WITHHELD (#231).
    """
    from crime_risk_analyzer.eval.compare import has_narrative, is_vacuous_arm
    from crime_risk_analyzer.rag import retrieval
    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    write_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    records = await run_experiment(
        ExperimentConfig(
            name="no-onto",
            mode="no_ontology_prompt",
            model="groq",
            cases=[RunCase(citta="Roma", zona="Centro")],
        ),
        executor=FakeProfiler(),
        llm_client=FakeLLMClient(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )
    assert has_narrative(records[0])
    assert not is_vacuous_arm(records)


async def test_no_ontology_arm_is_measured_on_the_block_its_prompt_asks_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The record carries the ``mode``, and the ``mode`` decides what is measured.

    The ablated prompt asks for honesty's sake a ``[SINTESI-LLM]`` block: if
    the harness measured every arm on the ``[ONTOLOGIA]`` label, that
    arm would get 0.0/1.0 for NON-ATTRIBUTION on every run and the C3 comparison
    would be decided by the name of the label instead of the anchoring.
    """
    from crime_risk_analyzer.llm.client import LLMResponse
    from crime_risk_analyzer.rag import retrieval
    from crime_risk_analyzer.rag.no_ontology_generation import (
        LLM_SYNTHESIS_BLOCK_HEADER,
    )
    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    write_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    response = LLMResponse(
        text=(
            f"Sintesi della zona.\n\n{LLM_SYNTHESIS_BLOCK_HEADER}\n"
            "Banca A presenta rischio rapina."
        ),
        llm_used=GROQ_MODEL,
        tokens_input=10,
        tokens_output=20,
        cache_hit=False,
        temperature=0.0,
        seed=0,
        prompt_hash="abc",
    )
    records = await run_experiment(
        ExperimentConfig(
            name="no-onto",
            mode="no_ontology_prompt",
            model="groq",
            cases=[RunCase(citta="Roma", zona="Centro")],
        ),
        executor=FakeProfiler(),
        llm_client=FakeLLMClient(response),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )
    assert records[0].metrics.grounding == 1.0
    assert records[0].metrics.hallucination == 0.0


async def test_no_ontology_arm_requires_an_llm_client(tmp_path: Path) -> None:
    """Without a client the arm makes no sense: it is the arm WITH the LLM.

    The branch of ``run_case`` that raises is that of ``analyze``: if the new mode
    ended up by mistake in the baseline branch, the run would run without a model and
    would produce a second mute arm instead of the comparison sought.
    """
    from tests.eval._doubles import FakeProfiler

    with pytest.raises(ValueError, match="llm_client"):
        await run_case(
            RunCase(citta="Roma", zona="Centro"),
            ExperimentConfig(
                name="no-onto",
                mode="no_ontology_prompt",
                model="groq",
                cases=[RunCase(citta="Roma", zona="Centro")],
            ),
            executor=FakeProfiler(),
            llm_client=None,
            results_dir=tmp_path,
            code_commit="c",
            ontology_hash="o",
        )


def _legacy_record(experiment: str, citta: str, zona: str):
    from crime_risk_analyzer.eval.schema import (
        Metrics,
        Provenance,
        RunRecord,
        RunStatus,
    )

    # run_id in PRE-#157 format: no __rep suffix.
    return RunRecord(
        run_id=f"{experiment}__{citta}__{zona}__analyze__groq".lower(),
        experiment=experiment,
        citta=citta,
        zona=zona,
        mode="analyze",
        model_id="m",
        status=RunStatus.OK,
        metrics=Metrics(
            grounding=0.8, hallucination=0.2, latency_ms=1000, cost_usd=0.001
        ),
        narrativa="x",
        n_poi=1,
        provenance=Provenance(
            code_commit="c",
            ontology_hash="o",
            snapshot_id=f"{citta}__{zona}".lower(),
            model_id="m",
            prompt_hash="p",
            temperature=0.0,
            seed=0,
            experiment=experiment,
        ),
    )


def test_is_repeated_run_id() -> None:
    from crime_risk_analyzer.eval.harness import is_repeated_run_id, make_run_id

    assert is_repeated_run_id(
        make_run_id("e", "Roma", "Colosseo", "analyze", "groq", 0)
    )
    assert not is_repeated_run_id("e__roma__colosseo__analyze__groq")


def test_guard_no_legacy_runs_raises_on_legacy(tmp_path: Path) -> None:
    from crime_risk_analyzer.eval.harness import guard_no_legacy_runs, write_record

    write_record(tmp_path, _legacy_record("exp", "Roma", "Colosseo"))
    with pytest.raises(ValueError, match="legacy"):
        guard_no_legacy_runs(tmp_path, "exp")


def test_guard_no_legacy_runs_clean_stale_removes(tmp_path: Path) -> None:
    from crime_risk_analyzer.eval.harness import (
        guard_no_legacy_runs,
        legacy_run_paths,
        write_record,
    )

    p = write_record(tmp_path, _legacy_record("exp", "Roma", "Colosseo"))
    guard_no_legacy_runs(tmp_path, "exp", clean_stale=True)
    assert not p.exists()
    assert legacy_run_paths(tmp_path, "exp") == []


def test_guard_no_legacy_runs_ignores_repeated_and_other_experiments(
    tmp_path: Path,
) -> None:
    from crime_risk_analyzer.eval.harness import (
        guard_no_legacy_runs,
        make_run_id,
        write_record,
    )
    from crime_risk_analyzer.eval.schema import (
        Metrics,
        Provenance,
        RunRecord,
        RunStatus,
    )

    # __rep record of the same experiment: must NOT trigger the guard.
    rec = RunRecord(
        run_id=make_run_id("exp", "Roma", "Colosseo", "analyze", "groq", 0),
        experiment="exp",
        citta="Roma",
        zona="Colosseo",
        mode="analyze",
        model_id="m",
        status=RunStatus.OK,
        metrics=Metrics(
            grounding=0.8, hallucination=0.2, latency_ms=1000, cost_usd=0.001
        ),
        narrativa="x",
        n_poi=1,
        provenance=Provenance(
            code_commit="c",
            ontology_hash="o",
            snapshot_id="roma__colosseo",
            model_id="m",
            prompt_hash="p",
            temperature=0.0,
            seed=0,
            experiment="exp",
        ),
    )
    write_record(tmp_path, rec)
    # legacy but of ANOTHER experiment: irrelevant for "exp".
    write_record(tmp_path, _legacy_record("other", "Milano", "Duomo"))
    guard_no_legacy_runs(tmp_path, "exp")  # does not raise


def test_guard_no_legacy_runs_clean_stale_removes_only_target(tmp_path: Path) -> None:
    """--clean-stale removes ONLY the legacy ones of the target experiment.

    Data safety: a __rep record of the same experiment and a legacy of ANOTHER
    experiment must not be touched by the cleaning.
    """
    from crime_risk_analyzer.eval.harness import (
        guard_no_legacy_runs,
        legacy_run_paths,
        make_run_id,
        write_record,
    )
    from crime_risk_analyzer.eval.schema import (
        Metrics,
        Provenance,
        RunRecord,
        RunStatus,
    )

    # (a) legacy TARGET of the experiment "exp": must be removed.
    target = write_record(tmp_path, _legacy_record("exp", "Roma", "Colosseo"))
    # (b) __rep record of the same "exp": valid repetition, must NOT be touched.
    rep = RunRecord(
        run_id=make_run_id("exp", "Roma", "Colosseo", "analyze", "groq", 0),
        experiment="exp",
        citta="Roma",
        zona="Colosseo",
        mode="analyze",
        model_id="m",
        status=RunStatus.OK,
        metrics=Metrics(
            grounding=0.8, hallucination=0.2, latency_ms=1000, cost_usd=0.001
        ),
        narrativa="x",
        n_poi=1,
        provenance=Provenance(
            code_commit="c",
            ontology_hash="o",
            snapshot_id="roma__colosseo",
            model_id="m",
            prompt_hash="p",
            temperature=0.0,
            seed=0,
            experiment="exp",
        ),
    )
    rep_path = write_record(tmp_path, rep)
    # (c) legacy of ANOTHER experiment: out of scope, must NOT be touched.
    other = write_record(tmp_path, _legacy_record("other", "Milano", "Duomo"))

    guard_no_legacy_runs(tmp_path, "exp", clean_stale=True)

    assert not target.exists()  # (a) removed
    assert rep_path.exists()  # (b) intact
    assert other.exists()  # (c) intact
    assert legacy_run_paths(tmp_path, "exp") == []


async def test_run_experiment_propagates_and_records_the_context_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#273: the variant must reach the prompt AND end up in the record.

    If it reached the prompt without being recorded, an A/B between the two formats
    would produce indistinguishable records (``prompt_hash`` covers only the system
    prompt); if it were recorded without reaching the prompt, the record would lie.
    The test closes both sides.
    """
    from crime_risk_analyzer.llm.client import LLMResponse
    from tests.eval._doubles import FakeProfiler, default_llm_response

    seen: list[str] = []

    class _Recording:
        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            seen.append(user_content)
            return default_llm_response()

    write_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    records = await run_experiment(
        ExperimentConfig(
            name="exp",
            mode="analyze",
            model="groq",
            cases=[RunCase(citta="Roma", zona="Centro")],
            context_format="per_classe",
        ),
        executor=FakeProfiler(),
        llm_client=_Recording(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )

    assert records[0].provenance.context_format == "per_classe"
    assert "raggruppati per classe TERMINUS" in seen[0]


async def test_run_experiment_default_keeps_the_historical_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An experiment that does not name the format must not move by a byte."""
    from crime_risk_analyzer.llm.client import LLMResponse
    from tests.eval._doubles import FakeProfiler, default_llm_response

    seen: list[str] = []

    class _Recording:
        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            seen.append(user_content)
            return default_llm_response()

    write_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    records = await run_experiment(
        ExperimentConfig(
            name="exp",
            mode="analyze",
            model="groq",
            cases=[RunCase(citta="Roma", zona="Centro")],
        ),
        executor=FakeProfiler(),
        llm_client=_Recording(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )

    assert records[0].provenance.context_format == "per_poi"
    assert "POI RILEVANTI:" in seen[0]


def test_record_from_response_copies_risk_models() -> None:
    """_record_from_response copies risk_models from the response into the RunRecord."""
    from crime_risk_analyzer.rag.generation import Repro

    # Build a fake AnalyzeResponse with non-empty risk_models.
    risk_model = RiskModel(poi_id="node/1", poi="Banca A", risks=[])

    resp = AnalyzeResponse(
        citta="Roma",
        zona_normalizzata="Centro",
        poi=[],
        risk_models=[risk_model],
        narrativa="Analisi.",
        confidence_summary=ConfidenceSummary(verificato=0, da_confermare=0),
        llm_used="claude-sonnet-4-6",
        latenza_ms=100,
        repro=Repro(temperature=0.0, seed=0, prompt_hash="p"),
        cache_hit=False,
        contesto_hash="h",
        zona_geo=GeoZone(
            lat=41.0,
            lon=12.0,
            bbox_min_lat=40.9,
            bbox_min_lon=11.9,
            bbox_max_lat=41.1,
            bbox_max_lon=12.1,
        ),
    )

    # Call _record_from_response directly.
    record = _record_from_response(
        run_id="r",
        snapshot_id="s",
        config=ExperimentConfig(name="exp", mode="analyze", model="claude", cases=[]),
        case=RunCase(citta="Roma", zona="Centro"),
        model_id="claude-sonnet-4-6",
        resp=resp,
        code_commit="a",
        ontology_hash="b",
        snapshot_catturato_il=None,
        snapshot_configurazione_canonica=None,
    )

    # Verify that the record carries the risk_models.
    assert len(record.risk_models) == 1
    assert record.risk_models[0].poi_id == "node/1"


async def _run_case_istat(tmp_path: Path, text: str) -> RunRecord:
    """A case of the arm with ISTAT (Roma/Colosseo, one POI "Banca A") on which the
    fake model writes ``text``. #365: the bank robberies of the Municipality of Rome
    stay under the threshold of 20 crimes and do not enter the block; the thefts
    (Property_theft) do."""
    from crime_risk_analyzer.models.risk import PoiRiskProfile
    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    pois = [
        Poi(
            id="node/1",
            name="Banca A",
            lat=41.8902,
            lon=12.4922,
            osm_tags="amenity=bank",
            ontology_class="Bank",
            citta="Roma",
        )
    ]
    write_snapshot(snapshot_path(tmp_path, make_snapshot_key("Roma", "Colosseo")), pois)
    cfg = ExperimentConfig(
        name="istat",
        mode="analyze",
        model="groq",
        cases=[RunCase(citta="Roma", zona="Colosseo")],
        istat=True,
    )
    profiles = {
        "Bank": PoiRiskProfile(
            ontology_class="Bank",
            hazards=["Bank_robbery", "Property_theft"],
            sparql_paths=["Bank → havingHazard → Bank_robbery"],
        )
    }
    return await run_case(
        cfg.cases[0],
        cfg,
        executor=FakeProfiler(profiles),
        llm_client=FakeLLMClient(
            default_llm_response().model_copy(update={"text": text})
        ),
        results_dir=tmp_path,
        code_commit="c",
        ontology_hash="o",
    )


async def test_run_case_with_istat_writes_provenance_raw_text_and_metrics(
    tmp_path: Path,
) -> None:
    from crime_risk_analyzer.istat.data import istat_data

    istat = (
        "Secondo i dati ISTAT del Comune di Roma i furti hanno un tasso piu' alto "
        "di quello italiano e sono in calo"
    )
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nBanca A: rapina in banca. "
        f"{istat}.\nCirca 999 casi in piu'.\n"
    )
    rec = await _run_case_istat(tmp_path, text)
    assert rec.provenance.istat is True
    assert rec.provenance.istat_versione_dati == istat_data().versione
    assert rec.narrativa_grezza == text
    assert "999" not in rec.narrativa
    assert rec.istat_frasi_scartate == 1
    assert rec.istat_metrics is not None
    assert (rec.istat_metrics.versione, rec.istat_metrics.voci_fornite) == (4, 1)
    assert (rec.istat_metrics.frasi_istat, rec.istat_metrics.voci_citate) == (1, 1)
    # #369: the record says which sentences M1 did not measure, and how many.
    assert rec.frasi_escluse_m1 == [istat]
    assert rec.istat_metrics.frasi_escluse_m1 == 1
    assert (rec.metrics.grounding, rec.metrics.hallucination) == (0.5, 0.5)


async def test_run_case_with_istat_separates_excluded_without_item_of_the_prompt(
    tmp_path: Path,
) -> None:
    """#378: among the sentences excluded from M1 the record separates those that name
    no item of the ISTAT rows of the prompt, without touching M1."""
    thefts = "Secondo i dati ISTAT del Comune di Roma i furti sono in calo"
    kidnappings = (
        "Secondo i dati ISTAT del Comune di Roma i sequestri di persona sono in aumento"
    )
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nBanca A: rapina in banca. "
        f"{thefts}. {kidnappings}.\n"
    )
    rec = await _run_case_istat(tmp_path, text)
    assert rec.frasi_escluse_m1 == [thefts, kidnappings]
    assert rec.frasi_escluse_senza_voce == [kidnappings]
    assert rec.istat_metrics is not None
    assert rec.istat_metrics.frasi_escluse_m1 == 2
    assert rec.istat_metrics.frasi_escluse_senza_voce == 1
    assert (rec.metrics.grounding, rec.metrics.hallucination) == (1.0, 0.0)


async def test_run_case_with_istat_off_raw_text_equals_the_narrative(
    tmp_path: Path,
) -> None:
    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    write_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    cfg = ExperimentConfig(
        name="exp",
        mode="analyze",
        model="groq",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    rec = await run_case(
        cfg.cases[0],
        cfg,
        executor=FakeProfiler(),
        llm_client=FakeLLMClient(),
        results_dir=tmp_path,
        code_commit="c",
        ontology_hash="o",
    )
    assert rec.narrativa_grezza == rec.narrativa
    assert (rec.provenance.istat, rec.istat_metrics, rec.istat_frasi_scartate) == (
        False,
        None,
        0,
    )
    assert rec.frasi_escluse_m1 is None
    assert rec.frasi_escluse_senza_voce is None


async def test_m1_on_istat_record_grades_raw_text_without_excluded_istat_sentences(
    tmp_path: Path,
) -> None:
    """F10 (final review), #369: M1 on an ISTAT record is computed on the raw text
    without the ISTAT sentences that name neither a POI nor a risk, not on the filtered
    text nor on the whole raw text.

    The measured block has three sentences: one anchored (Banca A), one with an invented
    number without anchoring (removed by the filter but measured by M1) and one with an
    ISTAT figure (removed by the filter and excluded from M1). Only so 1 anchored out of
    2: the filtered would give 1/1, the whole raw text 1/3.
    """
    from crime_risk_analyzer.istat.data import istat_data
    from crime_risk_analyzer.rag.generation import (
        DEFAULT_MAX_TOKENS,
        DEFAULT_REQUEST_TOKEN_BUDGET,
    )

    data = istat_data()
    total = data.delitti.valore("058091", "TOT", data.delitti.anno)
    assert total is not None and total.delitti is not None
    # Without thousands separator: M1 splits the sentences at every period.
    figure = str(total.delitti)
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nBanca A: rapina in banca. "
        "Si stimano 999 episodi l'anno. "
        f"Nel Comune di Roma si contano {figure} delitti denunciati nel 2024.\n"
    )
    rec = await _run_case_istat(tmp_path, text)
    assert rec.istat_frasi_scartate == 2
    assert "999" not in rec.narrativa and figure not in rec.narrativa
    assert (rec.metrics.grounding, rec.metrics.hallucination) == (0.5, 0.5)
    # F8: the record says with which budget the request was built.
    assert rec.provenance.request_token_budget == DEFAULT_REQUEST_TOKEN_BUDGET
    assert rec.provenance.llm_max_tokens == DEFAULT_MAX_TOKENS


async def test_m1_on_istat_record_is_recomputed_from_the_record(tmp_path: Path) -> None:
    """#369: raw text, POIs, risks and excluded sentences saved in the record are enough
    to redo M1, and an ISTAT sentence that names a POI stays measured."""
    from crime_risk_analyzer.eval.metrics import (
        _anchors,  # pyright: ignore[reportPrivateUsage]
        _grounded,  # pyright: ignore[reportPrivateUsage]
        _measured_sentences,  # pyright: ignore[reportPrivateUsage]
    )

    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nBanca A: rapina in banca. "
        "Secondo l'ISTAT a Roma i furti sono in calo. La zona e' affollata. "
        "Secondo l'ISTAT a Roma i furti vicino a Banca A sono in calo.\n"
    )
    rec = await _run_case_istat(tmp_path, text)
    excluded = rec.frasi_escluse_m1
    assert excluded is not None
    assert excluded == ["Secondo l'ISTAT a Roma i furti sono in calo"]
    assert rec.narrativa_grezza is not None
    measured = _measured_sentences(rec.narrativa_grezza, rec.mode)
    for excluded_sentence in excluded:
        measured.remove(excluded_sentence)
    response = AnalyzeResponse.model_construct(
        poi=[PoiOut.model_construct(name=m.poi) for m in rec.risk_models],
        risk_models=rec.risk_models,
    )
    anchored = _grounded(measured, _anchors(response))
    assert rec.metrics.grounding == pytest.approx(len(anchored) / len(measured))
    assert rec.metrics.grounding == pytest.approx(2 / 3)


def test_vacuous_istat_record_declares_no_excluded_sentences() -> None:
    """Review #369: with ISTAT in the prompt but without POIs or risks M1 is vacuous.
    The record saves no excluded sentences and the report does not write «N frasi
    escluse»."""
    from crime_risk_analyzer.eval.compare import compare_records, to_markdown
    from tests.eval.test_metrics import (
        _resp_istat,  # pyright: ignore[reportPrivateUsage]
    )

    resp = _resp_istat(
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nBanca A: rapina in banca. "
        "Secondo l'ISTAT nel Comune di Roma i furti sono in calo.\n"
    ).model_copy(update={"poi": [], "risk_models": []})
    record = _record_from_response(
        run_id="r",
        snapshot_id="s",
        config=ExperimentConfig(
            name="istat", mode="analyze", model="groq", cases=[], istat=True
        ),
        case=RunCase(citta="Roma", zona="Centro"),
        model_id="m",
        resp=resp,
        code_commit="a",
        ontology_hash="b",
        snapshot_catturato_il=None,
        snapshot_configurazione_canonica=None,
    )
    assert record.metrics.quality_vacuous is True
    assert record.frasi_escluse_m1 == []
    assert record.frasi_escluse_senza_voce == []
    assert record.istat_metrics is not None
    assert record.istat_metrics.frasi_escluse_m1 == 0
    without = record.model_copy(update={"experiment": "base", "istat_metrics": None})
    md = to_markdown(
        compare_records([record], [without], label_a="istat", label_b="base")
    )
    assert "`istat`: 0 frasi escluse" in md


async def test_baseline_does_not_record_an_llm_budget(tmp_path: Path) -> None:
    """F8: the baseline arm does not call the LLM, the budget stays None."""
    from tests.eval._doubles import FakeProfiler

    write_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    cfg = ExperimentConfig(
        name="base",
        mode="baseline",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    rec = await run_case(
        cfg.cases[0],
        cfg,
        executor=FakeProfiler(),
        llm_client=None,
        results_dir=tmp_path,
        code_commit="c",
        ontology_hash="o",
    )
    assert (rec.provenance.request_token_budget, rec.provenance.llm_max_tokens) == (
        None,
        None,
    )


def _write_case_snapshots(tmp_path: Path, cases: list[RunCase]) -> None:
    for case in cases:
        write_snapshot(
            snapshot_path(tmp_path, make_snapshot_key(case.citta, case.zona)),
            _sample_pois(),
        )


async def _events_with_pause(
    tmp_path: Path, *, mode: Mode, **kwargs: object
) -> tuple[list[str], list[RunRecord]]:
    """Two cases x 2 repetitions; fake model and fake ``sleep`` write to the
    SAME list, so the real order of pauses and calls is seen."""
    from crime_risk_analyzer.llm.client import LLMResponse
    from tests.eval._doubles import FakeProfiler, default_llm_response

    events: list[str] = []

    class _RecordingModel:
        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            events.append("modello")
            return default_llm_response()

    async def _sleep(seconds: float) -> None:
        events.append(f"pausa {seconds}")

    cases = [RunCase(citta="Roma", zona="Centro"), RunCase(citta="Roma", zona="Prati")]
    _write_case_snapshots(tmp_path, cases)
    records = await run_experiment(
        ExperimentConfig(name="p", mode=mode, model="groq", cases=cases),
        executor=FakeProfiler(),
        llm_client=None if mode == "baseline" else _RecordingModel(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
        repeat=2,
        sleep=_sleep,
        **kwargs,  # type: ignore[arg-type]
    )
    return events, records


@pytest.mark.parametrize("mode", ["analyze", "no_ontology_prompt"])
async def test_run_experiment_pauses_before_every_call(
    mode: Mode, tmp_path: Path
) -> None:
    """#357: with the pause one waits before EVERY call to the model, first
    included (the two arms run as two commands in a row), in both arms
    that call the model, and all the calls really reach the model."""
    events, records = await _events_with_pause(tmp_path, mode=mode, pause_seconds=0.5)
    assert events == ["pausa 0.5", "modello"] * 4
    assert [r.status for r in records] == [RunStatus.OK] * 4


async def test_run_experiment_no_pause_by_default(tmp_path: Path) -> None:
    """Without the parameter (default 0): no wait, behaviour as before."""
    events, _ = await _events_with_pause(tmp_path, mode="analyze")
    assert events == ["modello"] * 4


async def test_run_experiment_baseline_does_not_wait(tmp_path: Path) -> None:
    """The baseline does not call the model: the pause has no reason to exist."""
    events, _ = await _events_with_pause(tmp_path, mode="baseline", pause_seconds=65)
    assert events == []


@pytest.mark.parametrize("pause", [-1.0, float("nan"), float("inf")])
async def test_run_experiment_rejects_invalid_pause(
    pause: float, tmp_path: Path
) -> None:
    """Negative or non-finite: ``nan`` would switch the pause off without warnings,
    ``inf`` would block the run after the first case."""
    from tests.eval._doubles import FakeProfiler

    cfg = ExperimentConfig(
        name="x",
        mode="baseline",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    with pytest.raises(ValueError, match="pause_seconds"):
        await run_experiment(
            cfg,
            executor=FakeProfiler(),
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
            pause_seconds=pause,
        )


async def test_run_experiment_announces_every_pause(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Every wait is in the log: a long run is not mistaken for a hang."""
    with caplog.at_level("WARNING", logger="crime_risk_analyzer.eval.harness"):
        await _events_with_pause(tmp_path, mode="analyze", pause_seconds=0.5)
    announcements = [r for r in caplog.records if "pausa di 0.5 s" in r.getMessage()]
    assert len(announcements) == 4
