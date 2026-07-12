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
