import csv
import io
import sys
from pathlib import Path

import pytest

import crime_risk_analyzer.eval.__main__ as eval_main
from crime_risk_analyzer.eval.gold import (
    WORKSHEET_FILENAME,
    KeptRiskRow,
    build_precision_report,
    collect_kept_risks,
    load_worksheet,
    write_gold_worksheet,
    write_precision_report,
)
from crime_risk_analyzer.eval.schema import (
    Metrics,
    Mode,
    Provenance,
    RunRecord,
    RunStatus,
)
from crime_risk_analyzer.rag.generation import RiskItem, RiskModel


def _prov(run_id: str) -> Provenance:
    return Provenance(
        code_commit="a",
        ontology_hash="b",
        snapshot_id=run_id,
        model_id="m",
        prompt_hash="p",
        temperature=0.0,
        seed=0,
        experiment="exp",
    )


def _rec(
    run_id: str,
    *,
    status: RunStatus,
    narrativa: str,
    risk_models: list[RiskModel],
    mode: Mode = "analyze",
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        experiment="exp",
        citta="Roma",
        zona="Centro",
        mode=mode,
        model_id="m",
        status=status,
        metrics=Metrics(grounding=1.0, hallucination=0.0, latency_ms=1, cost_usd=0.0),
        narrativa=narrativa,
        n_poi=1,
        risk_models=risk_models,
        provenance=_prov(run_id),
    )


def _cited_record(run_id: str = "r1", *, mode: Mode = "analyze") -> RunRecord:
    """Record with ONE risk cited in the narrative (one annotatable row)."""
    return _rec(
        run_id,
        status=RunStatus.OK,
        narrativa=(
            "Overview.\n\n[ONTOLOGIA]\nRapina al viaggiatore vicino alla stazione."
        ),
        risk_models=[
            RiskModel(
                poi_id="node/1",
                poi="Stazione",
                risks=[
                    RiskItem(
                        hazard="Robbery",
                        confidence="verificato",
                        tag="ONTOLOGIA",
                        hazard_label_it="Rapina al viaggiatore",
                        source="X",
                    )
                ],
            )
        ],
        mode=mode,
    )


def test_collect_kept_risks_keeps_only_hazards_cited_in_narrative() -> None:
    rec = _rec(
        "r1",
        status=RunStatus.OK,
        narrativa=(
            "Overview.\n\n[ONTOLOGIA]\nRapina al viaggiatore vicino alla stazione."
        ),
        risk_models=[
            RiskModel(
                poi_id="node/1",
                poi="Stazione",
                risks=[
                    RiskItem(
                        hazard="Robbery",
                        confidence="verificato",
                        tag="ONTOLOGIA",
                        hazard_label_it="Rapina al viaggiatore",
                        source="Railway_station → havingHazard → Robbery",
                    ),
                    RiskItem(
                        hazard="Cyber_attack",
                        confidence="verificato",
                        tag="ONTOLOGIA",
                        hazard_label_it="Attacco informatico",
                        source="Railway_station → havingHazard → Cyber_attack",
                    ),
                ],
            )
        ],
    )
    rows = collect_kept_risks([rec])
    assert len(rows) == 1
    assert rows[0].hazard == "Robbery"
    assert rows[0].source == "Railway_station → havingHazard → Robbery"
    assert rows[0].fonte_verificata is None
    assert rows[0].note == ""


def test_collect_kept_risks_skips_non_ok_status() -> None:
    rec = _rec(
        "r2",
        status=RunStatus.FALLBACK,
        narrativa="",
        risk_models=[
            RiskModel(
                poi_id="node/1",
                poi="Stazione",
                risks=[
                    RiskItem(hazard="Robbery", confidence="verificato", tag="ONTOLOGIA")
                ],
            )
        ],
    )
    assert collect_kept_risks([rec]) == []


def test_precision_report_none_when_nothing_annotated() -> None:
    row = KeptRiskRow(
        run_id="r",
        citta="Roma",
        zona="Centro",
        poi="P",
        hazard="Robbery",
        tag="ONTOLOGIA",
        confidence="verificato",
        source=None,
    )
    report = build_precision_report([row])
    assert report.n_totale == 1
    assert report.n_annotati == 0
    assert report.precisione_filtro is None
    assert report.allucinazioni_residue is None


def test_precision_report_all_verified() -> None:
    row = KeptRiskRow(
        run_id="r",
        citta="Roma",
        zona="Centro",
        poi="P",
        hazard="Robbery",
        tag="ONTOLOGIA",
        confidence="verificato",
        source="x",
        fonte_verificata=True,
    )
    report = build_precision_report([row])
    assert report.precisione_filtro == 1.0
    assert report.allucinazioni_residue == 0.0


def test_precision_report_all_fabricated() -> None:
    row = KeptRiskRow(
        run_id="r",
        citta="Roma",
        zona="Centro",
        poi="P",
        hazard="Robbery",
        tag="ONTOLOGIA",
        confidence="verificato",
        source="x",
        fonte_verificata=False,
    )
    report = build_precision_report([row])
    assert report.precisione_filtro == 0.0
    assert report.allucinazioni_residue == 1.0


def test_precision_report_mixed() -> None:
    verified = KeptRiskRow(
        run_id="r1",
        citta="Roma",
        zona="Centro",
        poi="P",
        hazard="Robbery",
        tag="ONTOLOGIA",
        confidence="verificato",
        source="x",
        fonte_verificata=True,
    )
    fabricated = KeptRiskRow(
        run_id="r2",
        citta="Roma",
        zona="Centro",
        poi="P",
        hazard="Cyber_attack",
        tag="ONTOLOGIA",
        confidence="verificato",
        source="y",
        fonte_verificata=False,
    )
    report = build_precision_report([verified, fabricated])
    assert report.n_annotati == 2
    assert report.precisione_filtro == pytest.approx(0.5)
    assert report.allucinazioni_residue == pytest.approx(0.5)


def test_write_gold_worksheet_and_reread_roundtrip(tmp_path: Path) -> None:
    path = write_gold_worksheet(tmp_path, [_cited_record()])
    assert path.exists()
    reloaded = load_worksheet(path)
    assert len(reloaded) == 1
    assert reloaded[0].hazard == "Robbery"
    assert reloaded[0].fonte_verificata is None


def _mark_verified_source(path: Path, *, value: str) -> None:
    """Rewrite the sheet setting ``fonte_verificata`` on the FIRST data row.

    Finds the column by NAME (not by fixed position): a replace on a fixed
    string like ``",,"`` would depend on the exact layout of empty columns
    produced by ``write_gold_worksheet`` and would silently break
    if another empty column preceded it. It simulates the manual filling
    of the sheet by the author without assuming anything about the position.
    """
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    header, data_rows = rows[0], rows[1:]
    col = header.index("fonte_verificata")
    data_rows[0][col] = value
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(data_rows)
    path.write_text(buf.getvalue(), encoding="utf-8", newline="")


def test_write_precision_report_after_manual_edit(tmp_path: Path) -> None:
    worksheet_path = write_gold_worksheet(tmp_path, [_cited_record()])
    # Simulate the manual filling: set fonte_verificata=true on the row.
    _mark_verified_source(worksheet_path, value="true")
    csv_path, md_path = write_precision_report(tmp_path, worksheet_path)
    assert csv_path.exists() and md_path.exists()
    assert "precisione del filtro: 100.0%" in md_path.read_text(encoding="utf-8")


# --- validation of the hand-annotated values (fail-loud on unknown tokens) ------


@pytest.mark.parametrize(
    "value",
    [
        "true",
        "TRUE",
        "vero",
        "VERO",
        "v",
        "1",
        "si",
        "sì",
        "Sì",
        "s",
        "x",
        "X",
        "yes",
        "y",
    ],
)
def test_load_worksheet_reads_truthy_tokens_as_true(tmp_path: Path, value: str) -> None:
    """An Italian annotator writes "vero"/"x"/"sì", not only ``true``.

    Before, these values silently collapsed to ``False``, corrupting
    precisely ``allucinazioni_residue`` -- the number for which the mechanism exists.
    """
    path = write_gold_worksheet(tmp_path, [_cited_record()])
    _mark_verified_source(path, value=value)
    assert load_worksheet(path)[0].fonte_verificata is True


@pytest.mark.parametrize("value", ["false", "FALSO", "falso", "f", "0", "no", "N", "n"])
def test_load_worksheet_reads_falsy_tokens_as_false(tmp_path: Path, value: str) -> None:
    path = write_gold_worksheet(tmp_path, [_cited_record()])
    _mark_verified_source(path, value=value)
    assert load_worksheet(path)[0].fonte_verificata is False


def test_load_worksheet_reads_blank_as_not_annotated(tmp_path: Path) -> None:
    """Empty cell = "nobody has looked yet", not "the source does not hold up"."""
    path = write_gold_worksheet(tmp_path, [_cited_record()])
    _mark_verified_source(path, value="   ")
    assert load_worksheet(path)[0].fonte_verificata is None


def test_load_worksheet_rejects_unrecognized_value(tmp_path: Path) -> None:
    """Fail-loud: a value outside the vocabulary does NOT silently become ``False``.

    The message names the value and the run, so whoever filled the sheet
    knows which cell to correct.
    """
    path = write_gold_worksheet(tmp_path, [_cited_record("r-strana")])
    _mark_verified_source(path, value="boh")
    with pytest.raises(ValueError, match="boh") as exc:
        load_worksheet(path)
    assert "r-strana" in str(exc.value)


# --- guard on overwriting human work (--force) -----------------


def test_write_gold_worksheet_refuses_to_overwrite_without_force(
    tmp_path: Path,
) -> None:
    """The hand-annotated sheet is not recomputable: without ``force`` it refuses.

    Same guard as ``capture``/``compare``, here on an output whose cost of
    reconstruction is human.
    """
    path = write_gold_worksheet(tmp_path, [_cited_record()])
    _mark_verified_source(path, value="true")
    # Raw bytes (not ``read_text``): the comparison must also catch a
    # rewrite that changes only the line terminators (#103/#241).
    before = path.read_bytes()

    with pytest.raises(FileExistsError, match="force"):
        write_gold_worksheet(tmp_path, [_cited_record()])

    # The annotated file stayed intact: the refusal happens BEFORE writing.
    assert path.read_bytes() == before


def test_write_gold_worksheet_force_overwrites(tmp_path: Path) -> None:
    path = write_gold_worksheet(tmp_path, [_cited_record()])
    _mark_verified_source(path, value="true")

    write_gold_worksheet(tmp_path, [_cited_record()], force=True)

    assert load_worksheet(path)[0].fonte_verificata is None


def test_write_gold_worksheet_overwrites_empty_file_without_force(
    tmp_path: Path,
) -> None:
    """An empty file (interrupted write) contains no work to protect."""
    (tmp_path / "gold").mkdir(parents=True)
    (tmp_path / "gold" / WORKSHEET_FILENAME).write_text("", encoding="utf-8")

    path = write_gold_worksheet(tmp_path, [_cited_record()])

    assert len(load_worksheet(path)) == 1


# --- legal constraint: no numeric danger scoring ---------------


def test_kept_risk_row_has_no_numeric_scoring_field() -> None:
    """Legal constraint (_project.md, Constraints): no numeric scoring.

    ``KeptRiskRow`` is of the same family as ``RiskItem``/``RiskModel``
    (it carries hazard/tag/confidence) and crosses the annotation sheet: a
    ``score``/``gravita``/``risk_level`` field added here would break
    the exact set, forcing a conscious review.
    """
    assert set(KeptRiskRow.model_fields) == {
        "run_id",
        "citta",
        "zona",
        "poi",
        "hazard",
        "tag",
        "confidence",
        "source",
        "fonte_verificata",
        "note",
    }


# --- CLI dispatch of the two gold verbs (main() end-to-end, mocked functions) ---


def _set_argv(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["crime_risk_analyzer.eval", *args])


def test_main_gold_sample_filters_records_by_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``gold-sample`` forwards to ``write_gold_worksheet`` ONLY the runs of the
    requested mode, and reports on screen how many rows it wrote."""
    analyze = _cited_record("r-analyze", mode="analyze")
    baseline = _cited_record("r-baseline", mode="baseline")
    seen: dict[str, object] = {}

    def fake_load_runs(
        results_dir: Path, experiment: str | None = None
    ) -> list[RunRecord]:
        seen["results_dir"] = results_dir
        seen["experiment"] = experiment
        return [analyze, baseline]

    def fake_write(
        results_dir: Path, records: list[RunRecord], *, force: bool = False
    ) -> Path:
        seen["records"] = records
        seen["force"] = force
        return results_dir / "gold" / WORKSHEET_FILENAME

    monkeypatch.setattr(eval_main, "load_runs", fake_load_runs)
    monkeypatch.setattr(eval_main, "write_gold_worksheet", fake_write)
    _set_argv(
        monkeypatch, "gold-sample", "--results", str(tmp_path), "--experiment", "exp"
    )

    assert eval_main.main() == 0
    assert seen["results_dir"] == tmp_path
    assert seen["experiment"] == "exp"
    assert seen["records"] == [analyze]
    assert seen["force"] is False
    assert "rischi da annotare: 1" in capsys.readouterr().out


def test_main_gold_sample_reports_an_empty_worksheet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zero rows must be VISIBLE: a sheet with just the header and exit code 0 is
    otherwise indistinguishable from a success with data."""
    not_cited = _rec(
        "r1",
        status=RunStatus.OK,
        narrativa="Overview.\n\n[ONTOLOGIA]\nNessun rischio riconducibile.",
        risk_models=[
            RiskModel(
                poi_id="node/1",
                poi="Stazione",
                risks=[
                    RiskItem(hazard="Robbery", confidence="verificato", tag="ONTOLOGIA")
                ],
            )
        ],
    )

    def fake_load_runs(
        results_dir: Path, experiment: str | None = None
    ) -> list[RunRecord]:
        return [not_cited]

    def fake_write(
        results_dir: Path, records: list[RunRecord], *, force: bool = False
    ) -> Path:
        return results_dir / "gold" / WORKSHEET_FILENAME

    monkeypatch.setattr(eval_main, "load_runs", fake_load_runs)
    monkeypatch.setattr(eval_main, "write_gold_worksheet", fake_write)
    _set_argv(monkeypatch, "gold-sample", "--results", str(tmp_path))

    assert eval_main.main() == 0
    assert "rischi da annotare: 0" in capsys.readouterr().out


def test_main_gold_sample_forwards_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--force`` reaches ``write_gold_worksheet`` (otherwise the guard
    would be impossible to bypass from the command line)."""
    seen: dict[str, object] = {}

    def fake_write(
        results_dir: Path, records: list[RunRecord], *, force: bool = False
    ) -> Path:
        seen["force"] = force
        return results_dir / "gold" / WORKSHEET_FILENAME

    def fake_load_runs(
        results_dir: Path, experiment: str | None = None
    ) -> list[RunRecord]:
        return []

    monkeypatch.setattr(eval_main, "load_runs", fake_load_runs)
    monkeypatch.setattr(eval_main, "write_gold_worksheet", fake_write)
    _set_argv(monkeypatch, "gold-sample", "--results", str(tmp_path), "--force")

    assert eval_main.main() == 0
    assert seen["force"] is True


def test_main_gold_report_defaults_to_the_standard_worksheet_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ``--worksheet`` the sheet written by ``gold-sample`` is read."""
    calls: list[tuple[Path, Path]] = []

    def fake_report(results_dir: Path, worksheet_path: Path) -> tuple[Path, Path]:
        calls.append((results_dir, worksheet_path))
        return results_dir / "a.csv", results_dir / "a.md"

    monkeypatch.setattr(eval_main, "write_precision_report", fake_report)
    _set_argv(monkeypatch, "gold-report", "--results", str(tmp_path))

    assert eval_main.main() == 0
    assert calls == [(tmp_path, tmp_path / "gold" / WORKSHEET_FILENAME)]


def test_main_gold_report_uses_explicit_worksheet_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, Path]] = []

    def fake_report(results_dir: Path, worksheet_path: Path) -> tuple[Path, Path]:
        calls.append((results_dir, worksheet_path))
        return results_dir / "a.csv", results_dir / "a.md"

    monkeypatch.setattr(eval_main, "write_precision_report", fake_report)
    other = tmp_path / "altro.csv"
    _set_argv(
        monkeypatch,
        "gold-report",
        "--results",
        str(tmp_path),
        "--worksheet",
        str(other),
    )

    assert eval_main.main() == 0
    assert calls == [(tmp_path, other)]
