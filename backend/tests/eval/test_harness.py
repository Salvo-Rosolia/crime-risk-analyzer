"""Test dell'harness di esecuzione esperimenti (#34)."""

from __future__ import annotations

from pathlib import Path

import pytest

from crime_risk_analyzer.eval.harness import make_run_id, run_experiment
from crime_risk_analyzer.eval.schema import ExperimentConfig, RunCase, RunStatus
from crime_risk_analyzer.eval.snapshots import save_snapshot


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
    save_snapshot(
        tmp_path / "snapshots" / f"{rid}.json",
        [
            {
                "id": "1",
                "name": "Banca A",
                "lat": 41.0,
                "lon": 12.0,
                "osm_tags": "amenity=bank",
                "terminus_class": "Bank",
                "citta": "Roma",
            }
        ],
    )  # type: ignore[arg-type]

    # geocode mockato (replay ignora il bbox ma retrieve lo richiede)
    from crime_risk_analyzer.models.geo import Bbox
    from crime_risk_analyzer.rag import retrieval

    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        return {"lat": 41.0, "lon": 12.0, "bbox": Bbox(41.0, 12.0, 41.1, 12.1)}

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode)

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
