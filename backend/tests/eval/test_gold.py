import csv
import io
from pathlib import Path

import pytest

from crime_risk_analyzer.eval.gold import (
    KeptRiskRow,
    build_precision_report,
    collect_kept_risks,
    load_worksheet,
    write_gold_worksheet,
    write_precision_report,
)
from crime_risk_analyzer.eval.schema import Metrics, Provenance, RunRecord, RunStatus
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
    run_id: str, *, status: RunStatus, narrativa: str, risk_models: list[RiskModel]
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        experiment="exp",
        citta="Roma",
        zona="Centro",
        mode="analyze",
        model_id="m",
        status=status,
        metrics=Metrics(grounding=1.0, hallucination=0.0, latency_ms=1, cost_usd=0.0),
        narrativa=narrativa,
        n_poi=1,
        risk_models=risk_models,
        provenance=_prov(run_id),
    )


def test_collect_kept_risks_keeps_only_hazards_cited_in_narrativa() -> None:
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
                        source="X",
                    )
                ],
            )
        ],
    )
    path = write_gold_worksheet(tmp_path, [rec])
    assert path.exists()
    reloaded = load_worksheet(path)
    assert len(reloaded) == 1
    assert reloaded[0].hazard == "Robbery"
    assert reloaded[0].fonte_verificata is None


def _mark_fonte_verificata(path: Path, *, value: str) -> None:
    """Riscrive il foglio impostando ``fonte_verificata`` sulla PRIMA riga dati.

    Individua la colonna per NOME (non per posizione fissa): un replace su
    stringa fissa come ``",,"`` dipenderebbe dall'esatto layout di colonne
    vuote prodotto da ``write_gold_worksheet`` e si romperebbe silenziosamente
    se un'altra colonna vuota lo precedesse. Simula la compilazione manuale
    del foglio da parte dell'autore senza assumere nulla sulla posizione.
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
                        source="X",
                    )
                ],
            )
        ],
    )
    worksheet_path = write_gold_worksheet(tmp_path, [rec])
    # Simula la compilazione manuale: imposta fonte_verificata=true sulla riga.
    _mark_fonte_verificata(worksheet_path, value="true")
    csv_path, md_path = write_precision_report(tmp_path, worksheet_path)
    assert csv_path.exists() and md_path.exists()
    assert "precisione del filtro: 100.0%" in md_path.read_text(encoding="utf-8")
