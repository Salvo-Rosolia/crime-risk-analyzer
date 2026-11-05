"""Tests of the two-arm comparison (#32).

GENERIC primitive (any arms A vs B): joins the RunRecords of two
experiments by ``(citta, zona)`` and computes the delta of the 4 metrics. It is
reused by #33 (claude vs groq). The tests are offline: they build the records by hand,
no live LLM/Overpass run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from crime_risk_analyzer.eval.compare import (
    CONFOUNDED_VARIABLE_HEAD,
    ISOLATED_DELTA_CLAIM,
    ISOLATED_VARIABLE_HEAD,
    OPERATIONAL_AXES_NOTE,
    POI_SUBSET_VALIDITY_HEAD,
    PROMPT_LENGTH_SIDE_EFFECT,
    VACUOUS_CAVEAT_HEAD,
    VACUOUS_DELTA_CLAIM,
    Comparison,
    FailedZone,
    MetricValues,
    NoUsableOutputError,
    ZoneComparison,
    compare_experiments,
    compare_records,
    is_ontology_isolating_pair,
    is_vacuous_arm,
    to_csv,
    to_markdown,
    write_comparison,
)
from crime_risk_analyzer.eval.harness import write_record
from crime_risk_analyzer.eval.schema import (
    Metrics,
    Mode,
    Provenance,
    RunRecord,
    RunStatus,
)
from crime_risk_analyzer.rag.generation import ContextFormat


def _rec(
    experiment: str,
    citta: str,
    zona: str,
    *,
    grounding: float,
    hallucination: float,
    latency_ms: int,
    cost_usd: float,
    mode: Mode = "analyze",
    model: str = "claude",
    temperature: float = 0.0,
    seed: int = 0,
    status: RunStatus = RunStatus.OK,
    snapshot_id: str | None = None,
    narrativa: str = "x",
    context_format: ContextFormat = "per_poi",
    quality_vacuous: bool | None = None,
    poi_nel_prompt: tuple[str, ...] | None = ("1",),
    n_poi: int = 1,
) -> RunRecord:
    """Minimal RunRecord with controlled metrics for the comparison tests.

    ``poi_nel_prompt`` by default is the only point of the zone (``n_poi=1``): the
    condition of the records produced after #349 without cut.
    """
    return RunRecord(
        run_id=f"{experiment}__{citta}__{zona}__{mode}__{model}".lower(),
        experiment=experiment,
        citta=citta,
        zona=zona,
        mode=mode,
        model_id=model,
        status=status,
        metrics=Metrics(
            grounding=grounding,
            hallucination=hallucination,
            quality_vacuous=quality_vacuous,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        ),
        narrativa=narrativa,
        n_poi=n_poi,
        poi_nel_prompt=None if poi_nel_prompt is None else list(poi_nel_prompt),
        provenance=Provenance(
            code_commit="c",
            ontology_hash="o",
            snapshot_id=snapshot_id or f"{citta}__{zona}".lower(),
            model_id=model,
            prompt_hash="p",
            temperature=temperature,
            seed=seed,
            experiment=experiment,
            context_format=context_format,
        ),
    )


def _arm_a_with_error() -> list[RunRecord]:
    """Arm A with a zone (Napoli) in ERROR: zeroed metrics like the harness."""
    return _arm_a() + [
        _rec(
            "full",
            "Napoli",
            "Garibaldi",
            grounding=0.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.ERROR,
        )
    ]


def _arm_b_napoli_ok() -> list[RunRecord]:
    """Arm B with Napoli OK (real metrics): same set of zones as A."""
    return _arm_b() + [
        _rec(
            "base",
            "Napoli",
            "Garibaldi",
            grounding=0.45,
            hallucination=0.0,
            latency_ms=110,
            cost_usd=0.0,
            mode="baseline",
        )
    ]


def _arm_a() -> list[RunRecord]:
    return [
        _rec(
            "full",
            "Roma",
            "Colosseo",
            grounding=0.9,
            hallucination=0.1,
            latency_ms=2000,
            cost_usd=0.003,
        ),
        _rec(
            "full",
            "Milano",
            "Duomo",
            grounding=0.8,
            hallucination=0.2,
            latency_ms=2500,
            cost_usd=0.004,
        ),
    ]


def _arm_b() -> list[RunRecord]:
    return [
        _rec(
            "base",
            "Roma",
            "Colosseo",
            grounding=0.5,
            hallucination=0.0,
            latency_ms=100,
            cost_usd=0.0,
            mode="baseline",
        ),
        _rec(
            "base",
            "Milano",
            "Duomo",
            grounding=0.4,
            hallucination=0.0,
            latency_ms=120,
            cost_usd=0.0,
            mode="baseline",
        ),
    ]


# --- core: join + delta ---------------------------------------------------


def test_compare_records_joins_and_computes_per_zone_delta() -> None:
    """Join by (citta, zona) and compute delta = A - B on every metric."""
    cmp = compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base")
    assert isinstance(cmp, Comparison)
    by_zone = {(z.citta, z.zona): z for z in cmp.zones}
    roma = by_zone[("Roma", "Colosseo")]
    assert roma.a.grounding == pytest.approx(0.9)
    assert roma.b.grounding == pytest.approx(0.5)
    assert roma.delta.grounding == pytest.approx(0.4)
    assert roma.delta.hallucination == pytest.approx(0.1)
    assert roma.delta.latency_ms == pytest.approx(1900.0)
    assert roma.delta.cost_usd == pytest.approx(0.003)


def test_compare_records_sorts_zones_deterministically() -> None:
    """The order of the zones is deterministic (sorted by (citta, zona))."""
    cmp = compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base")
    assert [(z.citta, z.zona) for z in cmp.zones] == [
        ("Milano", "Duomo"),
        ("Roma", "Colosseo"),
    ]


def test_compare_records_aggregate_means_and_mean_delta() -> None:
    """The aggregate is the mean per arm; mean_delta == mean_a - mean_b."""
    cmp = compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base")
    assert cmp.mean_a.grounding == pytest.approx(0.85)
    assert cmp.mean_b.grounding == pytest.approx(0.45)
    assert cmp.mean_a.latency_ms == pytest.approx(2250.0)
    assert cmp.mean_b.latency_ms == pytest.approx(110.0)
    assert cmp.mean_delta.grounding == pytest.approx(0.40)
    assert cmp.mean_delta.hallucination == pytest.approx(0.15)
    assert cmp.mean_delta.latency_ms == pytest.approx(2140.0)
    assert cmp.mean_delta.cost_usd == pytest.approx(0.0035)


def test_compare_records_labels_are_preserved() -> None:
    cmp = compare_records(_arm_a(), _arm_b(), label_a="analyze", label_b="baseline")
    assert cmp.label_a == "analyze"
    assert cmp.label_b == "baseline"


def test_compare_records_raises_on_zone_key_mismatch() -> None:
    """Different sets of (citta, zona) between the arms -> error (iso-input
    violated)."""
    arm_b = [_arm_b()[0]]  # (Milano, Duomo) is missing
    with pytest.raises(ValueError, match="(?i)zone|citta|zona|iso"):
        compare_records(_arm_a(), arm_b, label_a="full", label_b="base")


def test_compare_records_raises_on_duplicate_zone_within_arm() -> None:
    """Two records for the same (citta, zona) in the same arm -> error."""
    dup = _arm_a() + [
        _rec(
            "full",
            "Roma",
            "Colosseo",
            grounding=0.1,
            hallucination=0.9,
            latency_ms=1,
            cost_usd=0.0,
        )
    ]
    with pytest.raises(ValueError, match="(?i)duplicat|doppi"):
        compare_records(dup, _arm_b(), label_a="full", label_b="base")


def test_compare_records_raises_on_empty() -> None:
    """No zone in common (empty arms) -> error, no mean over 0."""
    with pytest.raises(ValueError):
        compare_records([], [], label_a="a", label_b="b")


def test_zone_comparison_delta_type() -> None:
    """The delta is a MetricValues (can be negative, outside [0,1])."""
    cmp = compare_records(_arm_b(), _arm_a(), label_a="base", label_b="full")
    z = cmp.zones[0]
    assert isinstance(z, ZoneComparison)
    assert isinstance(z.delta, MetricValues)
    assert z.delta.grounding < 0  # base - full is negative


# --- M1: ERROR records do not pollute deltas/means ----------------------


def test_error_zone_excluded_from_zones_and_means() -> None:
    """A zone in ERROR (zeroed metrics) is excluded from compared zones and means."""
    cmp = compare_records(
        _arm_a_with_error(), _arm_b_napoli_ok(), label_a="full", label_b="base"
    )
    # Napoli (ERROR in A) does NOT appear among the compared zones.
    assert [(z.citta, z.zona) for z in cmp.zones] == [
        ("Milano", "Duomo"),
        ("Roma", "Colosseo"),
    ]
    # The means are identical to the 2-zone all-OK case: Napoli's zero does not
    # enter the aggregate (no silent mean over a zeroed record).
    baseline = compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base")
    assert cmp.mean_a.grounding == pytest.approx(baseline.mean_a.grounding)
    assert cmp.mean_b.grounding == pytest.approx(baseline.mean_b.grounding)
    assert cmp.mean_a.latency_ms == pytest.approx(baseline.mean_a.latency_ms)
    assert cmp.mean_delta.grounding == pytest.approx(baseline.mean_delta.grounding)


@pytest.mark.parametrize(
    "status", [s for s in RunStatus if s is not RunStatus.OK], ids=lambda s: s.value
)
def test_every_status_other_than_ok_is_kept_out_of_the_means(
    status: RunStatus,
) -> None:
    """No failure status enters the means, present and future.

    Parametrized on the enum and not on today's ERROR/FALLBACK pair: a new
    value (``HARNESS_ERROR``) is born with zeroed metrics by construction, and if
    someone forgets to add it to ``_EXCLUDED_STATUSES`` those zeros
    end up in the mean as if they were a measure -- an arm would get worse
    because of an instrumentation bug, silently. This case fails in place
    of the table.
    """
    arm_a = _arm_a() + [
        _rec(
            "full",
            "Napoli",
            "Garibaldi",
            grounding=0.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=status,
        )
    ]
    cmp = compare_records(arm_a, _arm_b_napoli_ok(), label_a="full", label_b="base")

    assert [(z.citta, z.zona) for z in cmp.zones] == [
        ("Milano", "Duomo"),
        ("Roma", "Colosseo"),
    ]
    assert [(f.citta, f.zona) for f in cmp.failed] == [("Napoli", "Garibaldi")]
    assert cmp.failed[0].status_a == status.value
    baseline = compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base")
    assert cmp.mean_a.grounding == pytest.approx(baseline.mean_a.grounding)


def test_error_zone_reported_with_both_statuses() -> None:
    """The failed zone is reported with the status of BOTH arms."""
    cmp = compare_records(
        _arm_a_with_error(), _arm_b_napoli_ok(), label_a="full", label_b="base"
    )
    assert len(cmp.failed) == 1
    failed = cmp.failed[0]
    assert isinstance(failed, FailedZone)
    assert (failed.citta, failed.zona) == ("Napoli", "Garibaldi")
    assert failed.status_a == "error"
    assert failed.status_b == "ok"


def test_no_failed_zones_when_all_ok() -> None:
    cmp = compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base")
    assert cmp.failed == []


def test_fallback_zone_is_excluded_from_comparison() -> None:
    """FALLBACK has an empty narrative -> non-quality metrics: the zone is excluded."""
    arm_a = _arm_a() + [
        _rec(
            "full",
            "Napoli",
            "Garibaldi",
            grounding=1.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.FALLBACK,
        )
    ]
    arm_b = _arm_b() + [
        _rec(
            "base",
            "Napoli",
            "Garibaldi",
            grounding=0.45,
            hallucination=0.0,
            latency_ms=110,
            cost_usd=0.0,
            mode="baseline",
        )
    ]
    cmp = compare_records(arm_a, arm_b, label_a="full", label_b="base")
    # Napoli (FALLBACK in A) is NOT among the compared zones.
    assert [(z.citta, z.zona) for z in cmp.zones] == [
        ("Milano", "Duomo"),
        ("Roma", "Colosseo"),
    ]
    assert [(f.citta, f.zona) for f in cmp.failed] == [("Napoli", "Garibaldi")]


def test_fallback_zone_reported_with_status() -> None:
    """The FALLBACK exclusion is traced (not silent): status in the FailedZone."""
    arm_a = _arm_a() + [
        _rec(
            "full",
            "Napoli",
            "Garibaldi",
            grounding=1.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.FALLBACK,
        )
    ]
    arm_b = _arm_b() + [
        _rec(
            "base",
            "Napoli",
            "Garibaldi",
            grounding=0.45,
            hallucination=0.0,
            latency_ms=110,
            cost_usd=0.0,
            mode="baseline",
        )
    ]
    failed = compare_records(arm_a, arm_b, label_a="full", label_b="base").failed[0]
    assert failed.status_a == "fallback"
    assert failed.status_b == "ok"


def test_raises_when_all_zones_fallback() -> None:
    """An arm entirely in FALLBACK -> no valid zone -> clear error."""
    arm_a = [
        _rec(
            "full",
            "Roma",
            "Colosseo",
            grounding=1.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.FALLBACK,
        )
    ]
    arm_b = [
        _rec(
            "base",
            "Roma",
            "Colosseo",
            grounding=0.5,
            hallucination=0.0,
            latency_ms=100,
            cost_usd=0.0,
            mode="baseline",
        )
    ]
    with pytest.raises(ValueError, match="(?i)valida|fallit|error|fallback"):
        compare_records(arm_a, arm_b, label_a="full", label_b="base")


def test_no_usable_output_error_carries_label_and_failed_zones() -> None:
    """#239: the exception carries the data for the report, not just a message."""
    arm_a = [
        _rec(
            "full",
            "Roma",
            "Colosseo",
            grounding=1.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.FALLBACK,
        )
    ]
    arm_b = [
        _rec(
            "base",
            "Roma",
            "Colosseo",
            grounding=0.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            mode="baseline",
            status=RunStatus.ERROR,
        )
    ]
    with pytest.raises(NoUsableOutputError) as excinfo:
        compare_records(arm_a, arm_b, label_a="full", label_b="base")
    exc = excinfo.value
    assert exc.label_a == "full"
    assert exc.label_b == "base"
    assert len(exc.failed) == 1
    assert exc.failed[0].citta == "Roma"
    assert exc.failed[0].status_a == "fallback"
    assert exc.failed[0].status_b == "error"


def test_raises_when_all_zones_error() -> None:
    """If no valid zone remains -> explicit error (no mean over nothing)."""
    arm_a = [
        _rec(
            "full",
            "Roma",
            "Colosseo",
            grounding=0.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.ERROR,
        )
    ]
    arm_b = [
        _rec(
            "base",
            "Roma",
            "Colosseo",
            grounding=0.5,
            hallucination=0.0,
            latency_ms=100,
            cost_usd=0.0,
            mode="baseline",
        )
    ]
    with pytest.raises(ValueError, match="(?i)valida|fallit|error"):
        compare_records(arm_a, arm_b, label_a="full", label_b="base")


# --- m1: iso-input at record level (snapshot_id) -----------------------


def test_raises_on_snapshot_id_mismatch() -> None:
    """Same (citta, zona) but different snapshot_id between the arms -> iso-input
    error."""
    arm_a = [
        _rec(
            "full",
            "Roma",
            "Colosseo",
            grounding=0.9,
            hallucination=0.1,
            latency_ms=2000,
            cost_usd=0.003,
            snapshot_id="roma__colosseo",
        )
    ]
    arm_b = [
        _rec(
            "base",
            "Roma",
            "Colosseo",
            grounding=0.5,
            hallucination=0.0,
            latency_ms=100,
            cost_usd=0.0,
            mode="baseline",
            snapshot_id="roma__colosseo-forced",
        )
    ]
    with pytest.raises(ValueError, match="(?i)snapshot"):
        compare_records(arm_a, arm_b, label_a="full", label_b="base")


# --- serialization: CSV / Markdown --------------------------------------


def test_to_csv_labeled_headers_and_mean_row() -> None:
    """Headers parametrized on the labels + aggregate row (mean)."""
    csv = to_csv(compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base"))
    lines = csv.strip().splitlines()
    header = lines[0]
    assert "citta" in header and "zona" in header
    assert "grounding_full" in header
    assert "grounding_base" in header
    assert "grounding_delta" in header
    assert "latency_ms_delta" in header
    assert "cost_usd_delta" in header
    assert "MEDIA" in csv  # aggregate row


def test_to_csv_delta_has_sign() -> None:
    """The delta is formatted with the explicit sign (+/-)."""
    csv = to_csv(compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base"))
    assert "+0.400" in csv  # grounding delta
    assert "+1900" in csv  # latency delta (Roma)


def test_to_markdown_table_with_headers_and_mean() -> None:
    md = to_markdown(
        compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base")
    )
    assert "|" in md
    assert "grounding_delta" in md
    assert "MEDIA" in md
    # markdown table separator
    assert "---" in md


def test_to_markdown_reports_failed_zones_section() -> None:
    """The excluded-zones section appears in the markdown, with the status of both
    arms."""
    cmp = compare_records(
        _arm_a_with_error(), _arm_b_napoli_ok(), label_a="full", label_b="base"
    )
    md = to_markdown(cmp)
    assert "escluse" in md.lower()
    assert "Napoli" in md
    assert "status_full" in md
    assert "status_base" in md
    assert "error" in md


def test_csv_is_rectangular_with_failed_zones() -> None:
    """Option (a): with zones in ERROR the CSV stays RECTANGULAR and does not include
    them.

    The failed zones do NOT enter the numeric CSV (no ragged row, pandas loads
    them clean) but do NOT disappear: they stay in ``Comparison.failed`` (and in the
    Markdown report).
    """
    import csv as _csv
    import io as _io

    cmp = compare_records(
        _arm_a_with_error(), _arm_b_napoli_ok(), label_a="full", label_b="base"
    )
    csv_text = to_csv(cmp)
    rows = list(_csv.reader(_io.StringIO(csv_text)))
    header_width = len(rows[0])
    for row in rows:
        assert len(row) == header_width  # no row of different width
    # header + valid zones (Milano, Roma) + MEDIA; Napoli (ERROR) excluded.
    assert len(rows) == len(cmp.zones) + 2
    assert "Napoli" not in csv_text
    assert "status_full" not in csv_text
    # Not lost: accessible programmatically.
    assert [(f.citta, f.zona) for f in cmp.failed] == [("Napoli", "Garibaldi")]


def test_no_failed_section_in_markdown_when_all_ok() -> None:
    """Without failures there is no excluded-zones section in the Markdown report."""
    cmp = compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base")
    assert "escluse" not in to_markdown(cmp).lower()


def test_main_table_rows_match_header_width() -> None:
    """m2: header and data rows derive from the same source -> same width."""
    import csv as _csv
    import io as _io

    cmp = compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base")
    rows = list(_csv.reader(_io.StringIO(to_csv(cmp))))
    header_width = len(rows[0])
    # header + one row per zone + MEDIA row, all of the same width.
    assert len(rows) == len(cmp.zones) + 2
    for row in rows:
        assert len(row) == header_width


# --- writing to disk ----------------------------------------------------


def test_write_comparison_writes_csv_and_md(tmp_path: Path) -> None:
    cmp = compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base")
    csv_path, md_path = write_comparison(tmp_path, cmp, "ablation")
    assert csv_path == tmp_path / "ablation.csv"
    assert md_path == tmp_path / "ablation.md"
    assert csv_path.exists() and md_path.exists()
    assert "grounding_full" in csv_path.read_text(encoding="utf-8")
    assert "grounding_delta" in md_path.read_text(encoding="utf-8")


def test_write_comparison_csv_uses_newline_empty(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """#103-style regression for the NEW file: CSV written with newline="".

    ``csv.writer`` already emits ``\\r\\n``; without ``newline=""`` the text mode of
    ``write_text`` on Windows would re-translate ``\\n`` into ``\\r\\n`` (spurious
    rows). Deterministic and cross-platform guard: it spies the KWARG passed to
    write_text.
    """
    cmp = compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base")

    original = Path.write_text
    csv_newline_kwargs: list[str | None] = []

    def spy(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        if self.suffix == ".csv":
            csv_newline_kwargs.append(newline)
        return original(self, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "write_text", spy)
    csv_path, _md = write_comparison(tmp_path, cmp, "ablation")

    assert csv_newline_kwargs == [""]
    assert b"\r\r\n" not in csv_path.read_bytes()


def test_compare_experiments_end_to_end(tmp_path: Path) -> None:
    """From records on disk (two experiments) to tables: load -> join -> write."""
    for rec in _arm_a():
        write_record(tmp_path, rec)
    for rec in _arm_b():
        write_record(tmp_path, rec)
    csv_path, md_path = compare_experiments(
        tmp_path, "full", "base", label_a="analyze", label_b="baseline"
    )
    assert csv_path == tmp_path / "full_vs_base.csv"
    assert md_path == tmp_path / "full_vs_base.md"
    text = csv_path.read_text(encoding="utf-8")
    assert "grounding_analyze" in text
    assert "grounding_baseline" in text
    assert "+0.400" in text  # Roma grounding delta verified end-to-end


def test_compare_experiments_custom_stem(tmp_path: Path) -> None:
    for rec in _arm_a():
        write_record(tmp_path, rec)
    for rec in _arm_b():
        write_record(tmp_path, rec)
    csv_path, md_path = compare_experiments(
        tmp_path, "full", "base", stem="mio-confronto"
    )
    assert csv_path == tmp_path / "mio-confronto.csv"
    assert md_path == tmp_path / "mio-confronto.md"


def _all_fallback_arm(experiment: str, mode: Mode) -> list[RunRecord]:
    return [
        _rec(
            experiment,
            "Roma",
            "Colosseo",
            grounding=1.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            mode=mode,
            status=RunStatus.FALLBACK,
        ),
        _rec(
            experiment,
            "Milano",
            "Duomo",
            grounding=1.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            mode=mode,
            status=RunStatus.ERROR,
        ),
    ]


def test_compare_experiments_writes_report_and_raises_when_all_zones_fail(
    tmp_path: Path,
) -> None:
    """#239: no usable output -> report on disk, not a bare traceback.

    Both zones are excluded (one FALLBACK, one ERROR on A): no MEDIA,
    no metrics table, no verdict -- only the excluded zones.
    """
    for rec in _all_fallback_arm("full", "analyze"):
        write_record(tmp_path, rec)
    for rec in _all_fallback_arm("base", "baseline"):
        write_record(tmp_path, rec)

    with pytest.raises(NoUsableOutputError):
        compare_experiments(
            tmp_path, "full", "base", label_a="analyze", label_b="baseline"
        )

    csv_path = tmp_path / "full_vs_base.csv"
    md_path = tmp_path / "full_vs_base.md"
    json_path = tmp_path / "full_vs_base.json"
    assert csv_path.exists()
    assert md_path.exists()
    assert json_path.exists()

    csv_text = csv_path.read_text(encoding="utf-8")
    assert "Roma" in csv_text
    assert "Milano" in csv_text
    assert "MEDIA" not in csv_text  # no mean: there is nothing to average

    md_text = md_path.read_text(encoding="utf-8")
    assert "Nessun output utilizzabile" in md_text
    assert "Nessun verdetto" in md_text
    assert "grounding" not in md_text.lower()  # no metrics table

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["winner"] is None
    assert payload["quality_verdict_applicable"] is False
    assert len(payload["failed"]) == 2


def test_compare_experiments_still_raises_no_usable_output_if_report_write_fails(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """#239 (review follow-up): an OSError in the report write must not
    replace NoUsableOutputError -- otherwise the CLI loses the clean exit code
    and goes back to an unhandled traceback (exactly what #239 was meant to avoid).
    """
    import crime_risk_analyzer.eval.compare as compare_mod

    for rec in _all_fallback_arm("full", "analyze"):
        write_record(tmp_path, rec)
    for rec in _all_fallback_arm("base", "baseline"):
        write_record(tmp_path, rec)

    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(compare_mod, "write_no_usable_output_report", _boom)

    with pytest.raises(NoUsableOutputError):
        compare_experiments(
            tmp_path, "full", "base", label_a="analyze", label_b="baseline"
        )
    # No file written: _boom replaced the real write.
    assert not (tmp_path / "full_vs_base.md").exists()


def test_compare_experiments_propagates_file_exists_error_from_report_write(
    tmp_path: Path,
) -> None:
    """The anti-overwrite guard stays prioritary also on this branch."""
    for rec in _all_fallback_arm("full", "analyze"):
        write_record(tmp_path, rec)
    for rec in _all_fallback_arm("base", "baseline"):
        write_record(tmp_path, rec)
    (tmp_path / "full_vs_base.csv").write_text("gia' presente", encoding="utf-8")

    with pytest.raises(FileExistsError):
        compare_experiments(
            tmp_path, "full", "base", label_a="analyze", label_b="baseline"
        )


def test_main_compare_returns_1_on_no_usable_output(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """#239: the CLI command `compare` signals the failure with exit code 1."""
    import sys

    import crime_risk_analyzer.eval.__main__ as eval_main

    for rec in _all_fallback_arm("full", "analyze"):
        write_record(tmp_path, rec)
    for rec in _all_fallback_arm("base", "baseline"):
        write_record(tmp_path, rec)

    argv = [
        "crime_risk_analyzer.eval",
        "compare",
        "--experiment-a",
        "full",
        "--experiment-b",
        "base",
        "--results",
        str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    rc = eval_main.main()
    assert rc == 1
    assert (tmp_path / "full_vs_base.md").exists()


def test_main_compare_dispatch_writes_tables(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """DoD #32: the ablation tables are regenerable with ONE CLI command.

    Drives ``eval.__main__.main`` with the argv of the ``compare`` subcommand: from the
    records on disk it produces the CSV/MD files of the comparison.
    """
    import sys

    import crime_risk_analyzer.eval.__main__ as eval_main

    for rec in _arm_a():
        write_record(tmp_path, rec)
    for rec in _arm_b():
        write_record(tmp_path, rec)

    argv = [
        "crime_risk_analyzer.eval",
        "compare",
        "--experiment-a",
        "full",
        "--experiment-b",
        "base",
        "--label-a",
        "analyze",
        "--label-b",
        "baseline",
        "--out",
        "ablation",
        "--results",
        str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    rc = eval_main.main()
    assert rc == 0
    csv_path = tmp_path / "ablation.csv"
    assert csv_path.exists()
    assert (tmp_path / "ablation.md").exists()
    assert "grounding_analyze" in csv_path.read_text(encoding="utf-8")


def test_compare_experiments_refuses_overwrite_without_force(tmp_path: Path) -> None:
    from crime_risk_analyzer.eval.compare import compare_experiments
    from crime_risk_analyzer.eval.harness import write_record

    # two minimal arms, one OK zone each, same snapshot_id
    from crime_risk_analyzer.eval.schema import (
        Metrics,
        Provenance,
        RunRecord,
        RunStatus,
    )

    def _mk(experiment: str) -> RunRecord:
        return RunRecord(
            run_id=f"{experiment}__roma__colosseo__analyze__groq__rep00",
            experiment=experiment,
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
                experiment=experiment,
            ),
        )

    write_record(tmp_path, _mk("a-exp"))
    write_record(tmp_path, _mk("b-exp"))
    compare_experiments(tmp_path, "a-exp", "b-exp", stem="dup")
    with pytest.raises(FileExistsError):
        compare_experiments(tmp_path, "a-exp", "b-exp", stem="dup")
    compare_experiments(tmp_path, "a-exp", "b-exp", stem="dup", force=True)


# --- Structurally vacuous arm: quality axes not applicable (#231) ---
#
# Observed on the first real run: the `baseline` arm (no LLM) produces no
# narrative, falls into the VACUOUS branch of metrics.py (grounding 1.0 / hallucination
# 0.0) and so "wins" the quality axes for absence of text to judge. The
# vacuous rule is correct for FALLBACK; here it must be marked as not interpretable.


def _analyze_rec(
    citta: str,
    zona: str,
    *,
    narrativa: str = "prosa reale",
    context_format: ContextFormat = "per_poi",
    temperature: float = 0.0,
    seed: int = 0,
    status: RunStatus = RunStatus.OK,
    poi_nel_prompt: tuple[str, ...] | None = ("1",),
    n_poi: int = 1,
) -> RunRecord:
    return _rec(
        "analyze-exp",
        citta,
        zona,
        grounding=0.700,
        hallucination=0.300,
        latency_ms=3000,
        cost_usd=0.005,
        narrativa=narrativa,
        context_format=context_format,
        temperature=temperature,
        seed=seed,
        status=status,
        poi_nel_prompt=poi_nel_prompt,
        n_poi=n_poi,
    )


def _silent_rec(citta: str, zona: str, *, narrativa: str = "") -> RunRecord:
    """Record of the arm without LLM: status OK, no narrative (by design)."""
    return _rec(
        "baseline-exp",
        citta,
        zona,
        grounding=1.000,
        hallucination=0.000,
        latency_ms=2,
        cost_usd=0.0,
        mode="baseline",
        model="baseline",
        narrativa=narrativa,
    )


def test_compare_records_flags_arm_that_never_produces_narrative() -> None:
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_silent_rec("Roma", "Colosseo")],
        label_a="analyze",
        label_b="baseline",
    )
    assert comparison.vacuous_arms == ["baseline"]


def test_compare_records_does_not_flag_arm_with_narrative_on_some_zones() -> None:
    """An arm mute on ONE zone but speaking on another is NOT vacuous."""
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo"), _analyze_rec("Milano", "Duomo")],
        [
            _silent_rec("Roma", "Colosseo"),
            _silent_rec("Milano", "Duomo", narrativa="ha parlato qui"),
        ],
        label_a="analyze",
        label_b="baseline",
    )
    assert comparison.vacuous_arms == []


def test_compare_records_flags_arm_whose_narrative_is_only_whitespace() -> None:
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_silent_rec("Roma", "Colosseo", narrativa="   \n  ")],
        label_a="analyze",
        label_b="baseline",
    )
    assert comparison.vacuous_arms == ["baseline"]


def test_markdown_marks_quality_axes_not_applicable_for_vacuous_arm() -> None:
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_silent_rec("Roma", "Colosseo")],
        label_a="analyze",
        label_b="baseline",
    )
    md = to_markdown(comparison)
    assert VACUOUS_CAVEAT_HEAD in md
    assert "`baseline`" in md
    # The caveat must precede the generic methodological note: it is read first.
    assert md.index(VACUOUS_CAVEAT_HEAD) < md.index("Nota metodologica")


def test_markdown_does_not_claim_operational_axes_are_compared_when_vacuous() -> None:
    """#237: the vacuity caveat must not promise an operational comparison that
    is never declared -- only raw data readable in the tables."""
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_silent_rec("Roma", "Colosseo")],
        label_a="analyze",
        label_b="baseline",
    )
    md = to_markdown(comparison)
    assert OPERATIONAL_AXES_NOTE in md
    assert "restano confrontabili" not in md.lower()


def test_markdown_has_no_quality_caveat_when_both_arms_generate() -> None:
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_analyze_rec("Roma", "Colosseo", narrativa="anche qui prosa")],
        label_a="claude",
        label_b="groq",
    )
    assert VACUOUS_CAVEAT_HEAD not in to_markdown(comparison)


# --- Vacuity per ZONE, not just per arm (#231, review C2) --------------
#
# `status=OK` with empty narrative is reachable in production: the Groq client
# returns `content or ""` without raising (llm/client.py), so the orchestrator
# answers fallback=False and the harness records OK. A single mute zone gets
# hallucination 0.000 vacuous and can shift the mean that decides the verdict.


def test_compare_records_flags_the_single_zone_where_an_arm_stays_silent() -> None:
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo"), _analyze_rec("Milano", "Duomo")],
        [
            _silent_rec("Roma", "Colosseo"),
            _silent_rec("Milano", "Duomo", narrativa="qui il modello ha parlato"),
        ],
        label_a="analyze",
        label_b="baseline",
    )
    # The arm is not vacuous (speaks on Milano), but Roma stays not interpretable.
    assert comparison.vacuous_arms == []
    assert [(z.citta, z.zona, z.arms) for z in comparison.vacuous_zones] == [
        ("Roma", "Colosseo", ["baseline"])
    ]


def test_compare_records_flags_zone_vacuous_for_no_anchors_not_just_silence() -> None:
    """#240: ``has_narrative`` alone does not cover "full narrative but zone without
    POIs/anchors to cite" -- its own boundary declared it (pre-#240 docstring
    of ``is_vacuous_arm``). A record with a NON-empty narrative but
    ``metrics.quality_vacuous=True`` (the vacuous branch of ``metrics.py::_grade`` for
    absence of anchors) must still end up in ``vacuous_zones``: before the
    fix it would have gone unnoticed because the text was there.
    """
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [
            _rec(
                "no-anchors-exp",
                "Roma",
                "Colosseo",
                grounding=1.000,
                hallucination=0.000,
                latency_ms=5,
                cost_usd=0.001,
                narrativa="Qualcosa accade nella zona, ma non ci sono POI da citare.",
                quality_vacuous=True,
            )
        ],
        label_a="analyze",
        label_b="no-anchors",
    )
    assert [(z.citta, z.zona, z.arms) for z in comparison.vacuous_zones] == [
        ("Roma", "Colosseo", ["no-anchors"])
    ]
    assert comparison.vacuous_arms == ["no-anchors"]


def test_compare_records_has_no_vacuous_zones_when_both_arms_speak_everywhere() -> None:
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_analyze_rec("Roma", "Colosseo", narrativa="anche qui prosa")],
        label_a="claude",
        label_b="groq",
    )
    assert comparison.vacuous_zones == []


def test_markdown_names_the_vacuous_zone_when_the_arm_is_not_wholly_silent() -> None:
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo"), _analyze_rec("Milano", "Duomo")],
        [
            _silent_rec("Roma", "Colosseo"),
            _silent_rec("Milano", "Duomo", narrativa="qui ha parlato"),
        ],
        label_a="analyze",
        label_b="baseline",
    )
    md = to_markdown(comparison)
    assert VACUOUS_CAVEAT_HEAD in md
    assert "Roma" in md


def test_markdown_puts_the_vacuity_warning_before_the_numbers() -> None:
    """The warning must precede the table: whoever reads must not first meet
    a quality delta that the warning then contradicts (review C1)."""
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_silent_rec("Roma", "Colosseo")],
        label_a="analyze",
        label_b="baseline",
    )
    md = to_markdown(comparison)
    assert md.index(VACUOUS_CAVEAT_HEAD) < md.index("| citta | zona |")


def test_is_vacuous_arm_is_false_for_an_arm_without_records() -> None:
    """An empty arm is not mute: it is not an arm (documented rule)."""
    assert is_vacuous_arm([]) is False


# --- #236: the report declares which variable the comparison isolates --------------


def _no_ontology_rec(
    citta: str,
    zona: str,
    *,
    model: str = "claude",
    temperature: float = 0.0,
    seed: int = 0,
    narrativa: str = "prosa senza ancoraggi",
    poi_nel_prompt: tuple[str, ...] | None = ("1",),
    n_poi: int = 1,
    status: RunStatus = RunStatus.OK,
) -> RunRecord:
    """Record of the ablated arm: with LLM, prompt without ontological contribution.

    Model and temperature coincide by default with those of
    :func:`_analyze_rec`: it is the real condition of the pair (the two experiments
    ``ablation-*-groq`` run on the same provider) and the only one in which the
    comparison really isolates the ontological contribution of the prompt. The tests of
    the CONFOUNDED comparison override them to make an arm diverge.
    """
    return _rec(
        "no-ontology-exp",
        citta,
        zona,
        grounding=0.400,
        hallucination=0.600,
        latency_ms=2800,
        cost_usd=0.004,
        mode="no_ontology_prompt",
        model=model,
        temperature=temperature,
        seed=seed,
        narrativa=narrativa,
        poi_nel_prompt=poi_nel_prompt,
        n_poi=n_poi,
        status=status,
    )


def test_comparison_declares_the_isolated_variable_for_the_c3_pair() -> None:
    """The analyze vs no_ontology_prompt comparison knows what it is isolating.

    The declaration is DERIVED from the modes of the records, not wired to the name
    of the experiment: any two arms stay freely labellable.
    """
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_no_ontology_rec("Roma", "Colosseo")],
        label_a="con-ontologia",
        label_b="senza-ontologia",
    )
    assert "con-ontologia" in comparison.isolated_variable
    assert "senza-ontologia" in comparison.isolated_variable


def test_comparison_declares_nothing_for_other_pairs() -> None:
    """On a pair that does not isolate the ontology the report stays as it was.

    ``analyze`` vs ``baseline`` (or two models) does not manipulate the ontological
    contribution: declaring that it isolates it would be false.
    """
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_silent_rec("Roma", "Colosseo")],
        label_a="analyze",
        label_b="baseline",
    )
    assert comparison.isolated_variable == ""
    assert ISOLATED_VARIABLE_HEAD not in to_markdown(comparison)


def test_markdown_declares_the_isolated_variable_before_the_numbers() -> None:
    """The declaration precedes the table and does not promise more than the proxy.

    It must be read BEFORE the deltas (like the vacuity warning), and must say that the
    two quality columns stay textual proxies: the comparison isolates the ontology,
    it does not certify the quality of the analysis.
    """
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_no_ontology_rec("Roma", "Colosseo")],
        label_a="con-ontologia",
        label_b="senza-ontologia",
    )
    md = to_markdown(comparison)
    assert ISOLATED_VARIABLE_HEAD in md
    assert md.index(ISOLATED_VARIABLE_HEAD) < md.index("| citta | zona |")
    assert md.index(ISOLATED_VARIABLE_HEAD) < md.index("Nota metodologica")


def test_isolated_variable_survives_in_the_json_report(tmp_path: Path) -> None:
    """The machine-readable deliverable also declares the isolated variable."""
    write_record(tmp_path, _analyze_rec("Roma", "Colosseo"))
    write_record(tmp_path, _no_ontology_rec("Roma", "Colosseo"))
    compare_experiments(
        tmp_path,
        "analyze-exp",
        "no-ontology-exp",
        label_a="con-ontologia",
        label_b="senza-ontologia",
        stem="c3",
    )
    payload = json.loads((tmp_path / "c3.json").read_text(encoding="utf-8"))
    assert "con-ontologia" in payload["isolated_variable"]


def test_isolated_variable_does_not_claim_a_shared_model_when_models_differ() -> None:
    """The pair of modes is not enough to promise "same model".

    The modes say what changes in the PROMPT, not with which generator the prose was
    written: comparing a Claude run with a Groq run the sentence "the two
    arms share model" is false, and it would attribute to the ontological
    anchoring a delta produced by two different models -- in a report that
    ends up in the evaluation chapter of the thesis.
    """
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_no_ontology_rec("Roma", "Colosseo", model="groq")],
        label_a="con-ontologia",
        label_b="senza-ontologia",
    )
    note = comparison.isolated_variable
    assert "condividono modello" not in note
    assert ISOLATED_VARIABLE_HEAD not in note
    # It is not enough to stay silent: the note must say why the delta is not
    # attributable to the ontology, and name the two models the reader is comparing.
    assert CONFOUNDED_VARIABLE_HEAD in note
    assert "`claude`" in note
    assert "`groq`" in note


def test_isolated_variable_does_not_claim_a_shared_temperature_when_it_varies() -> None:
    """Same model but different temperatures: the variable stays confounded.

    The temperature decides how far the prose moves from the prompt, i.e. precisely
    the axis that the proxies measure: promising "same temperature" without looking at
    the provenance would shift onto the ontology a sampling delta.
    """
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_no_ontology_rec("Roma", "Colosseo", temperature=0.7)],
        label_a="con-ontologia",
        label_b="senza-ontologia",
    )
    note = comparison.isolated_variable
    assert CONFOUNDED_VARIABLE_HEAD in note
    assert "temperatura" in note
    assert "0.7" in note


def test_isolated_variable_does_not_claim_isolation_when_context_format_differs() -> (
    None
):
    """Third dimension of the setting: the FORMAT of the POI block (#273).

    ``per_classe`` writes the set of hazards once per class instead of
    repeating it per point: it is a second prompt, and #273 exists precisely because it
    is not obvious which of the two makes more points be named -- i.e. it acts on the
    axis that the proxies measure. Comparing a grouped arm with the ablated one (which
    by construction is always ``per_poi``, the schema rejects the rest)
    would change format AND ontological contribution together.

    Defence in depth: no committed config uses ``per_classe`` today,
    so here no active bug is being closed but the door through which the
    first A/B on the format would enter.
    """
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo", context_format="per_classe")],
        [_no_ontology_rec("Roma", "Colosseo")],
        label_a="con-ontologia",
        label_b="senza-ontologia",
    )
    note = comparison.isolated_variable
    assert ISOLATED_VARIABLE_HEAD not in note
    assert CONFOUNDED_VARIABLE_HEAD in note
    assert "per_classe" in note
    assert "per_poi" in note


def test_isolated_variable_does_not_claim_a_shared_model_within_a_mixed_arm() -> None:
    """An arm that mixes two models has no model to declare.

    ``load_runs`` filters by experiment name: if the same experiment was
    re-run changing provider, the arm arrives mixed. There is no single value
    to say shared, so the note does not promise it.
    """
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo"), _analyze_rec("Milano", "Duomo")],
        [
            _no_ontology_rec("Roma", "Colosseo"),
            _no_ontology_rec("Milano", "Duomo", model="groq"),
        ],
        label_a="con-ontologia",
        label_b="senza-ontologia",
    )
    note = comparison.isolated_variable
    assert "condividono modello" not in note
    assert CONFOUNDED_VARIABLE_HEAD in note


def test_markdown_warns_before_the_numbers_when_the_pair_is_confounded() -> None:
    """The warning arrives in the report, and before the table like the declaration.

    It is the document that ends up in the evaluation chapter: reading the deltas and
    only afterwards discovering that the arms are not comparable is the order in which
    one misreads (same rule as the vacuity warning).
    """
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_no_ontology_rec("Roma", "Colosseo", model="groq")],
        label_a="con-ontologia",
        label_b="senza-ontologia",
    )
    md = to_markdown(comparison)
    assert CONFOUNDED_VARIABLE_HEAD in md
    assert md.index(CONFOUNDED_VARIABLE_HEAD) < md.index("| citta | zona |")


def test_the_c3_note_warns_that_speed_and_cost_come_from_prompt_length() -> None:
    """The ablated arm is faster and cheaper BY CONSTRUCTION.

    Its prompt carries no hazard, vulnerability or citations: it is shorter,
    so it consumes fewer tokens and takes less time whatever the quality
    of the prose. Whoever reads the operational table sees an advantage where there is
    just less text, so the report declares it next to the isolated variable.
    """
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_no_ontology_rec("Roma", "Colosseo")],
        label_a="con-ontologia",
        label_b="senza-ontologia",
    )
    assert PROMPT_LENGTH_SIDE_EFFECT in comparison.isolated_variable
    assert PROMPT_LENGTH_SIDE_EFFECT in to_markdown(comparison)


def test_the_prompt_length_warning_survives_a_confounded_pair() -> None:
    """The warning stays also when the variable is NOT isolated.

    The length of the two prompts is a property of the prompts: it does not depend on
    whether the arms share model and temperature, nor on how the quality axes
    go.
    """
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_no_ontology_rec("Roma", "Colosseo", model="groq")],
        label_a="con-ontologia",
        label_b="senza-ontologia",
    )
    assert CONFOUNDED_VARIABLE_HEAD in comparison.isolated_variable
    assert PROMPT_LENGTH_SIDE_EFFECT in comparison.isolated_variable


def test_the_prompt_length_warning_is_absent_from_other_pairs() -> None:
    """On ``analyze`` vs ``baseline`` there is no shorter prompt to explain."""
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_silent_rec("Roma", "Colosseo")],
        label_a="analyze",
        label_b="baseline",
    )
    assert PROMPT_LENGTH_SIDE_EFFECT not in to_markdown(comparison)


def test_is_ontology_isolating_pair_recognizes_only_the_c3_pair() -> None:
    """The predicate that the verdict consumes lives here, derived from the modes.

    It is the same recognition as the isolation note: a second copy
    downstream could diverge precisely on the pair that matters.
    """
    analyze = [_analyze_rec("Roma", "Colosseo")]
    assert is_ontology_isolating_pair(analyze, [_no_ontology_rec("Roma", "Colosseo")])
    assert not is_ontology_isolating_pair(analyze, [_silent_rec("Roma", "Colosseo")])
    assert not is_ontology_isolating_pair(analyze, [_analyze_rec("Roma", "Colosseo")])
    # MIXED arm: there is no pair of modes to recognise.
    mixed = [_analyze_rec("Roma", "Colosseo"), _no_ontology_rec("Milano", "Duomo")]
    ablated = [
        _no_ontology_rec("Roma", "Colosseo"),
        _no_ontology_rec("Milano", "Duomo"),
    ]
    assert not is_ontology_isolating_pair(mixed, ablated)


# --- #236: the consistency check looks at the right records, and also the seed ----


def test_a_fallback_record_does_not_confound_the_pair_by_itself() -> None:
    """The fallback placeholder is not a setting of the experiment.

    ``_structured_response`` always writes ``Repro(temperature=0.0)`` when the LLM
    drops, whatever temperature is configured: with a real temperature different
    from 0.0 the arm would look mixed and the report would declare a confound
    never configured. The means already exclude ERROR/FALLBACK (#163) -- the consistency
    check must look at the same records.
    """
    comparison = compare_records(
        [
            _analyze_rec("Roma", "Colosseo", temperature=0.7),
            _analyze_rec(
                "Milano",
                "Duomo",
                temperature=0.0,
                status=RunStatus.FALLBACK,
                narrativa="",
            ),
        ],
        [
            _no_ontology_rec("Roma", "Colosseo", temperature=0.7),
            _no_ontology_rec("Milano", "Duomo", temperature=0.7),
        ],
        label_a="con-ontologia",
        label_b="senza-ontologia",
    )
    note = comparison.isolated_variable
    assert ISOLATED_VARIABLE_HEAD in note
    assert CONFOUNDED_VARIABLE_HEAD not in note


def test_isolated_variable_does_not_claim_isolation_when_the_seed_differs() -> None:
    """Fourth dimension of the setting: the sampling seed.

    Two different seeds make the model sample two different prose from the same
    prompt: it is the axis that the proxies measure, so the delta would not be
    attributable to the ontological anchoring any more than it is with two
    different temperatures.
    """
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo", seed=0)],
        [_no_ontology_rec("Roma", "Colosseo", seed=7)],
        label_a="con-ontologia",
        label_b="senza-ontologia",
    )
    note = comparison.isolated_variable
    assert ISOLATED_VARIABLE_HEAD not in note
    assert CONFOUNDED_VARIABLE_HEAD in note
    assert "seed" in note
    assert "`7`" in note


def test_the_isolated_note_lists_the_seed_among_the_shared_settings() -> None:
    """What the note promises shared is what it verified."""
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo", seed=7)],
        [_no_ontology_rec("Roma", "Colosseo", seed=7)],
        label_a="con-ontologia",
        label_b="senza-ontologia",
    )
    assert ISOLATED_VARIABLE_HEAD in comparison.isolated_variable
    assert "seed" in comparison.isolated_variable


# --- #236 + #231: the isolation declaration does not contradict vacuity ---
#
# The two blocks that open the report speak of the SAME axes: one said that the
# quality delta measures the effect of the ontology, the other that on those axes the
# comparison is not interpretable in any direction. Both were printed,
# unconditionally, in the same document.


def _c3_pair_with_one_silent_zone() -> Comparison:
    """Isolated C3 pair (same model/temperature/format) with ONE mute zone.

    State reachable in production: the client returns ``content or ""`` without
    raising, so a zone with ``status=OK`` and empty narrative enters
    the aggregate with vacuous ``grounding``/``hallucination`` (#231).
    """
    return compare_records(
        [_analyze_rec("Roma", "Colosseo"), _analyze_rec("Milano", "Duomo")],
        [
            _no_ontology_rec("Roma", "Colosseo", narrativa=""),
            _no_ontology_rec("Milano", "Duomo"),
        ],
        label_a="con-ontologia",
        label_b="senza-ontologia",
    )


def test_isolation_does_not_claim_a_measured_delta_when_quality_axes_are_vacuous() -> (
    None
):
    """Only one block at a time can speak of the quality axes.

    With verified isolation AND vacuity the report asserted and denied the same
    thing two lines apart: "the delta measures the effect of the ontological
    anchoring" and, right below, "on these axes the comparison is NOT
    interpretable in any direction".
    """
    md = to_markdown(_c3_pair_with_one_silent_zone())
    assert VACUOUS_CAVEAT_HEAD in md
    assert ISOLATED_DELTA_CLAIM not in md


def test_isolation_still_says_what_changes_between_the_arms_when_vacuous() -> None:
    """The declaration does not disappear: it says what changes, without promising the
    delta.

    The design of the two arms stays isolated (same model, temperature,
    format) and the warning on the prompt length is still needed, because the
    operational table is printed anyway.
    """
    comparison = _c3_pair_with_one_silent_zone()
    note = comparison.isolated_variable
    assert ISOLATED_VARIABLE_HEAD in note
    assert VACUOUS_DELTA_CLAIM in note
    assert PROMPT_LENGTH_SIDE_EFFECT in note


def test_isolation_keeps_claiming_the_measured_delta_without_vacuity() -> None:
    """Non-regression: without vacuity the note stays as before."""
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_no_ontology_rec("Roma", "Colosseo")],
        label_a="con-ontologia",
        label_b="senza-ontologia",
    )
    md = to_markdown(comparison)
    assert ISOLATED_DELTA_CLAIM in md
    assert VACUOUS_DELTA_CLAIM not in md
    assert VACUOUS_CAVEAT_HEAD not in md


# --- #349: POI parity in the prompt is verified, not presumed ---


def _c3(a: list[RunRecord], b: list[RunRecord]) -> Comparison:
    return compare_records(a, b, label_a="con-ontologia", label_b="senza-ontologia")


def test_isolation_is_not_claimed_on_records_without_poi_in_prompt() -> None:
    """Records prior to #349 (``poi_nel_prompt`` absent): parity is not
    verifiable, so the variable is NOT declared isolated and the report says
    why, case by case."""
    note = _c3(
        [_analyze_rec("Roma", "Colosseo", poi_nel_prompt=None)],
        [_no_ontology_rec("Roma", "Colosseo", poi_nel_prompt=None)],
    ).isolated_variable
    assert ISOLATED_VARIABLE_HEAD not in note
    assert CONFOUNDED_VARIABLE_HEAD in note
    assert "Roma/Colosseo" in note
    assert "precedenti a #349" in note


def test_isolation_is_not_claimed_when_one_arm_lacks_poi_in_prompt() -> None:
    note = _c3(
        [_analyze_rec("Roma", "Colosseo")],
        [_no_ontology_rec("Roma", "Colosseo", poi_nel_prompt=None)],
    ).isolated_variable
    assert CONFOUNDED_VARIABLE_HEAD in note
    assert "`senza-ontologia`" in note
    assert "precedenti a #349" in note


def test_isolation_is_not_claimed_when_the_poi_sets_differ() -> None:
    """The case that #349 closes: 20 POIs against 9-12. Different sets = two
    variables."""
    note = _c3(
        [
            _analyze_rec("Roma", "Colosseo", poi_nel_prompt=("1", "2"), n_poi=3),
            _analyze_rec("Milano", "Duomo"),
        ],
        [
            _no_ontology_rec(
                "Roma", "Colosseo", poi_nel_prompt=("1", "2", "3"), n_poi=3
            ),
            _no_ontology_rec("Milano", "Duomo"),
        ],
    ).isolated_variable
    assert CONFOUNDED_VARIABLE_HEAD in note
    assert "Roma/Colosseo" in note
    assert "insiemi diversi" in note
    assert "Milano/Duomo" not in note


def test_isolation_holds_when_the_sets_match_in_a_different_order() -> None:
    """The order diverges by construction (the full one by relevance, the ablated
    in the retrieval one): the SET counts."""
    note = _c3(
        [_analyze_rec("Roma", "Colosseo", poi_nel_prompt=("2", "1"), n_poi=2)],
        [_no_ontology_rec("Roma", "Colosseo", poi_nel_prompt=("1", "2"), n_poi=2)],
    ).isolated_variable
    assert ISOLATED_VARIABLE_HEAD in note
    assert POI_SUBSET_VALIDITY_HEAD not in note


def test_isolation_ignores_zones_excluded_from_the_comparison() -> None:
    """A FALLBACK did not generate prose (``poi_nel_prompt`` None) and is already
    excluded from means and deltas: it does not make the variable confounded on the
    other zones."""
    note = _c3(
        [_analyze_rec("Roma", "Colosseo"), _analyze_rec("Milano", "Duomo")],
        [
            _no_ontology_rec("Roma", "Colosseo"),
            _no_ontology_rec(
                "Milano", "Duomo", poi_nel_prompt=None, status=RunStatus.FALLBACK
            ),
        ],
    ).isolated_variable
    assert ISOLATED_VARIABLE_HEAD in note


def test_isolation_with_a_cut_declares_the_subset_and_an_undetermined_direction() -> (
    None
):
    """Same POIs but not all of them: the report says so, with N out of M per case, who
    chose them and that the direction of the effect is not determined."""
    comparison = _c3(
        [
            _analyze_rec("Roma", "Colosseo", poi_nel_prompt=("3", "1"), n_poi=5),
            _analyze_rec("Milano", "Duomo"),
        ],
        [
            _no_ontology_rec("Roma", "Colosseo", poi_nel_prompt=("1", "3"), n_poi=5),
            _no_ontology_rec("Milano", "Duomo"),
        ],
    )
    note = comparison.isolated_variable
    assert ISOLATED_VARIABLE_HEAD in note
    assert POI_SUBSET_VALIDITY_HEAD in note
    assert "Roma/Colosseo 2 su 5" in note
    assert "Milano/Duomo" not in note
    assert "NON è determinato" in note
    assert ISOLATED_DELTA_CLAIM in to_markdown(comparison)


def test_isolated_note_says_the_points_are_the_same_and_verified() -> None:
    """The note said that the only difference was the PROMPT and that the ablated one
    receives "solo nome e classe dei punti": it stays true only by saying that they are
    the SAME points, verified on the records."""
    note = _c3(
        [_analyze_rec("Roma", "Colosseo")], [_no_ontology_rec("Roma", "Colosseo")]
    ).isolated_variable
    assert "stessi POI nel prompt" in note


def test_compare_experiments_writes_the_vacuity_warning_to_disk(tmp_path: Path) -> None:
    """AC3: the non-repeated path (the one the CLI `compare` calls) must
    carry the warning in the .md and `vacuous_arms` in the .json written to disk."""
    write_record(tmp_path, _analyze_rec("Roma", "Colosseo"))
    write_record(tmp_path, _silent_rec("Roma", "Colosseo"))
    compare_experiments(
        tmp_path,
        "analyze-exp",
        "baseline-exp",
        label_a="analyze",
        label_b="baseline",
        stem="cli",
    )
    md = (tmp_path / "cli.md").read_text(encoding="utf-8")
    assert VACUOUS_CAVEAT_HEAD in md
    payload = json.loads((tmp_path / "cli.json").read_text(encoding="utf-8"))
    assert payload["vacuous_arms"] == ["baseline"]
    assert payload["vacuous_zones"][0]["zona"] == "Colosseo"
    # #238: the same explicit field of the repeated report, here too -- a
    # reader must not inspect the shape of vacuous_arms/vacuous_zones to
    # know whether the quality axes are readable.
    assert payload["quality_verdict"]["applicable"] is False
    assert payload["quality_verdict"]["vacuous_arms"] == ["baseline"]
    assert payload["quality_verdict"]["reason"] == (
        "manca la narrativa su cui i proxy di qualità si pronunciano: "
        "metriche vacue (#231)"
    )
    # ensure_ascii=False: the very same text must not end up with a different
    # encoding depending on whether `compare` or
    # `compare-repeated` wrote it (#238).
    assert "qualità" in (tmp_path / "cli.json").read_text(encoding="utf-8")


def test_write_comparison_json_reports_quality_verdict_applicable_when_not_vacuous(
    tmp_path: Path,
) -> None:
    """#238: same field as the repeated path, here at `applicable: True`."""
    cmp = compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base")
    write_comparison(tmp_path, cmp, "ablation")
    payload = json.loads((tmp_path / "ablation.json").read_text(encoding="utf-8"))
    assert payload["quality_verdict"]["applicable"] is True
    assert payload["quality_verdict"]["vacuous_arms"] == []
    assert payload["quality_verdict"]["reason"] == ""
    # The keys already written by #33/#157 stay at the usual flat level.
    assert payload["label_a"] == "full"
