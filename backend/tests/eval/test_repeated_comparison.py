"""Report esteso confronto modelli con K ripetizioni (#157), offline."""

from __future__ import annotations

import json
from pathlib import Path

from pytest import MonkeyPatch

from crime_risk_analyzer.eval.compare import compare_records
from crime_risk_analyzer.eval.harness import make_run_id, write_record
from crime_risk_analyzer.eval.repeat import fold_arm
from crime_risk_analyzer.eval.repeated_comparison import (
    build_repeated_report,
    variance_markdown,
    winner_markdown,
)
from crime_risk_analyzer.eval.schema import (
    Metrics,
    Provenance,
    RunRecord,
    RunStatus,
)
from crime_risk_analyzer.eval.winner import decide_winner


def _rec(
    experiment: str,
    citta: str,
    zona: str,
    *,
    rep: int,
    model_id: str,
    grounding: float,
    hallucination: float,
    latency_ms: int,
    cost_usd: float,
    status: RunStatus = RunStatus.OK,
) -> RunRecord:
    return RunRecord(
        run_id=make_run_id(experiment, citta, zona, "analyze", "groq", rep),
        experiment=experiment,
        citta=citta,
        zona=zona,
        mode="analyze",
        model_id=model_id,
        status=status,
        metrics=Metrics(
            grounding=grounding,
            hallucination=hallucination,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        ),
        narrativa="x",
        n_poi=1,
        provenance=Provenance(
            code_commit="c",
            ontology_hash="o",
            snapshot_id=f"{citta}__{zona}".lower(),
            model_id=model_id,
            prompt_hash="p",
            temperature=0.0,
            seed=rep,
            experiment=experiment,
        ),
    )


def _arm(
    experiment: str, model_id: str, base: tuple[float, float, int, float]
) -> list[RunRecord]:
    """3 ripetizioni su una zona con leggera variazione → std > 0."""
    g, h, lat, cost = base
    return [
        _rec(
            experiment,
            "Roma",
            "Colosseo",
            rep=r,
            model_id=model_id,
            grounding=g + 0.01 * r,
            hallucination=h - 0.01 * r,
            latency_ms=lat + 10 * r,
            cost_usd=cost,
        )
        for r in range(3)
    ]


def _write_arm(results_dir: Path, records: list[RunRecord]) -> None:
    for rec in records:
        write_record(results_dir, rec)


def test_winner_markdown_reports_winner_and_deciding_axis() -> None:
    claude = fold_arm(
        _arm("claude-exp", "claude-sonnet-4-6", (0.90, 0.10, 3000, 0.012))
    )
    groq = fold_arm(
        _arm("groq-exp", "llama-3.3-70b-versatile", (0.70, 0.20, 1000, 0.0006))
    )
    cmp = compare_records(
        claude.mean_records, groq.mean_records, label_a="claude", label_b="groq"
    )
    w = decide_winner(cmp.mean_a, cmp.mean_b, label_a="claude", label_b="groq")
    md = winner_markdown(w, k=3)
    assert "claude" in md  # hallucination piu' bassa → claude vince
    assert "hallucination" in md
    assert "K=3" in md or "K = 3" in md
    # riga del verdetto esatta (non tautologico: "claude" e' anche negli header
    # tabella) — un bug che interpola label_b al posto di winner.winner fallisce.
    assert "**Vincitore: `claude`**" in md
    assert "**Vincitore: `groq`**" not in md


def test_winner_markdown_declares_tie() -> None:
    same = _arm("a-exp", "m", (0.80, 0.10, 1000, 0.001))
    other = _arm("b-exp", "m", (0.80, 0.10, 1000, 0.001))
    cmp = compare_records(
        fold_arm(same).mean_records,
        fold_arm(other).mean_records,
        label_a="a",
        label_b="b",
    )
    w = decide_winner(cmp.mean_a, cmp.mean_b, label_a="a", label_b="b")
    md = winner_markdown(w, k=3)
    assert "pareggio" in md.lower()


def test_variance_markdown_shows_mean_and_std() -> None:
    claude = fold_arm(
        _arm("claude-exp", "claude-sonnet-4-6", (0.90, 0.10, 3000, 0.012))
    )
    groq = fold_arm(
        _arm("groq-exp", "llama-3.3-70b-versatile", (0.70, 0.20, 1000, 0.0006))
    )
    cmp = compare_records(
        claude.mean_records, groq.mean_records, label_a="claude", label_b="groq"
    )
    md = variance_markdown(cmp, claude, groq, k=3)
    assert "±" in md
    assert "grounding" in md
    assert "Roma" in md
    # onesta' del report (G): n_reps/n_totali per braccio, non solo media±std.
    # _arm produce 3 ripetizioni valide su 3 per entrambi i bracci → 3/3.
    assert "n_claude" in md
    assert "n_groq" in md
    assert "3/3" in md


def test_variance_markdown_shows_reps_count_when_dropped() -> None:
    """Zona con 1 rep ERROR su 3 (braccio A) → 2/3, non std=0 senza contesto (G)."""
    claude_recs = [
        _rec(
            "claude-exp",
            "Roma",
            "Colosseo",
            rep=0,
            model_id="claude-sonnet-4-6",
            grounding=0.90,
            hallucination=0.10,
            latency_ms=3000,
            cost_usd=0.012,
        ),
        _rec(
            "claude-exp",
            "Roma",
            "Colosseo",
            rep=1,
            model_id="claude-sonnet-4-6",
            grounding=0.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.ERROR,
        ),
        _rec(
            "claude-exp",
            "Roma",
            "Colosseo",
            rep=2,
            model_id="claude-sonnet-4-6",
            grounding=0.92,
            hallucination=0.08,
            latency_ms=3020,
            cost_usd=0.012,
        ),
    ]
    groq_recs = _arm("groq-exp", "llama-3.3-70b-versatile", (0.70, 0.20, 1000, 0.0006))
    claude = fold_arm(claude_recs)
    groq = fold_arm(groq_recs)
    assert claude.variances[0].n_reps == 2
    assert claude.variances[0].n_dropped == 1
    cmp = compare_records(
        claude.mean_records, groq.mean_records, label_a="claude", label_b="groq"
    )
    md = variance_markdown(cmp, claude, groq, k=3)
    assert "2/3" in md  # braccio claude: 2 valide su 3
    assert "3/3" in md  # braccio groq: 3 valide su 3, nessuno scarto


def test_variance_markdown_cell_values_match_getter_mapping() -> None:
    """Cella specifica con valore atteso: cattura uno scambio in _GETTERS/_STD_GETTERS.

    Le 4 metriche hanno media E deviazione std TUTTE DISTINTE tra loro: uno
    scambio di colonna/metrica in _GETTERS (medie) o _STD_GETTERS (std) — es.
    hallucination che legge grounding — cambia il valore stampato in almeno
    una cella nota. cost_usd VARIA tra ripetizioni (a differenza di _arm, dove
    e' costante): la sua colonna std deve risultare diversa da 0, verificabile.
    """
    recs = [
        _rec(
            "claude-exp",
            "Roma",
            "Colosseo",
            rep=r,
            model_id="claude-sonnet-4-6",
            grounding=g,
            hallucination=h,
            latency_ms=lat,
            cost_usd=cost,
        )
        for r, (g, h, lat, cost) in enumerate(
            [
                (0.88, 0.05, 2990, 0.010),
                (0.90, 0.10, 3000, 0.011),
                (0.92, 0.15, 3010, 0.012),
            ]
        )
    ]
    groq_recs = _arm("groq-exp", "llama-3.3-70b-versatile", (0.70, 0.20, 1000, 0.0006))
    claude = fold_arm(recs)
    groq = fold_arm(groq_recs)
    cmp = compare_records(
        claude.mean_records, groq.mean_records, label_a="claude", label_b="groq"
    )
    md = variance_markdown(cmp, claude, groq, k=3)
    # media/std attese (calcolate con statistics.pstdev), tutte distinte tra
    # loro: grounding=0.900±0.016, hallucination=0.100±0.041, latency=3000±8,
    # cost=0.011000±0.000816.
    assert "0.900 ± 0.016" in md
    assert "0.100 ± 0.041" in md
    assert "3000 ± 8" in md
    assert "0.011000 ± 0.000816" in md
    assert claude.variances[0].std.cost_usd > 0.0


def test_build_repeated_report_writes_md_and_json(tmp_path: Path) -> None:
    _write_arm(
        tmp_path, _arm("claude-exp", "claude-sonnet-4-6", (0.90, 0.10, 3000, 0.012))
    )
    _write_arm(
        tmp_path,
        _arm("groq-exp", "llama-3.3-70b-versatile", (0.70, 0.20, 1000, 0.0006)),
    )
    md_path, json_path = build_repeated_report(
        tmp_path, "claude-exp", "groq-exp", label_a="claude", label_b="groq", stem="cmp"
    )
    assert md_path.exists() and json_path.exists()
    md = md_path.read_text(encoding="utf-8")
    # tabelle #33 presenti + sezioni nuove
    assert "grounding_claude" in md
    assert "±" in md
    assert "claude" in md.lower()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["winner"]["winner"] == "claude"
    assert data["winner"]["deciding_axis"] == "hallucination"
    assert data["variance"]["k"] == 3
    assert len(data["variance"]["arm_a"]) == 1  # una zona
    assert "comparison" in data


def test_main_compare_repeated_dispatch_writes_report(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Dispatch main() per compare-repeated (gemello di compare, #157, M11).

    Guida ``eval.__main__.main`` con argv del sottocomando ``compare-repeated``:
    dai run su disco (K ripetizioni per braccio) produce il report MD/JSON, con
    ``winner`` presente nel JSON.
    """
    import sys

    import crime_risk_analyzer.eval.__main__ as eval_main

    _write_arm(
        tmp_path, _arm("claude-exp", "claude-sonnet-4-6", (0.90, 0.10, 3000, 0.012))
    )
    _write_arm(
        tmp_path,
        _arm("groq-exp", "llama-3.3-70b-versatile", (0.70, 0.20, 1000, 0.0006)),
    )

    argv = [
        "crime_risk_analyzer.eval",
        "compare-repeated",
        "--experiment-a",
        "claude-exp",
        "--experiment-b",
        "groq-exp",
        "--label-a",
        "claude",
        "--label-b",
        "groq",
        "--out",
        "cmp-repeated",
        "--results",
        str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    rc = eval_main.main()
    assert rc == 0

    md_path = tmp_path / "cmp-repeated.md"
    json_path = tmp_path / "cmp-repeated.json"
    assert md_path.exists()
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "winner" in data
    assert data["winner"]["winner"] == "claude"


def test_end_to_end_fold_compare_winner(tmp_path: Path) -> None:
    """run→disk→fold→compare→winner: Claude (piu' accurato) vince su hallucination."""
    _write_arm(
        tmp_path, _arm("claude-exp", "claude-sonnet-4-6", (0.90, 0.10, 3000, 0.012))
    )
    _write_arm(
        tmp_path,
        _arm("groq-exp", "llama-3.3-70b-versatile", (0.70, 0.20, 1000, 0.0006)),
    )
    md_path, json_path = build_repeated_report(
        tmp_path, "claude-exp", "groq-exp", label_a="claude", label_b="groq"
    )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["winner"]["winner"] == "claude"
    # varianza non nulla (le 3 ripetizioni variano)
    assert data["variance"]["arm_a"][0]["std"]["grounding"] > 0.0
    assert "Vincitore" in md_path.read_text(encoding="utf-8")


def test_build_repeated_report_default_stem_filename(tmp_path: Path) -> None:
    """Senza --out/stem, il nome file di default e' <a>_vs_<b>_repeated.{md,json}."""
    _write_arm(
        tmp_path, _arm("claude-exp", "claude-sonnet-4-6", (0.90, 0.10, 3000, 0.012))
    )
    _write_arm(
        tmp_path,
        _arm("groq-exp", "llama-3.3-70b-versatile", (0.70, 0.20, 1000, 0.0006)),
    )
    md_path, json_path = build_repeated_report(tmp_path, "claude-exp", "groq-exp")
    assert md_path == tmp_path / "claude-exp_vs_groq-exp_repeated.md"
    assert json_path == tmp_path / "claude-exp_vs_groq-exp_repeated.json"
    assert md_path.exists() and json_path.exists()


def test_build_repeated_report_all_error_zone_excluded_from_variance_table(
    tmp_path: Path,
) -> None:
    """Zona tutta-ERROR in un braccio: niente crash, esclusa dalla tabella
    varianza MD ma presente nel JSON con n_reps=0 e tra le zone escluse (#33)."""
    ok_a = _arm("claude-exp", "claude-sonnet-4-6", (0.90, 0.10, 3000, 0.012))
    ok_b = _arm("groq-exp", "llama-3.3-70b-versatile", (0.70, 0.20, 1000, 0.0006))
    all_error_a = [
        _rec(
            "claude-exp",
            "Milano",
            "Duomo",
            rep=r,
            model_id="claude-sonnet-4-6",
            grounding=0.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.ERROR,
        )
        for r in range(2)
    ]
    valid_b = [
        _rec(
            "groq-exp",
            "Milano",
            "Duomo",
            rep=r,
            model_id="llama-3.3-70b-versatile",
            grounding=0.5,
            hallucination=0.3,
            latency_ms=1200,
            cost_usd=0.0005,
        )
        for r in range(2)
    ]
    _write_arm(tmp_path, ok_a + all_error_a)
    _write_arm(tmp_path, ok_b + valid_b)

    md_path, json_path = build_repeated_report(
        tmp_path,
        "claude-exp",
        "groq-exp",
        label_a="claude",
        label_b="groq",
        stem="cmp-all-error",
    )
    md = md_path.read_text(encoding="utf-8")
    data = json.loads(json_path.read_text(encoding="utf-8"))

    variance_section = md.split("### Varianza")[1].split("### Vincitore")[0]
    assert "Milano" not in variance_section

    milano_a = next(v for v in data["variance"]["arm_a"] if v["zona"] == "Duomo")
    assert milano_a["n_reps"] == 0
    assert milano_a["n_dropped"] == 2
    assert any(f["zona"] == "Duomo" for f in data["comparison"]["failed"])


def test_build_repeated_report_deep_tie_break_on_latency(tmp_path: Path) -> None:
    """hallucination/grounding pari a precisione di stampa → decide su latency_ms."""
    tied_a = [
        _rec(
            "claude-exp",
            "Roma",
            "Colosseo",
            rep=r,
            model_id="claude-sonnet-4-6",
            grounding=0.800,
            hallucination=0.100,
            latency_ms=1000,
            cost_usd=0.001,
        )
        for r in range(3)
    ]
    tied_b = [
        _rec(
            "groq-exp",
            "Roma",
            "Colosseo",
            rep=r,
            model_id="llama-3.3-70b-versatile",
            grounding=0.800,
            hallucination=0.100,
            latency_ms=1005,
            cost_usd=0.001,
        )
        for r in range(3)
    ]
    _write_arm(tmp_path, tied_a)
    _write_arm(tmp_path, tied_b)

    _, json_path = build_repeated_report(
        tmp_path, "claude-exp", "groq-exp", label_a="claude", label_b="groq"
    )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["winner"]["deciding_axis"] in {"latency_ms", "cost_usd"}
    assert data["winner"]["winner"] == "claude"  # 1000ms < 1005ms
