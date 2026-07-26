"""Test del confronto a due bracci (#32).

Primitiva GENERICA (bracci A vs B qualsiasi): unisce i RunRecord di due
esperimenti per ``(citta, zona)`` e calcola il delta delle 4 metriche. La
riusa #33 (claude vs groq). I test sono offline: costruiscono i record a mano,
nessuna run live LLM/Overpass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from crime_risk_analyzer.eval.compare import (
    VACUOUS_CAVEAT_HEAD,
    Comparison,
    FailedZone,
    MetricValues,
    ZoneComparison,
    compare_experiments,
    compare_records,
    is_vacuous_arm,
    to_csv,
    to_markdown,
    write_comparison,
)
from crime_risk_analyzer.eval.harness import write_record
from crime_risk_analyzer.eval.schema import (
    Metrics,
    Provenance,
    RunRecord,
    RunStatus,
)


def _rec(
    experiment: str,
    citta: str,
    zona: str,
    *,
    grounding: float,
    hallucination: float,
    latency_ms: int,
    cost_usd: float,
    mode: str = "analyze",
    model: str = "claude",
    status: RunStatus = RunStatus.OK,
    snapshot_id: str | None = None,
    narrativa: str = "x",
) -> RunRecord:
    """RunRecord minimale con metriche controllate per i test di confronto."""
    return RunRecord(
        run_id=f"{experiment}__{citta}__{zona}__{mode}__{model}".lower(),
        experiment=experiment,
        citta=citta,
        zona=zona,
        mode="analyze" if mode == "analyze" else "baseline",
        model_id=model,
        status=status,
        metrics=Metrics(
            grounding=grounding,
            hallucination=hallucination,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        ),
        narrativa=narrativa,
        n_poi=1,
        provenance=Provenance(
            code_commit="c",
            ontology_hash="o",
            snapshot_id=snapshot_id or f"{citta}__{zona}".lower(),
            model_id=model,
            prompt_hash="p",
            temperature=0.0,
            seed=0,
            experiment=experiment,
        ),
    )


def _arm_a_with_error() -> list[RunRecord]:
    """Braccio A con una zona (Napoli) in ERROR: metriche azzerate come l'harness."""
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
    """Braccio B con Napoli OK (metriche reali): stesso set di zone di A."""
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
    """Unisce per (citta, zona) e calcola delta = A - B su ogni metrica."""
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
    """L'ordine delle zone è deterministico (sorted per (citta, zona))."""
    cmp = compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base")
    assert [(z.citta, z.zona) for z in cmp.zones] == [
        ("Milano", "Duomo"),
        ("Roma", "Colosseo"),
    ]


def test_compare_records_aggregate_means_and_mean_delta() -> None:
    """L'aggregato è la media per braccio; mean_delta == mean_a - mean_b."""
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
    """Set di (citta, zona) diversi tra i bracci → errore (iso-input violato)."""
    arm_b = [_arm_b()[0]]  # manca (Milano, Duomo)
    with pytest.raises(ValueError, match="(?i)zone|citta|zona|iso"):
        compare_records(_arm_a(), arm_b, label_a="full", label_b="base")


def test_compare_records_raises_on_duplicate_zone_within_arm() -> None:
    """Due record per la stessa (citta, zona) nello stesso braccio → errore."""
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
    """Nessuna zona in comune (bracci vuoti) → errore, niente media su 0."""
    with pytest.raises(ValueError):
        compare_records([], [], label_a="a", label_b="b")


def test_zone_comparison_delta_type() -> None:
    """Il delta è un MetricValues (può essere negativo, fuori da [0,1])."""
    cmp = compare_records(_arm_b(), _arm_a(), label_a="base", label_b="full")
    z = cmp.zones[0]
    assert isinstance(z, ZoneComparison)
    assert isinstance(z.delta, MetricValues)
    assert z.delta.grounding < 0  # base - full è negativo


# --- M1: i record in ERROR non inquinano delta/medie ----------------------


def test_error_zone_excluded_from_zones_and_means() -> None:
    """Una zona in ERROR (metriche azzerate) è esclusa da zone comparate e medie."""
    cmp = compare_records(
        _arm_a_with_error(), _arm_b_napoli_ok(), label_a="full", label_b="base"
    )
    # Napoli (ERROR in A) NON compare tra le zone confrontate.
    assert [(z.citta, z.zona) for z in cmp.zones] == [
        ("Milano", "Duomo"),
        ("Roma", "Colosseo"),
    ]
    # Le medie sono identiche al caso a 2 zone tutte-OK: lo zero di Napoli non
    # entra nell'aggregato (niente media silenziosa su un record azzerato).
    baseline = compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base")
    assert cmp.mean_a.grounding == pytest.approx(baseline.mean_a.grounding)
    assert cmp.mean_b.grounding == pytest.approx(baseline.mean_b.grounding)
    assert cmp.mean_a.latency_ms == pytest.approx(baseline.mean_a.latency_ms)
    assert cmp.mean_delta.grounding == pytest.approx(baseline.mean_delta.grounding)


def test_error_zone_reported_with_both_statuses() -> None:
    """La zona fallita è riportata con lo status di ENTRAMBI i bracci."""
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
    """FALLBACK ha narrativa vuota → metriche non di qualità: la zona è esclusa."""
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
    # Napoli (FALLBACK in A) NON è tra le zone confrontate.
    assert [(z.citta, z.zona) for z in cmp.zones] == [
        ("Milano", "Duomo"),
        ("Roma", "Colosseo"),
    ]
    assert [(f.citta, f.zona) for f in cmp.failed] == [("Napoli", "Garibaldi")]


def test_fallback_zone_reported_with_status() -> None:
    """L'esclusione FALLBACK è tracciata (non silenziosa): status nel FailedZone."""
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
    """Un braccio interamente in FALLBACK → nessuna zona valida → errore chiaro."""
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


def test_raises_when_all_zones_error() -> None:
    """Se non resta alcuna zona valida → errore esplicito (niente media su nulla)."""
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


# --- m1: iso-input a livello di record (snapshot_id) -----------------------


def test_raises_on_snapshot_id_mismatch() -> None:
    """Stessa (citta, zona) ma snapshot_id diverso tra i bracci → errore iso-input."""
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


# --- serializzazione: CSV / Markdown --------------------------------------


def test_to_csv_labeled_headers_and_mean_row() -> None:
    """Header parametrizzati sulle label + riga aggregata (media)."""
    csv = to_csv(compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base"))
    lines = csv.strip().splitlines()
    header = lines[0]
    assert "citta" in header and "zona" in header
    assert "grounding_full" in header
    assert "grounding_base" in header
    assert "grounding_delta" in header
    assert "latency_ms_delta" in header
    assert "cost_usd_delta" in header
    assert "MEDIA" in csv  # riga aggregata


def test_to_csv_delta_has_sign() -> None:
    """Il delta è formattato col segno esplicito (+/-)."""
    csv = to_csv(compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base"))
    assert "+0.400" in csv  # delta grounding
    assert "+1900" in csv  # delta latency (Roma)


def test_to_markdown_table_with_headers_and_mean() -> None:
    md = to_markdown(
        compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base")
    )
    assert "|" in md
    assert "grounding_delta" in md
    assert "MEDIA" in md
    # separatore di tabella markdown
    assert "---" in md


def test_to_markdown_reports_failed_zones_section() -> None:
    """La sezione zone escluse compare nel markdown, con status di entrambi i bracci."""
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
    """Opzione (a): con zone in ERROR il CSV resta RETTANGOLARE e non le include.

    Le zone fallite NON entrano nel CSV numerico (niente riga ragged, pandas le
    carica pulite) ma NON spariscono: restano in ``Comparison.failed`` (e nel
    report Markdown).
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
        assert len(row) == header_width  # nessuna riga di larghezza diversa
    # header + zone valide (Milano, Roma) + MEDIA; Napoli (ERROR) escluso.
    assert len(rows) == len(cmp.zones) + 2
    assert "Napoli" not in csv_text
    assert "status_full" not in csv_text
    # Non perso: accessibile programmaticamente.
    assert [(f.citta, f.zona) for f in cmp.failed] == [("Napoli", "Garibaldi")]


def test_no_failed_section_in_markdown_when_all_ok() -> None:
    """Senza fallimenti non c'è sezione zone escluse nel report Markdown."""
    cmp = compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base")
    assert "escluse" not in to_markdown(cmp).lower()


def test_main_table_rows_match_header_width() -> None:
    """m2: header e righe dati derivano dalla stessa fonte → stessa larghezza."""
    import csv as _csv
    import io as _io

    cmp = compare_records(_arm_a(), _arm_b(), label_a="full", label_b="base")
    rows = list(_csv.reader(_io.StringIO(to_csv(cmp))))
    header_width = len(rows[0])
    # header + una riga per zona + riga MEDIA, tutte della stessa larghezza.
    assert len(rows) == len(cmp.zones) + 2
    for row in rows:
        assert len(row) == header_width


# --- scrittura su disco ----------------------------------------------------


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
    """Regressione stile #103 per il file NUOVO: CSV scritto con newline="".

    ``csv.writer`` emette già ``\\r\\n``; senza ``newline=""`` il text-mode di
    ``write_text`` su Windows ritradurrebbe ``\\n`` in ``\\r\\n`` (righe spurie).
    Guard deterministico e cross-platform: spia il KWARG passato a write_text.
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
    """Da record su disco (due esperimenti) a tabelle: load → join → write."""
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
    assert "+0.400" in text  # delta grounding Roma verificato end-to-end


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


def test_main_compare_dispatch_writes_tables(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """DoD #32: le tabelle di ablation sono rigenerabili con UN comando CLI.

    Guida ``eval.__main__.main`` con argv del sottocomando ``compare``: dai
    record su disco produce i file CSV/MD del confronto.
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

    # due bracci minimi, una zona OK ciascuno, stesso snapshot_id
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


# --- Braccio strutturalmente vacuo: assi di qualita' non applicabili (#231) ---
#
# Osservato sulla prima run reale: il braccio `baseline` (nessun LLM) non produce
# narrativa, cade nel ramo VACUO di metrics.py (grounding 1.0 / hallucination 0.0)
# e cosi' "vince" gli assi di qualita' per assenza di testo da giudicare. La
# regola vacua e' corretta per il FALLBACK; qui va marcata come non interpretabile.


def _analyze_rec(citta: str, zona: str, *, narrativa: str = "prosa reale") -> RunRecord:
    return _rec(
        "analyze-exp",
        citta,
        zona,
        grounding=0.700,
        hallucination=0.300,
        latency_ms=3000,
        cost_usd=0.005,
        narrativa=narrativa,
    )


def _silent_rec(citta: str, zona: str, *, narrativa: str = "") -> RunRecord:
    """Record del braccio senza LLM: status OK, nessuna narrativa (by design)."""
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


def test_compare_records_flags_arm_that_never_produces_narrativa() -> None:
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_silent_rec("Roma", "Colosseo")],
        label_a="analyze",
        label_b="baseline",
    )
    assert comparison.vacuous_arms == ["baseline"]


def test_compare_records_does_not_flag_arm_with_narrativa_on_some_zones() -> None:
    """Un braccio muto su UNA zona ma parlante su un'altra NON e' vacuo."""
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


def test_compare_records_flags_arm_whose_narrativa_is_only_whitespace() -> None:
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
    # Il caveat deve precedere la nota metodologica generica: si legge prima.
    assert md.index(VACUOUS_CAVEAT_HEAD) < md.index("Nota metodologica")


def test_markdown_has_no_quality_caveat_when_both_arms_generate() -> None:
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_analyze_rec("Roma", "Colosseo", narrativa="anche qui prosa")],
        label_a="claude",
        label_b="groq",
    )
    assert VACUOUS_CAVEAT_HEAD not in to_markdown(comparison)


# --- Vacuita' per ZONA, non solo per braccio (#231, review C2) --------------
#
# `status=OK` con narrativa vuota e' raggiungibile in produzione: il client Groq
# ritorna `content or ""` senza sollevare (llm/client.py), quindi l'orchestrator
# risponde fallback=False e l'harness registra OK. Una singola zona muta prende
# hallucination 0.000 vacuo e puo' spostare la media che decide il verdetto.


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
    # Il braccio non e' vacuo (parla su Milano), ma Roma resta non interpretabile.
    assert comparison.vacuous_arms == []
    assert [(z.citta, z.zona, z.arms) for z in comparison.vacuous_zones] == [
        ("Roma", "Colosseo", ["baseline"])
    ]


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
    """L'avviso deve precedere la tabella: chi legge non deve incontrare prima
    un delta di qualità che l'avviso poi smentisce (review C1)."""
    comparison = compare_records(
        [_analyze_rec("Roma", "Colosseo")],
        [_silent_rec("Roma", "Colosseo")],
        label_a="analyze",
        label_b="baseline",
    )
    md = to_markdown(comparison)
    assert md.index(VACUOUS_CAVEAT_HEAD) < md.index("| citta | zona |")


def test_is_vacuous_arm_is_false_for_an_arm_without_records() -> None:
    """Un braccio vuoto non è muto: non è un braccio (regola documentata)."""
    assert is_vacuous_arm([]) is False


def test_compare_experiments_writes_the_vacuity_warning_to_disk(tmp_path: Path) -> None:
    """AC3: il percorso non ripetuto (quello che il CLI `compare` chiama) deve
    portare l'avviso nel .md e `vacuous_arms` nel .json scritti su disco."""
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
