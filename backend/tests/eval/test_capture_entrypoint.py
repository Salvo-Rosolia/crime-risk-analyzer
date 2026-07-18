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
_snapshot_reusable = eval_main._snapshot_reusable  # pyright: ignore[reportPrivateUsage]


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


def test_snapshot_reusable_true_for_valid(tmp_path: Path) -> None:
    """Fix 1 (#148): uno snapshot esistente, non vuoto e JSON valido è riusabile."""
    path = tmp_path / "snap.json"
    save_snapshot(path, _sample_pois())
    assert _snapshot_reusable(path) is True


def test_snapshot_reusable_false_for_missing(tmp_path: Path) -> None:
    """Fix 1 (#148): un file inesistente non è riusabile."""
    assert _snapshot_reusable(tmp_path / "assente.json") is False


def test_snapshot_reusable_false_for_empty(tmp_path: Path) -> None:
    """Fix 1 (#148): un file vuoto (size 0) non è riusabile."""
    path = tmp_path / "snap.json"
    path.write_text("", encoding="utf-8")
    assert _snapshot_reusable(path) is False


def test_snapshot_reusable_false_for_corrupt(tmp_path: Path) -> None:
    """Fix 1 (#148): un file troncato/corrotto (JSON non parsabile) non è riusabile."""
    path = tmp_path / "snap.json"
    path.write_text("[{ troncato non json", encoding="utf-8")
    assert _snapshot_reusable(path) is False


async def test_capture_recaptures_when_snapshot_corrupt(
    tmp_path: Path, capture_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Fix 1 (#148): uno snapshot presente ma corrotto (JSON non parsabile) NON
    viene riusato in silenzio → _capture ri-cattura live e lo sovrascrive."""
    calls = 0

    async def counting_live(bbox: Bbox, citta: str) -> list[Poi]:
        nonlocal calls
        calls += 1
        return _sample_pois()

    config_path = _write_config(tmp_path, "Roma", "Centro")
    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[{ troncato non json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        await _capture(config_path, tmp_path, poi_source=counting_live)

    assert calls == 1  # ri-catturato, non saltato
    assert load_snapshot(path) == _sample_pois()  # sovrascritto con contenuto fresco
    assert any(
        "corrotto" in r.getMessage().lower() or "vuoto" in r.getMessage().lower()
        for r in caplog.records
    )


async def test_capture_recaptures_when_snapshot_empty(
    tmp_path: Path, capture_env: None
) -> None:
    """Fix 1 (#148): uno snapshot presente ma vuoto (size 0) NON viene riusato."""
    calls = 0

    async def counting_live(bbox: Bbox, citta: str) -> list[Poi]:
        nonlocal calls
        calls += 1
        return _sample_pois()

    config_path = _write_config(tmp_path, "Roma", "Centro")
    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")

    await _capture(config_path, tmp_path, poi_source=counting_live)

    assert calls == 1  # ri-catturato
    assert load_snapshot(path) == _sample_pois()


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


async def test_capture_all_present_never_builds_client(
    tmp_path: Path, capture_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix 2 (#148): un re-run tutto-skip (snapshot già presenti, mode=analyze)
    NON costruisce mai il client LLM → offline davvero, nessuna API key richiesta.
    Il builder esplode se invocato: se il test passa, non è mai stato chiamato."""

    def _exploding_builder(config: ExperimentConfig) -> object:
        raise AssertionError("build_llm_eval_client non deve essere invocato")

    monkeypatch.setattr(eval_main, "build_llm_eval_client", _exploding_builder)

    async def unused_live(bbox: Bbox, citta: str) -> list[Poi]:
        raise AssertionError("nessuna query live: snapshot già presente")

    config_path = _write_config(
        tmp_path, "Roma", "Centro", mode="analyze", model="claude"
    )
    # Pre-crea uno snapshot valido: la singola (citta, zona) va in skip.
    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))
    save_snapshot(path, _sample_pois())

    # Non deve sollevare: né il builder né la live vengono toccati.
    await _capture(config_path, tmp_path, poi_source=unused_live)

    assert load_snapshot(path) == _sample_pois()  # invariato


async def test_capture_baseline_never_builds_client(
    tmp_path: Path, capture_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T9 mantenuto (#148): mode=baseline non costruisce mai il client LLM,
    nemmeno quando lo snapshot va catturato ex-novo."""

    def _exploding_builder(config: ExperimentConfig) -> object:
        raise AssertionError("baseline non deve costruire il client LLM")

    monkeypatch.setattr(eval_main, "build_llm_eval_client", _exploding_builder)

    async def counting_live(bbox: Bbox, citta: str) -> list[Poi]:
        return _sample_pois()

    config_path = _write_config(tmp_path, "Roma", "Centro", mode="baseline")
    await _capture(config_path, tmp_path, poi_source=counting_live)

    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))
    assert load_snapshot(path) == _sample_pois()  # catturato senza LLM


async def test_capture_analyze_builds_client_once_across_cases(
    tmp_path: Path, capture_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix 2 (#148): con più case analyze da catturare, il client LLM è costruito
    LAZY al primo case che lo richiede e MEMOIZZATO (una sola costruzione)."""
    from tests.eval._doubles import FakeLLMClient

    builds = 0

    def _counting_builder(config: ExperimentConfig) -> FakeLLMClient:
        nonlocal builds
        builds += 1
        return FakeLLMClient()

    monkeypatch.setattr(eval_main, "build_llm_eval_client", _counting_builder)

    async def live(bbox: Bbox, citta: str) -> list[Poi]:
        return _sample_pois()

    cfg = ExperimentConfig(
        name="ablation",
        mode="analyze",
        model="claude",
        cases=[
            RunCase(citta="Roma", zona="Centro"),
            RunCase(citta="Milano", zona="Duomo"),
        ],
    )
    config_path = tmp_path / "multi.json"
    config_path.write_text(cfg.model_dump_json(), encoding="utf-8")

    await _capture(config_path, tmp_path, poi_source=live)

    assert builds == 1  # costruito una sola volta, condiviso tra i due case
