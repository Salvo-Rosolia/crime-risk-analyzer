from pathlib import Path

from pytest import MonkeyPatch

from crime_risk_analyzer.eval.aggregate import (
    load_runs,
    to_csv,
    to_markdown,
    write_tables,
)
from crime_risk_analyzer.eval.harness import write_record
from crime_risk_analyzer.eval.schema import Metrics, Provenance, RunRecord, RunStatus


def _rec(
    run_id: str,
    experiment: str,
    status: RunStatus = RunStatus.OK,
    quality_vacuous: bool | None = False,
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        experiment=experiment,
        citta="Roma",
        zona="Centro",
        mode="analyze",
        model_id="claude-sonnet-4-6",
        status=status,
        metrics=Metrics(
            grounding=1.0,
            hallucination=0.0,
            latency_ms=120,
            cost_usd=0.003,
            quality_vacuous=quality_vacuous,
        ),
        narrativa="x",
        n_poi=2,
        provenance=Provenance(
            code_commit="a",
            ontology_hash="b",
            snapshot_id=run_id,
            model_id="claude-sonnet-4-6",
            prompt_hash="p",
            temperature=0.0,
            seed=0,
            experiment=experiment,
        ),
    )


def test_load_runs_filters_by_experiment(tmp_path: Path) -> None:
    write_record(tmp_path, _rec("exp1__a", "exp1"))
    write_record(tmp_path, _rec("exp2__a", "exp2"))
    assert {r.experiment for r in load_runs(tmp_path, experiment="exp1")} == {"exp1"}
    assert len(load_runs(tmp_path)) == 2
    assert load_runs(tmp_path / "nonexistent") == []


def test_to_csv_has_header_and_row() -> None:
    csv = to_csv([_rec("r1", "exp")])
    lines = csv.strip().splitlines()
    expected_header = (
        "run_id,citta,zona,mode,model_id,status,"
        "grounding,hallucination,quality_vacuous,latency_ms,cost_usd"
    )
    assert lines[0] == expected_header
    assert "r1" in lines[1]


def test_to_csv_marks_vacuous_quality_metrics() -> None:
    """#240: vacuous grounding/hallucination (no narrative to judge) are
    recognisable also outside the comparison report (#231), here in the per-run
    table and in the CSV -- same marking mechanism for both artefacts.
    """
    csv = to_csv([_rec("r1", "exp", quality_vacuous=True)])
    row = csv.strip().splitlines()[1]
    assert row.split(",")[8] == "true"

    csv = to_csv([_rec("r2", "exp", quality_vacuous=False)])
    row = csv.strip().splitlines()[1]
    assert row.split(",")[8] == "false"


def test_to_csv_leaves_vacuous_column_blank_for_legacy_records() -> None:
    """A pre-#240 record (``quality_vacuous`` absent, default ``None``) must not
    read as "not vacuous": the column stays empty, not "false"."""
    csv = to_csv([_rec("r1", "exp", quality_vacuous=None)])
    row = csv.strip().splitlines()[1]
    assert row.split(",")[8] == ""


def test_to_markdown_marks_vacuous_quality_metrics() -> None:
    md = to_markdown([_rec("r1", "exp", quality_vacuous=True)])
    assert "quality_vacuous" in md
    assert "| true |" in md


def test_markdown_flags_error(tmp_path: Path) -> None:
    md = to_markdown([_rec("r1", "exp", status=RunStatus.ERROR)])
    assert "error" in md
    assert "|" in md  # markdown table
    assert "fallback" in to_markdown([_rec("r2", "exp", status=RunStatus.FALLBACK)])


def test_write_tables_writes_csv_and_md(tmp_path: Path) -> None:
    write_record(tmp_path, _rec("exp__a", "exp"))
    csv_path, md_path = write_tables(tmp_path, "exp")
    assert csv_path == tmp_path / "exp.csv"
    assert md_path == tmp_path / "exp.md"
    assert csv_path.exists() and md_path.exists()
    assert "run_id" in csv_path.read_text(encoding="utf-8")
    assert "exp__a" in csv_path.read_text(encoding="utf-8")


def test_write_tables_csv_uses_newline_empty(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Regression #103: the CSV write must pass ``newline=""``.

    ``to_csv()`` uses ``csv.writer`` which already emits ``\\r\\n`` terminators; if
    ``write_text`` opens the file in text mode without ``newline=""``, on Windows the
    ``\\n`` gets re-translated to ``\\r\\n`` producing ``\\r\\r\\n`` (spurious blank
    lines, CSV corrupt for Excel/pandas/csv.reader).

    The guard is DETERMINISTIC and cross-platform because it does not inspect the bytes
    on disk (the text-mode translation is Windows-only: on Linux an assert on the bytes
    would pass even with the bug), but verifies the KWARG passed to the code: it spies
    ``Path.write_text`` and demands ``newline=""`` on the write of the ``.csv``.
    This fails on the buggy behaviour on EVERY platform, CI included.
    """
    write_record(tmp_path, _rec("exp__a", "exp"))

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
    csv_path, _md_path = write_tables(tmp_path, "exp")

    # Primary guard, cross-platform: the code explicitly passes newline="".
    assert csv_newline_kwargs == [""]
    # Supplementary assert (sensitive only on Windows): no spurious row.
    assert b"\r\r\n" not in csv_path.read_bytes()
