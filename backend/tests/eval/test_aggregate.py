from pathlib import Path

from crime_risk_analyzer.eval.aggregate import (
    load_runs,
    to_csv,
    to_markdown,
    write_tables,
)
from crime_risk_analyzer.eval.harness import write_record
from crime_risk_analyzer.eval.schema import Metrics, Provenance, RunRecord, RunStatus


def _rec(run_id: str, experiment: str, status: RunStatus = RunStatus.OK) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        experiment=experiment,
        citta="Roma",
        zona="Centro",
        mode="analyze",
        model_id="claude-sonnet-4-6",
        status=status,
        metrics=Metrics(
            grounding=1.0, hallucination=0.0, latency_ms=120, cost_usd=0.003
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
        "grounding,hallucination,latency_ms,cost_usd"
    )
    assert lines[0] == expected_header
    assert "r1" in lines[1]


def test_markdown_flags_error(tmp_path: Path) -> None:
    md = to_markdown([_rec("r1", "exp", status=RunStatus.ERROR)])
    assert "error" in md
    assert "|" in md  # tabella markdown
    assert "fallback" in to_markdown([_rec("r2", "exp", status=RunStatus.FALLBACK)])


def test_write_tables_writes_csv_and_md(tmp_path: Path) -> None:
    write_record(tmp_path, _rec("exp__a", "exp"))
    csv_path, md_path = write_tables(tmp_path, "exp")
    assert csv_path == tmp_path / "exp.csv"
    assert md_path == tmp_path / "exp.md"
    assert csv_path.exists() and md_path.exists()
    assert "run_id" in csv_path.read_text(encoding="utf-8")
    assert "exp__a" in csv_path.read_text(encoding="utf-8")
