import sys
from pathlib import Path

import pytest

import crime_risk_analyzer.eval.__main__ as eval_main
from crime_risk_analyzer.eval.cli import build_parser
from crime_risk_analyzer.eval.gold import (
    AgreementReport,
    build_agreement_report,
    to_csv,
    to_markdown,
    write_agreement_report,
)
from crime_risk_analyzer.eval.harness import write_record
from crime_risk_analyzer.eval.schema import (
    GoldAnnotation,
    Metrics,
    Provenance,
    RunRecord,
    RunStatus,
)


def _rec(
    run_id: str,
    *,
    proxy_grounding: float,
    proxy_hallucination: float,
    gold: GoldAnnotation | None,
) -> RunRecord:
    """RunRecord con metriche proxy note e annotazione gold (o assente)."""
    return RunRecord(
        run_id=run_id,
        experiment="exp",
        citta="Roma",
        zona="Centro",
        mode="analyze",
        model_id="claude-sonnet-4-6",
        status=RunStatus.OK,
        metrics=Metrics(
            grounding=proxy_grounding,
            hallucination=proxy_hallucination,
            latency_ms=100,
            cost_usd=0.001,
        ),
        narrativa="x",
        n_poi=1,
        annotazione_manuale=gold,
        provenance=Provenance(
            code_commit="a",
            ontology_hash="b",
            snapshot_id=run_id,
            model_id="claude-sonnet-4-6",
            prompt_hash="p",
            temperature=0.0,
            seed=0,
            experiment="exp",
        ),
    )


def _gold(grounding: float, hallucination: float) -> GoldAnnotation:
    return GoldAnnotation(grounding=grounding, hallucination=hallucination)


# --- GoldAnnotation (schema, additivo) ---------------------------------------


def test_gold_annotation_bounds_validation() -> None:
    with pytest.raises(ValueError):
        GoldAnnotation(grounding=1.5, hallucination=0.0)


def test_run_record_accepts_gold_annotation_roundtrip() -> None:
    rec = _rec("r", proxy_grounding=1.0, proxy_hallucination=0.0, gold=_gold(0.9, 0.1))
    reloaded = RunRecord.model_validate_json(rec.model_dump_json())
    assert reloaded.annotazione_manuale is not None
    assert reloaded.annotazione_manuale.hallucination == pytest.approx(0.1)


# --- build_agreement_report --------------------------------------------------


def test_build_pairs_only_annotated_records() -> None:
    records = [
        _rec("a", proxy_grounding=1.0, proxy_hallucination=0.0, gold=_gold(1.0, 0.0)),
        _rec("b", proxy_grounding=0.5, proxy_hallucination=0.5, gold=None),
    ]
    report = build_agreement_report(records)
    assert report.n_runs_total == 2
    assert report.n_annotated == 1
    assert [row.run_id for row in report.rows] == ["a"]


def test_pearson_perfect_when_proxy_equals_gold() -> None:
    records = [
        _rec("a", proxy_grounding=0.0, proxy_hallucination=0.0, gold=_gold(1.0, 0.0)),
        _rec("b", proxy_grounding=0.5, proxy_hallucination=0.5, gold=_gold(0.5, 0.5)),
        _rec("c", proxy_grounding=1.0, proxy_hallucination=1.0, gold=_gold(0.0, 1.0)),
    ]
    report = build_agreement_report(records)
    assert report.hallucination.pearson == pytest.approx(1.0)
    assert report.hallucination.mean_abs_error == pytest.approx(0.0)


def test_mean_abs_error_captures_systematic_bias() -> None:
    # gold = proxy + 0.2 su tutti: correlazione perfetta ma scarto sistematico.
    records = [
        _rec("a", proxy_grounding=1.0, proxy_hallucination=0.0, gold=_gold(0.8, 0.2)),
        _rec("b", proxy_grounding=0.6, proxy_hallucination=0.4, gold=_gold(0.4, 0.6)),
        _rec("c", proxy_grounding=0.2, proxy_hallucination=0.8, gold=_gold(0.0, 1.0)),
    ]
    report = build_agreement_report(records)
    assert report.hallucination.pearson == pytest.approx(1.0)
    assert report.hallucination.mean_abs_error == pytest.approx(0.2)
    assert report.hallucination.mean_proxy == pytest.approx(0.4)
    assert report.hallucination.mean_gold == pytest.approx(0.6)


def test_pearson_none_when_fewer_than_two_annotated() -> None:
    records = [
        _rec("a", proxy_grounding=1.0, proxy_hallucination=0.0, gold=_gold(1.0, 0.0)),
    ]
    report = build_agreement_report(records)
    assert report.hallucination.pearson is None


def test_pearson_none_when_no_variance() -> None:
    # Proxy costante -> varianza nulla -> correlazione di Pearson indefinita.
    records = [
        _rec("a", proxy_grounding=1.0, proxy_hallucination=0.0, gold=_gold(0.2, 0.3)),
        _rec("b", proxy_grounding=1.0, proxy_hallucination=0.0, gold=_gold(0.4, 0.7)),
    ]
    report = build_agreement_report(records)
    assert report.hallucination.pearson is None


def test_confusion_matrix_flags_proxy_under_and_over_counting() -> None:
    # threshold di default 0.0: "allucinazione presente" == valore > 0.
    records = [
        # TP: proxy e gold concordano sul "presente"
        _rec("tp", proxy_grounding=0.5, proxy_hallucination=0.5, gold=_gold(0.5, 0.5)),
        # FP: proxy segnala, umano no (sovra-conteggio)
        _rec("fp", proxy_grounding=0.5, proxy_hallucination=0.5, gold=_gold(1.0, 0.0)),
        # FN: proxy tace, umano segnala (SOTTO-conteggio: la preoccupazione di #109)
        _rec("fn", proxy_grounding=1.0, proxy_hallucination=0.0, gold=_gold(0.5, 0.5)),
        # TN: entrambi "assente"
        _rec("tn", proxy_grounding=1.0, proxy_hallucination=0.0, gold=_gold(1.0, 0.0)),
    ]
    cm = build_agreement_report(records).hallucination_confusion
    assert (
        cm.true_positive,
        cm.false_positive,
        cm.false_negative,
        cm.true_negative,
    ) == (
        1,
        1,
        1,
        1,
    )


def test_empty_gold_does_not_crash() -> None:
    records = [
        _rec("a", proxy_grounding=1.0, proxy_hallucination=0.0, gold=None),
    ]
    report = build_agreement_report(records)
    assert report.n_annotated == 0
    assert report.rows == []
    assert report.hallucination.pearson is None
    assert report.hallucination.mean_abs_error == pytest.approx(0.0)
    cm = report.hallucination_confusion
    assert (
        cm.true_positive,
        cm.false_positive,
        cm.false_negative,
        cm.true_negative,
    ) == (
        0,
        0,
        0,
        0,
    )


# --- serializzazione della tabella-accordo -----------------------------------


def _sample_report() -> AgreementReport:
    records = [
        _rec(
            "run-a", proxy_grounding=1.0, proxy_hallucination=0.0, gold=_gold(0.9, 0.1)
        ),
        _rec(
            "run-b", proxy_grounding=0.5, proxy_hallucination=0.5, gold=_gold(0.4, 0.6)
        ),
    ]
    return build_agreement_report(records)


def test_to_markdown_has_table_and_summary() -> None:
    md = to_markdown(_sample_report())
    assert "| run_id |" in md
    assert "run-a" in md and "run-b" in md
    assert "pearson" in md.lower()
    assert "confusion" in md.lower() or "confusione" in md.lower()


def test_to_csv_has_header_and_rows() -> None:
    csv = to_csv(_sample_report())
    lines = csv.strip().splitlines()
    assert lines[0].startswith("run_id,")
    assert any("run-a" in line for line in lines[1:])


def test_write_agreement_report_writes_files(tmp_path: Path) -> None:
    write_record(
        tmp_path,
        _rec(
            "run-a", proxy_grounding=1.0, proxy_hallucination=0.0, gold=_gold(0.9, 0.1)
        ),
    )
    write_record(
        tmp_path,
        _rec(
            "run-b", proxy_grounding=0.5, proxy_hallucination=0.5, gold=_gold(0.4, 0.6)
        ),
    )
    csv_path, md_path = write_agreement_report(tmp_path)
    assert csv_path.exists() and md_path.exists()
    assert "run-a" in csv_path.read_text(encoding="utf-8")
    assert "pearson" in md_path.read_text(encoding="utf-8").lower()


# --- wiring CLI: subcomando `gold` -------------------------------------------


def test_parser_gold_defaults_results() -> None:
    ns = build_parser().parse_args(["gold"])
    assert ns.command == "gold"
    assert ns.results == "results"


def test_main_gold_dispatch_writes_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Guida main() come farebbe la CLI reale: `... gold --results <dir>`.
    write_record(
        tmp_path,
        _rec(
            "run-a", proxy_grounding=1.0, proxy_hallucination=0.0, gold=_gold(0.9, 0.1)
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["crime_risk_analyzer.eval", "gold", "--results", str(tmp_path)],
    )
    assert eval_main.main() == 0
    csv_path = tmp_path / "gold" / "agreement.csv"
    md_path = tmp_path / "gold" / "agreement.md"
    assert csv_path.exists() and md_path.exists()
    assert "run-a" in csv_path.read_text(encoding="utf-8")
