"""Tests of the CLI capture entry point: ``eval/__main__._capture`` (#110).

Drive ``_capture`` DIRECTLY (not just the ``capturing_source`` helper) to:
- M1: the snapshot is written at the (citta, zona) key resolved by
  ``make_snapshot_key``, never at a key that includes mode/model;
- M2: idempotent capture (skip-if-exists) + ``--force`` flag to re-capture.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

import crime_risk_analyzer.eval.__main__ as eval_main
from crime_risk_analyzer.eval import snapshots
from crime_risk_analyzer.eval.harness import make_snapshot_key
from crime_risk_analyzer.eval.schema import (
    ExperimentConfig,
    Mode,
    ModelChoice,
    RunCase,
)
from crime_risk_analyzer.eval.snapshots import (
    load_snapshot,
    snapshot_path,
)
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.overpass_client import OFFLINE_RETRY, OverpassError, Poi
from tests.eval._doubles import write_snapshot

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
            ontology_class="Bank",
            citta="Roma",
        )
    ]


def _sentinel_pois() -> list[Poi]:
    """Distinct content: if _capture re-captures, it overwrites this."""
    return [
        Poi(
            id="SENTINEL",
            name="Sentinella",
            lat=0.0,
            lon=0.0,
            osm_tags="x=y",
            ontology_class="Bank",
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
    """Config as a JSON file, as the real CLI would (default: baseline, no LLM)."""
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
    """Isolate _capture from the network: fake geocode + fake executor (baseline, no
    LLM)."""
    from crime_risk_analyzer.rag import retrieval
    from tests.eval._doubles import FakeProfiler

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    monkeypatch.setattr(eval_main, "get_executor", lambda: FakeProfiler())


async def test_capture_writes_at_citta_zona_key(
    tmp_path: Path, capture_env: None
) -> None:
    """M1: _capture writes the snapshot at the (citta, zona) key, NEVER at a
    key that includes mode/model (locks against reintroducing make_run_id)."""
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
    # A single file, at the (citta, zona) key: no variant with mode/model.
    assert list((tmp_path / "snapshots").glob("*.json")) == [expected]
    assert "baseline" not in expected.name
    assert "claude" not in expected.name


async def test_capture_skips_if_snapshot_exists(
    tmp_path: Path, capture_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    """M2: two _capture on the same (citta, zona) -> live query only ONCE and
    file NOT overwritten (skip-if-exists), with a reuse log."""
    calls = 0

    async def counting_live(bbox: Bbox, citta: str) -> list[Poi]:
        nonlocal calls
        calls += 1
        return _sample_pois()

    config_path = _write_config(tmp_path, "Roma", "Centro")
    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))

    await _capture(config_path, tmp_path, poi_source=counting_live)
    assert calls == 1
    # Sentinel: a re-capture would overwrite it.
    write_snapshot(path, _sentinel_pois())

    with caplog.at_level(logging.INFO):
        await _capture(config_path, tmp_path, poi_source=counting_live)

    assert calls == 1  # no second live query
    assert load_snapshot(path) == _sentinel_pois()  # file NOT overwritten
    assert any("riuso" in r.getMessage().lower() for r in caplog.records)


async def test_capture_warns_on_reuse_with_diverging_configuration(
    tmp_path: Path, capture_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    """#267: reusing a snapshot with a ``configurazione_canonica`` different from
    the current one must not be indistinguishable from a consistent reuse."""
    import json

    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))
    write_snapshot(path, _sample_pois())
    written = json.loads(path.read_text(encoding="utf-8"))
    written["provenienza"]["configurazione_canonica"]["per_class_cap"] += 100
    path.write_text(json.dumps(written), encoding="utf-8")

    config_path = _write_config(tmp_path, "Roma", "Centro")

    async def fake_live(bbox: Bbox, citta: str) -> list[Poi]:
        raise AssertionError("must not recapture: this is a reuse, not a force")

    with caplog.at_level(logging.WARNING):
        await _capture(config_path, tmp_path, poi_source=fake_live)

    assert any(
        "#267" in r.getMessage() and "riuso" in r.getMessage().lower()
        for r in caplog.records
    )


def test_snapshot_reusable_true_for_valid(tmp_path: Path) -> None:
    """Fix 1 (#148): an existing, non-empty snapshot with valid JSON is reusable."""
    path = tmp_path / "snap.json"
    write_snapshot(path, _sample_pois())
    assert _snapshot_reusable(path) is True


def test_snapshot_reusable_false_for_missing(tmp_path: Path) -> None:
    """Fix 1 (#148): a nonexistent file is not reusable."""
    assert _snapshot_reusable(tmp_path / "assente.json") is False


def test_snapshot_reusable_false_for_empty(tmp_path: Path) -> None:
    """Fix 1 (#148): an empty file (size 0) is not reusable."""
    path = tmp_path / "snap.json"
    path.write_text("", encoding="utf-8")
    assert _snapshot_reusable(path) is False


def test_snapshot_reusable_false_for_corrupt(tmp_path: Path) -> None:
    """Fix 1 (#148): a truncated/corrupt file (unparseable JSON) is not reusable."""
    path = tmp_path / "snap.json"
    path.write_text("[{ troncato non json", encoding="utf-8")
    assert _snapshot_reusable(path) is False


def test_snapshot_reusable_false_for_unknown_shape(tmp_path: Path) -> None:
    """#241: valid JSON but in a shape that ``load_snapshot`` does not recognise
    (neither bare list nor envelope) is not reusable -> re-capture, not a blow-up
    halfway through the capture."""
    path = tmp_path / "snap.json"
    path.write_text('{"qualcosa": "altro"}', encoding="utf-8")
    assert _snapshot_reusable(path) is False


async def test_capture_recaptures_when_snapshot_corrupt(
    tmp_path: Path, capture_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Fix 1 (#148): a snapshot present but corrupt (unparseable JSON) is NOT
    silently reused -> _capture re-captures live and overwrites it."""
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

    assert calls == 1  # re-captured, not skipped
    assert load_snapshot(path) == _sample_pois()  # overwritten with fresh content
    assert any(
        "corrotto" in r.getMessage().lower() or "vuoto" in r.getMessage().lower()
        for r in caplog.records
    )


async def test_capture_recaptures_when_snapshot_empty(
    tmp_path: Path, capture_env: None
) -> None:
    """Fix 1 (#148): a snapshot present but empty (size 0) is NOT reused."""
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

    assert calls == 1  # re-captured
    assert load_snapshot(path) == _sample_pois()


async def test_capture_force_recaptures(tmp_path: Path, capture_env: None) -> None:
    """M2: --force ignores skip-if-exists and re-captures (overwrites the snapshot)."""
    calls = 0

    async def counting_live(bbox: Bbox, citta: str) -> list[Poi]:
        nonlocal calls
        calls += 1
        return _sample_pois()

    config_path = _write_config(tmp_path, "Roma", "Centro")
    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))

    await _capture(config_path, tmp_path, poi_source=counting_live)
    assert calls == 1
    write_snapshot(path, _sentinel_pois())

    await _capture(config_path, tmp_path, force=True, poi_source=counting_live)
    assert calls == 2  # live re-capture
    assert load_snapshot(path) == _sample_pois()  # snapshot overwritten (fresh)


async def test_capture_analyze_arms_share_key(
    tmp_path: Path, capture_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M1: two analyze arms (claude, groq) capture at the SAME key (citta,
    zona); the second reuses the snapshot of the first -> no diverging live query
    (anti-confound #33, analyze branch of _capture).

    The builder blows up (#233): the capture must not touch the LLM even here, where
    the config declares mode=analyze."""

    def _exploding_builder(config: ExperimentConfig) -> object:
        raise AssertionError("capture must not build the LLM client (#233)")

    monkeypatch.setattr(eval_main, "build_llm_eval_client", _exploding_builder)

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
    # A single file per (citta, zona): claude and groq do NOT diverge.
    assert list((tmp_path / "snapshots").glob("*.json")) == [expected]
    assert calls == 1  # the second arm reused the snapshot (skip-if-exists)


async def test_capture_all_present_never_builds_client(
    tmp_path: Path, capture_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix 2 (#148): an all-skip re-run (snapshots already present, mode=analyze)
    NEVER builds the LLM client -> truly offline, no API key required.
    The builder blows up if invoked: if the test passes, it was never called."""

    def _exploding_builder(config: ExperimentConfig) -> object:
        raise AssertionError("build_llm_eval_client must not be invoked")

    monkeypatch.setattr(eval_main, "build_llm_eval_client", _exploding_builder)

    async def unused_live(bbox: Bbox, citta: str) -> list[Poi]:
        raise AssertionError("no live query: snapshot already present")

    config_path = _write_config(
        tmp_path, "Roma", "Centro", mode="analyze", model="claude"
    )
    # Pre-create a valid snapshot: the single (citta, zona) is skipped.
    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))
    write_snapshot(path, _sample_pois())

    # It must not raise: neither the builder nor the live source is touched.
    await _capture(config_path, tmp_path, poi_source=unused_live)

    assert load_snapshot(path) == _sample_pois()  # unchanged


async def test_capture_baseline_never_builds_client(
    tmp_path: Path, capture_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T9 kept (#148): mode=baseline never builds the LLM client,
    not even when the snapshot must be captured from scratch."""

    def _exploding_builder(config: ExperimentConfig) -> object:
        raise AssertionError("baseline must not build the LLM client")

    monkeypatch.setattr(eval_main, "build_llm_eval_client", _exploding_builder)

    async def counting_live(bbox: Bbox, citta: str) -> list[Poi]:
        return _sample_pois()

    config_path = _write_config(tmp_path, "Roma", "Centro", mode="baseline")
    await _capture(config_path, tmp_path, poi_source=counting_live)

    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))
    assert load_snapshot(path) == _sample_pois()  # captured without LLM


async def test_capture_analyze_never_builds_client(
    tmp_path: Path, capture_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#233: the capture NEVER calls the LLM, not even with ``mode=analyze`` and
    several cases to capture from scratch.

    It replaces the #148 test on the lazy and memoized construction of the client:
    that invariant ("do not build it on an all-skip re-run") is absorbed by
    this one, stronger. The capture is input acquisition, not an experiment: the
    narrative generated here would be discarded output, and on 26/07 it cost a third
    of the daily Groq quota, blocking the K=3 run."""
    builds = 0

    def _exploding_builder(config: ExperimentConfig) -> object:
        nonlocal builds
        builds += 1
        raise AssertionError("capture must not build the LLM client (#233)")

    monkeypatch.setattr(eval_main, "build_llm_eval_client", _exploding_builder)

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

    assert builds == 0
    # The snapshots are there anyway: the capture stays complete without LLM.
    for citta, zona in (("Roma", "Centro"), ("Milano", "Duomo")):
        path = snapshot_path(tmp_path, make_snapshot_key(citta, zona))
        assert load_snapshot(path) == _sample_pois()


async def test_capture_uses_the_offline_retry_policy(
    tmp_path: Path, capture_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#232: the capture, WITHOUT an injected source, reaches Overpass with the
    OFFLINE policy. It also covers the wiring of the OSM cut (#251) up to the
    written snapshot: no isolated test on ``capturing_source``/
    ``offline_fetch_pois`` would notice a broken unpacking in
    ``_capture`` itself.

    It does not pass ``poi_source``: it is the only way to cover the wiring line
    (``offline_fetch_pois`` when ``poi_source`` is ``None``). A test that
    called the offline source directly would leave green a return to
    ``fetch_pois``/``fetch_pois_with_cut`` with the interactive policy, i.e. the
    defect of #232 intact with new code next to it.
    """
    seen: list[object] = []
    osm_cut = {"timestamp_osm_base": "2026-07-26T17:42:03Z", "overpass_url": "x"}

    async def _spy(
        bbox: Bbox, citta: str, *args: object, **kwargs: object
    ) -> tuple[list[Poi], object]:
        seen.append(kwargs.get("retry"))
        return _sample_pois(), osm_cut

    monkeypatch.setattr(snapshots, "fetch_pois_with_cut", _spy)

    config_path = _write_config(tmp_path, "Roma", "Centro")
    await _capture(config_path, tmp_path)

    assert seen == [OFFLINE_RETRY]
    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))
    assert load_snapshot(path) == _sample_pois()
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["provenienza"]["taglio_osm"] == osm_cut


async def test_capture_isolates_failure_on_one_case(
    tmp_path: Path, capture_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    """#252: an error on the second of three cases must not prevent the capture of the
    third, and the final summary must explicitly declare what was
    captured and what was not."""
    attempted: list[str] = []

    async def flaky_live(bbox: Bbox, citta: str) -> list[Poi]:
        attempted.append(citta)
        if citta == "Milano":
            raise OverpassError("Overpass ha risposto 503")
        return _sample_pois()

    cfg = ExperimentConfig(
        name="ablation",
        mode="baseline",
        model="claude",
        cases=[
            RunCase(citta="Roma", zona="Centro"),
            RunCase(citta="Milano", zona="Duomo"),
            RunCase(citta="Napoli", zona="Vomero"),
        ],
    )
    config_path = tmp_path / "multi.json"
    config_path.write_text(cfg.model_dump_json(), encoding="utf-8")

    with caplog.at_level(logging.INFO):
        summary = await _capture(config_path, tmp_path, poi_source=flaky_live)

    # Rome and Naples captured despite the failure of Milan in the middle.
    assert attempted == ["Roma", "Milano", "Napoli"]
    roma_path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))
    milano_path = snapshot_path(tmp_path, make_snapshot_key("Milano", "Duomo"))
    napoli_path = snapshot_path(tmp_path, make_snapshot_key("Napoli", "Vomero"))
    assert load_snapshot(roma_path) == _sample_pois()
    assert not milano_path.exists()
    assert load_snapshot(napoli_path) == _sample_pois()

    # The summary explicitly declares captured/not captured.
    assert [(c.citta, c.zona) for c in summary.succeeded] == [
        ("Roma", "Centro"),
        ("Napoli", "Vomero"),
    ]
    assert [(c.citta, c.zona) for c in summary.failed] == [("Milano", "Duomo")]
    failure = summary.failed[0]
    assert failure.error is not None
    assert "Overpass ha risposto 503" in failure.error
    assert failure.error_type == "OverpassError"

    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "Milano" in log_text
    assert "Duomo" in log_text


async def test_capture_isolates_failure_of_any_kind(
    tmp_path: Path, capture_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    """#252: the per-case isolation is not restricted to GeocodingError/OverpassError --
    a bug elsewhere in the pipeline (here a generic ValueError) must not silently
    lose the previous cases nor skip the final summary."""

    async def flaky_live(bbox: Bbox, citta: str) -> list[Poi]:
        if citta == "Milano":
            raise ValueError("malformed POI")
        return _sample_pois()

    cfg = ExperimentConfig(
        name="ablation",
        mode="baseline",
        model="claude",
        cases=[
            RunCase(citta="Roma", zona="Centro"),
            RunCase(citta="Milano", zona="Duomo"),
            RunCase(citta="Napoli", zona="Vomero"),
        ],
    )
    config_path = tmp_path / "multi.json"
    config_path.write_text(cfg.model_dump_json(), encoding="utf-8")

    with caplog.at_level(logging.INFO):
        summary = await _capture(config_path, tmp_path, poi_source=flaky_live)

    napoli_path = snapshot_path(tmp_path, make_snapshot_key("Napoli", "Vomero"))
    assert load_snapshot(napoli_path) == _sample_pois()
    assert [(c.citta, c.zona) for c in summary.succeeded] == [
        ("Roma", "Centro"),
        ("Napoli", "Vomero"),
    ]
    failure = summary.failed[0]
    assert failure.error_type == "ValueError"
    assert failure.error is not None
    assert "malformed POI" in failure.error
    assert any("riepilogo cattura" in r.getMessage() for r in caplog.records)


async def test_capture_removes_freshly_written_snapshot_on_downstream_failure(
    tmp_path: Path, capture_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#252: ``capturing_source`` writes the snapshot BEFORE an error downstream
    (here in grounding) makes the case fail -- without cleanup, the next run
    would find a valid file and treat it as "already captured" (silent
    false success). The file just written by a failed case must be removed."""
    from crime_risk_analyzer import orchestrator

    def _boom(*args: object, **kwargs: object) -> object:
        raise ValueError("bug in grounding")

    monkeypatch.setattr(orchestrator, "ground", _boom)

    async def live(bbox: Bbox, citta: str) -> list[Poi]:
        return _sample_pois()

    config_path = _write_config(tmp_path, "Roma", "Centro")
    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))

    summary = await _capture(config_path, tmp_path, poi_source=live)

    assert not path.exists()  # no false success left on disk
    assert summary.succeeded == ()
    assert summary.failed[0].error_type == "ValueError"


async def test_capture_keeps_preexisting_snapshot_on_failure(
    tmp_path: Path, capture_env: None
) -> None:
    """#252: a PRE-EXISTING snapshot (even if corrupt) must not be deleted by the
    error branch -- only a file written by the current attempt must be cleaned up."""

    async def failing_live(bbox: Bbox, citta: str) -> list[Poi]:
        raise OverpassError("Overpass ha risposto 503")

    config_path = _write_config(tmp_path, "Roma", "Centro")
    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[{ troncato non json", encoding="utf-8")

    summary = await _capture(config_path, tmp_path, poi_source=failing_live)

    assert path.exists()  # the pre-existing file (however corrupt) stays
    assert path.read_text(encoding="utf-8") == "[{ troncato non json"
    assert summary.failed[0].error_type == "OverpassError"


async def test_capture_isolates_environmental_error_on_skip_check(
    tmp_path: Path, capture_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#252: an environmental error (``OSError``) raised by the skip-check of
    ``_snapshot_reusable`` isolates only that case, it does not abort the whole
    capture -- the second case must still be captured."""

    def _boom(path: Path) -> bool:
        raise OSError("disk unreachable")

    monkeypatch.setattr(eval_main, "_snapshot_reusable", _boom)

    async def live(bbox: Bbox, citta: str) -> list[Poi]:
        return _sample_pois()

    cfg = ExperimentConfig(
        name="ablation",
        mode="baseline",
        model="claude",
        cases=[
            RunCase(citta="Roma", zona="Centro"),
            RunCase(citta="Milano", zona="Duomo"),
        ],
    )
    config_path = tmp_path / "multi.json"
    config_path.write_text(cfg.model_dump_json(), encoding="utf-8")

    summary = await _capture(config_path, tmp_path, poi_source=live)

    assert [(c.citta, c.zona) for c in summary.failed] == [
        ("Roma", "Centro"),
        ("Milano", "Duomo"),
    ]
    assert all(c.error_type == "OSError" for c in summary.failed)


async def test_capture_case_error_none_for_exception_without_message(
    tmp_path: Path, capture_env: None
) -> None:
    """#252: an exception without a message (``ValueError()``) must not produce
    an empty string in ``CaptureCase.error`` -- it stays ``None``, consistent with
    the "None = no error" convention of the field."""

    async def failing_live(bbox: Bbox, citta: str) -> list[Poi]:
        raise ValueError()

    config_path = _write_config(tmp_path, "Roma", "Centro")
    summary = await _capture(config_path, tmp_path, poi_source=failing_live)

    assert summary.failed[0].error_type == "ValueError"
    assert summary.failed[0].error is None


async def test_capture_partial_skip_captures_only_missing(
    tmp_path: Path, capture_env: None
) -> None:
    """Fix 3 (#148): config with 2 cases, one snapshot pre-exists and the other does not
    -> the existing case is skipped (reuse, sentinel intact) and ONLY the missing
    one is captured. Locks the per-key ``continue`` against a future
    break/return that would interrupt the loop after the first skip."""
    captured_cities: list[str] = []

    async def recording_live(bbox: Bbox, citta: str) -> list[Poi]:
        captured_cities.append(citta)
        return _sample_pois()

    cfg = ExperimentConfig(
        name="ablation",
        mode="baseline",
        model="claude",
        cases=[
            RunCase(citta="Roma", zona="Centro"),
            RunCase(citta="Milano", zona="Duomo"),
        ],
    )
    config_path = tmp_path / "multi.json"
    config_path.write_text(cfg.model_dump_json(), encoding="utf-8")

    # Pre-create ONLY the Rome snapshot with a sentinel (it must stay intact).
    roma_path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))
    write_snapshot(roma_path, _sentinel_pois())
    milano_path = snapshot_path(tmp_path, make_snapshot_key("Milano", "Duomo"))

    await _capture(config_path, tmp_path, poi_source=recording_live)

    # Rome skipped (sentinel intact), Milan captured from scratch.
    assert load_snapshot(roma_path) == _sentinel_pois()
    assert load_snapshot(milano_path) == _sample_pois()
    assert captured_cities == ["Milano"]  # only the missing one touched the live source
