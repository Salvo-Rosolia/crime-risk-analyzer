"""Test dell'harness di esecuzione esperimenti (#34, iso-input #110)."""

from __future__ import annotations

from pathlib import Path

import pytest

from crime_risk_analyzer.eval.harness import (
    make_run_id,
    make_snapshot_key,
    run_experiment,
)
from crime_risk_analyzer.eval.schema import ExperimentConfig, RunCase, RunStatus
from crime_risk_analyzer.eval.snapshots import (
    capturing_source,
    load_snapshot,
    save_snapshot,
    snapshot_path,
)
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.overpass_client import Poi


def _fake_geocode_fixture(zona: str, citta: str) -> dict[str, object]:
    return {"lat": 41.0, "lon": 12.0, "bbox": Bbox(41.0, 12.0, 41.1, 12.1)}


def _sample_pois() -> list[Poi]:
    """Fixture POI minimale condivisa dai test dell'harness."""
    return [
        Poi(
            id="1",
            name="Banca A",
            lat=41.0,
            lon=12.0,
            osm_tags="amenity=bank",
            terminus_class="Bank",
            citta="Roma",
        )
    ]


def test_make_run_id_deterministic() -> None:
    a = make_run_id("ablation", "Roma", "Centro Storico", "analyze", "claude")
    b = make_run_id("ablation", "Roma", "Centro Storico", "analyze", "claude")
    assert a == b
    assert " " not in a


def test_make_run_id_includes_repetition_index() -> None:
    """Ripetizioni distinte producono run_id distinti; default rep=0 → __rep00."""
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
    """--repeat 3 → 3 record e 3 JSON distinti per caso (nessuna sovrascrittura)."""
    cfg = ExperimentConfig(
        name="exp",
        mode="analyze",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    save_snapshot(
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
    # Snapshot pre-salvato per ogni caso → replay offline.
    cfg = ExperimentConfig(
        name="exp",
        mode="analyze",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    rid = make_run_id("exp", "Roma", "Centro", "analyze", "claude")
    # Snapshot chiavato per (citta, zona), condiviso dai bracci comparativi (#110).
    save_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )

    # geocode mockato (replay ignora il bbox ma retrieve lo richiede)
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeLLMClient, FakeProfiler  # vedi nota sotto

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


async def test_run_experiment_rejects_non_positive_repeat(tmp_path: Path) -> None:
    """repeat < 1 → ValueError (niente esperimento vuoto in silenzio)."""
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
    """run_experiment con mode='baseline' e llm_client=None → status=ok (fix T9).

    Baseline non chiama il provider LLM: passare None non deve fallire.
    """
    cfg = ExperimentConfig(
        name="base",
        mode="baseline",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    # Snapshot chiavato per (citta, zona) (#110): baseline usa la stessa fixture.
    save_snapshot(
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
    """Un caso senza snapshot → status=error; l'esperimento continua."""
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

    # Solo (Roma, Centro) ha lo snapshot: chiave per (citta, zona) (#110).
    rid_ok = make_run_id("iso", "Roma", "Centro", "analyze", "claude")
    save_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    # Il secondo caso (Prati) non ha snapshot → FileNotFoundError → status=error.
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


def test_make_snapshot_key_ignores_mode_and_model() -> None:
    """La chiave snapshot dipende SOLO da (citta, zona) (#110).

    I bracci comparativi (analyze/claude, analyze/groq, baseline) condividono la
    stessa fixture POI; il run_id resta invece per-run (varia con mode/model).
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
    """Chiave canonica: case e whitespace normalizzati (#110).

    'Milano' e ' milano ' non devono generare snapshot separati.
    """
    assert make_snapshot_key("Milano", "Centro") == make_snapshot_key(
        " milano ", "CENTRO"
    )
    assert make_snapshot_key("Roma", "Centro Storico") == "roma__centro-storico"


async def test_comparative_arms_share_one_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #110: model/mode diversi sulla stessa (citta, zona) → STESSO snapshot.

    Una fixture salvata una volta è rigiocata dai tre bracci (analyze/claude,
    analyze/groq, baseline): nessuna divergenza di POI tra i bracci.
    """
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    key = make_snapshot_key("Roma", "Centro")
    save_snapshot(snapshot_path(tmp_path, key), _sample_pois())

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

    # Nessun braccio va in errore per snapshot mancante: leggono tutti la stessa.
    assert rec_claude.status == RunStatus.OK
    assert rec_groq.status == RunStatus.OK
    assert rec_baseline.status == RunStatus.OK
    # Provenienza auditabile: tutti citano lo stesso snapshot (citta, zona).
    assert rec_claude.provenance.snapshot_id == key
    assert rec_groq.provenance.snapshot_id == key
    assert rec_baseline.provenance.snapshot_id == key
    # Iso-input: stessa fixture → stesso conteggio POI per ogni braccio.
    assert rec_claude.n_poi == rec_groq.n_poi == rec_baseline.n_poi == 1
    # Un solo file snapshot per (citta, zona): nessuna copia per-braccio.
    assert list((tmp_path / "snapshots").glob("*.json")) == [
        snapshot_path(tmp_path, key)
    ]
    # N1: le LISTE di POI risolte dai tre bracci sono IDENTICHE (stesso input, non
    # solo stessa cardinalità), caricate dallo snapshot citato in provenance.
    pois_by_arm = [
        load_snapshot(snapshot_path(tmp_path, rec.provenance.snapshot_id))
        for rec in (rec_claude, rec_groq, rec_baseline)
    ]
    assert pois_by_arm[0] == pois_by_arm[1] == pois_by_arm[2] == _sample_pois()


async def test_capture_once_replayed_by_other_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #110: cattura live UNA volta per (citta, zona); l'altro braccio rigioca.

    Con model/mode diversi non parte una seconda query live: la fixture è condivisa.
    """
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeProfiler

    calls = 0

    async def counting_inner(bbox: Bbox, citta: str) -> list[Poi]:
        nonlocal calls
        calls += 1
        return _sample_pois()

    # Braccio A (analyze/claude) cattura live → scrive lo snapshot alla chiave.
    key = make_snapshot_key("Roma", "Centro")
    capture = capturing_source(snapshot_path(tmp_path, key), inner=counting_inner)
    await capture(Bbox(41.0, 12.0, 41.1, 12.1), "Roma")
    assert calls == 1

    # Braccio B (baseline/groq) rigioca dallo stesso snapshot: nessuna nuova query.
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
    assert calls == 1  # nessuna seconda cattura live
    assert records[0].provenance.snapshot_id == key


def _legacy_record(experiment: str, citta: str, zona: str):
    from crime_risk_analyzer.eval.schema import (
        Metrics,
        Provenance,
        RunRecord,
        RunStatus,
    )

    # run_id in formato PRE-#157: nessun suffisso __rep.
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

    # record __rep dello stesso esperimento: NON deve far scattare la guardia.
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
    # legacy ma di ALTRO esperimento: irrilevante per "exp".
    write_record(tmp_path, _legacy_record("other", "Milano", "Duomo"))
    guard_no_legacy_runs(tmp_path, "exp")  # non solleva
