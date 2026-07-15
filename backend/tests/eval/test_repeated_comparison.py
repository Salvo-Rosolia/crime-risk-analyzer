"""Report esteso confronto modelli con K ripetizioni (#157), offline."""

from __future__ import annotations

import json
from pathlib import Path

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
) -> RunRecord:
    return RunRecord(
        run_id=make_run_id(experiment, citta, zona, "analyze", "groq", rep),
        experiment=experiment,
        citta=citta,
        zona=zona,
        mode="analyze",
        model_id=model_id,
        status=RunStatus.OK,
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
