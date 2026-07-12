"""Test dell'entry point di cattura CLI: ``eval/__main__._capture`` (#110).

Guida DIRETTAMENTE ``_capture`` (non solo l'helper ``capturing_source``) per:
- M1: lo snapshot è scritto alla chiave (citta, zona) risolta da
  ``make_snapshot_key``, mai a una chiave che includa mode/model;
- M2: cattura idempotente (skip-if-exists) + flag ``--force`` per ri-catturare.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import crime_risk_analyzer.eval.__main__ as eval_main
from crime_risk_analyzer.eval.harness import make_snapshot_key
from crime_risk_analyzer.eval.schema import (
    ExperimentConfig,
    Mode,
    ModelChoice,
    RunCase,
)
from crime_risk_analyzer.eval.snapshots import (
    load_snapshot,
    save_snapshot,
    snapshot_path,
)
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.overpass_client import Poi

_capture = eval_main._capture  # pyright: ignore[reportPrivateUsage]


def _fake_geocode_fixture(zona: str, citta: str) -> dict[str, object]:
    return {"lat": 41.0, "lon": 12.0, "bbox": Bbox(41.0, 12.0, 41.1, 12.1)}


def _sample_pois() -> list[Poi]:
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


def _sentinel_pois() -> list[Poi]:
    """Contenuto distinto: se _capture ri-cattura, sovrascrive questo."""
    return [
        Poi(
            id="SENTINEL",
            name="Sentinella",
            lat=0.0,
            lon=0.0,
            osm_tags="x=y",
            terminus_class="Bank",
            citta="Roma",
        )
    ]


def _write_config(
    tmp_path: Path,
    citta: str,
    zona: str,
    *,
    mode: Mode = "baseline",
    model: ModelChoice = "claude",
    name: str = "cfg",
) -> Path:
    """Config su file JSON, come farebbe il CLI reale (default: baseline, no LLM)."""
    cfg = ExperimentConfig(
        name="ablation",
        mode=mode,
        model=model,
        cases=[RunCase(citta=citta, zona=zona)],
    )
    path = tmp_path / f"{name}.json"
    path.write_text(cfg.model_dump_json(), encoding="utf-8")
    return path


@pytest.fixture
def capture_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isola _capture dalla rete: geocode finto + executor finto (baseline, no LLM)."""
    from crime_risk_analyzer.rag import retrieval
    from tests.eval._doubles import FakeProfiler

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    monkeypatch.setattr(eval_main, "get_executor", lambda: FakeProfiler())


async def test_capture_writes_at_citta_zona_key(
    tmp_path: Path, capture_env: None
) -> None:
    """M1: _capture scrive lo snapshot alla chiave (citta, zona), MAI a una
    chiave che includa mode/model (blinda contro reintroduzione di make_run_id)."""
    calls = 0

    async def fake_live(bbox: Bbox, citta: str) -> list[Poi]:
        nonlocal calls
        calls += 1
        return _sample_pois()

    config_path = _write_config(tmp_path, "Roma", "Centro Storico")
    await _capture(config_path, tmp_path, poi_source=fake_live)

    expected = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro Storico"))
    assert expected.exists()
    assert load_snapshot(expected) == _sample_pois()
    assert calls == 1
    # Un solo file, alla chiave (citta, zona): nessuna variante con mode/model.
    assert list((tmp_path / "snapshots").glob("*.json")) == [expected]
    assert "baseline" not in expected.name
    assert "claude" not in expected.name


async def test_capture_skips_if_snapshot_exists(
    tmp_path: Path, capture_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    """M2: due _capture sulla stessa (citta, zona) → query live UNA sola volta e
    file NON sovrascritto (skip-if-exists), con log di riuso."""
    calls = 0

    async def counting_live(bbox: Bbox, citta: str) -> list[Poi]:
        nonlocal calls
        calls += 1
        return _sample_pois()

    config_path = _write_config(tmp_path, "Roma", "Centro")
    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))

    await _capture(config_path, tmp_path, poi_source=counting_live)
    assert calls == 1
    # Sentinella: una ri-cattura la sovrascriverebbe.
    save_snapshot(path, _sentinel_pois())

    with caplog.at_level(logging.INFO):
        await _capture(config_path, tmp_path, poi_source=counting_live)

    assert calls == 1  # nessuna seconda query live
    assert load_snapshot(path) == _sentinel_pois()  # file NON sovrascritto
    assert any("riuso" in r.getMessage().lower() for r in caplog.records)


async def test_capture_force_recaptures(tmp_path: Path, capture_env: None) -> None:
    """M2: --force ignora lo skip-if-exists e ri-cattura (sovrascrive lo snapshot)."""
    calls = 0

    async def counting_live(bbox: Bbox, citta: str) -> list[Poi]:
        nonlocal calls
        calls += 1
        return _sample_pois()

    config_path = _write_config(tmp_path, "Roma", "Centro")
    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))

    await _capture(config_path, tmp_path, poi_source=counting_live)
    assert calls == 1
    save_snapshot(path, _sentinel_pois())

    await _capture(config_path, tmp_path, force=True, poi_source=counting_live)
    assert calls == 2  # ri-cattura live
    assert load_snapshot(path) == _sample_pois()  # snapshot sovrascritto (fresco)


async def test_capture_analyze_arms_share_key(
    tmp_path: Path, capture_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M1: due bracci analyze (claude, groq) catturano alla STESSA chiave (citta,
    zona); il secondo riusa lo snapshot del primo → nessuna query live divergente
    (anti-confondimento #33, ramo analyze di _capture)."""
    from tests.eval._doubles import FakeLLMClient

    def _fake_eval_client(config: ExperimentConfig) -> FakeLLMClient:
        return FakeLLMClient()

    monkeypatch.setattr(eval_main, "build_llm_eval_client", _fake_eval_client)

    calls = 0

    async def counting_live(bbox: Bbox, citta: str) -> list[Poi]:
        nonlocal calls
        calls += 1
        return _sample_pois()

    cfg_claude = _write_config(
        tmp_path, "Roma", "Centro", mode="analyze", model="claude", name="claude"
    )
    cfg_groq = _write_config(
        tmp_path, "Roma", "Centro", mode="analyze", model="groq", name="groq"
    )

    await _capture(cfg_claude, tmp_path, poi_source=counting_live)
    await _capture(cfg_groq, tmp_path, poi_source=counting_live)

    expected = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))
    # Un solo file per (citta, zona): claude e groq NON divergono.
    assert list((tmp_path / "snapshots").glob("*.json")) == [expected]
    assert calls == 1  # il secondo braccio ha riusato lo snapshot (skip-if-exists)
