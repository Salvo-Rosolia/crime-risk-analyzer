"""Extended model-comparison report with K repetitions (#157), offline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from crime_risk_analyzer.eval.compare import (
    ISOLATED_VARIABLE_HEAD,
    ISTAT_NO_WINNER_REASON,
    ISTAT_VERSIONS_DIFFER_HEAD,
    VACUOUS_CAVEAT_HEAD,
    NoUsableOutputError,
    compare_records,
)
from crime_risk_analyzer.eval.harness import make_run_id, write_record
from crime_risk_analyzer.eval.repeat import fold_arm
from crime_risk_analyzer.eval.repeated_comparison import (
    build_repeated_report,
    variance_markdown,
    winner_markdown,
)
from crime_risk_analyzer.eval.schema import (
    IstatMetrics,
    Metrics,
    Mode,
    Provenance,
    RunRecord,
    RunStatus,
)
from crime_risk_analyzer.eval.winner import decide_winner
from crime_risk_analyzer.llm.client import GROQ_MODEL


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
    narrativa: str = "x",
    mode: Mode = "analyze",
    poi_nel_prompt: list[str] | None = None,
) -> RunRecord:
    return RunRecord(
        run_id=make_run_id(experiment, citta, zona, mode, "groq", rep),
        experiment=experiment,
        citta=citta,
        zona=zona,
        mode=mode,
        model_id=model_id,
        status=status,
        metrics=Metrics(
            grounding=grounding,
            hallucination=hallucination,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        ),
        narrativa=narrativa,
        n_poi=1,
        # #349: without ``poi_nel_prompt`` the C3 pair is not declared isolated.
        poi_nel_prompt=poi_nel_prompt if poi_nel_prompt is not None else ["1"],
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
    experiment: str,
    model_id: str,
    base: tuple[float, float, int, float],
    *,
    mode: Mode = "analyze",
) -> list[RunRecord]:
    """3 repetitions on a zone with slight variation -> std > 0."""
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
            mode=mode,
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
    groq = fold_arm(_arm("groq-exp", GROQ_MODEL, (0.70, 0.20, 1000, 0.0006)))
    cmp = compare_records(
        claude.mean_records, groq.mean_records, label_a="claude", label_b="groq"
    )
    w = decide_winner(cmp.mean_a, cmp.mean_b, label_a="claude", label_b="groq")
    md = winner_markdown(w, k=3, folded_a=claude, folded_b=groq)
    assert "hallucination" in md
    assert "K=3" in md
    # E: softened label, exploratory -- NOT the strong word "Vincitore".
    assert "Vincitore" not in md
    assert "Esito del criterio proxy" in md
    # verdict on the right model, not tautological (claude is also in the headers).
    assert "`claude` ha scorato meglio" in md
    assert "`groq` ha scorato meglio" not in md
    # E: the scope caveat precedes the verdict (lower index in the text).
    assert md.index("proxy testuale") < md.index("ha scorato meglio")
    # F: sampling basis next to the verdict (3 valid reps on both arms).
    assert "n_reps validi per zona" in md
    assert "`claude`: 3-3" in md


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
    assert "Nessun modello prevale sul proxy" in md
    assert "Vincitore" not in md


def test_variance_markdown_shows_mean_and_std() -> None:
    claude = fold_arm(
        _arm("claude-exp", "claude-sonnet-4-6", (0.90, 0.10, 3000, 0.012))
    )
    groq = fold_arm(_arm("groq-exp", GROQ_MODEL, (0.70, 0.20, 1000, 0.0006)))
    cmp = compare_records(
        claude.mean_records, groq.mean_records, label_a="claude", label_b="groq"
    )
    md = variance_markdown(cmp, claude, groq, k=3)
    assert "±" in md
    assert "grounding" in md
    assert "Roma" in md
    # honesty of the report (G): n_reps/n_totals per arm, not just mean±std.
    # _arm produces 3 valid repetitions out of 3 for both arms -> 3/3.
    assert "n_claude" in md
    assert "n_groq" in md
    assert "3/3" in md


def test_variance_markdown_shows_reps_count_when_dropped() -> None:
    """Zone with 1 ERROR rep out of 3 (arm A) -> 2/3, not std=0 without context (G)."""
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
    groq_recs = _arm("groq-exp", GROQ_MODEL, (0.70, 0.20, 1000, 0.0006))
    claude = fold_arm(claude_recs)
    groq = fold_arm(groq_recs)
    assert claude.variances[0].n_reps == 2
    assert claude.variances[0].n_dropped == 1
    cmp = compare_records(
        claude.mean_records, groq.mean_records, label_a="claude", label_b="groq"
    )
    md = variance_markdown(cmp, claude, groq, k=3)
    assert "2/3" in md  # claude arm: 2 valid out of 3
    assert "3/3" in md  # groq arm: 3 valid out of 3, none discarded


def test_variance_markdown_shows_nd_when_only_one_valid_repetition() -> None:
    """With only 1 valid repetition out of 3, the std is not defined: n/d, not ±
    0.000."""
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
            grounding=0.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.FALLBACK,
        ),
    ]
    groq_recs = _arm("groq-exp", GROQ_MODEL, (0.70, 0.20, 1000, 0.0006))
    claude = fold_arm(claude_recs)
    groq = fold_arm(groq_recs)
    assert claude.variances[0].n_reps == 1
    cmp = compare_records(
        claude.mean_records, groq.mean_records, label_a="claude", label_b="groq"
    )
    md = variance_markdown(cmp, claude, groq, k=3)
    data_rows = [
        line for line in md.splitlines() if line.startswith("| ") and "---" not in line
    ]
    first_zone_row = data_rows[1]  # row 0 is the header of the markdown table
    assert "n/d" in first_zone_row
    # specific cell of the claude arm (n_reps=1): no false "0.900 ± 0.000".
    cells = [c.strip() for c in first_zone_row.strip().strip("|").split("|")]
    # column order: citta, zona, then for each metric (grounding, hallucination,
    # latency_ms, cost_usd) the claude/groq pair -> indices 2,4,6,8 = claude arm.
    assert cells[2] == "n/d"  # grounding_claude
    assert cells[4] == "n/d"  # hallucination_claude
    assert cells[6] == "n/d"  # latency_ms_claude
    assert cells[8] == "n/d"  # cost_usd_claude
    # the groq arm (n_reps=3) stays mean ± std, not "n/d".
    assert cells[3] != "n/d"
    assert "±" in cells[3]


def test_variance_markdown_cell_values_match_getter_mapping() -> None:
    """Specific cell with expected value: catches a swap in _GETTERS/_STD_GETTERS.

    The 4 metrics have mean AND std deviation ALL DISTINCT from each other: a
    column/metric swap in _GETTERS (means) or _STD_GETTERS (std) -- e.g.
    hallucination reading grounding -- changes the printed value in at least
    one known cell. cost_usd VARIES across repetitions (unlike _arm, where
    it is constant): its std column must come out different from 0, verifiable.
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
    groq_recs = _arm("groq-exp", GROQ_MODEL, (0.70, 0.20, 1000, 0.0006))
    claude = fold_arm(recs)
    groq = fold_arm(groq_recs)
    cmp = compare_records(
        claude.mean_records, groq.mean_records, label_a="claude", label_b="groq"
    )
    md = variance_markdown(cmp, claude, groq, k=3)
    # expected mean/std (computed with statistics.pstdev), all distinct from
    # each other: grounding=0.900±0.016, hallucination=0.100±0.041, latency=3000±8,
    # cost=0.011000±0.000816.
    assert "0.900 ± 0.016" in md
    assert "0.100 ± 0.041" in md
    assert "3000 ± 8" in md
    assert "0.011000 ± 0.000816" in md
    assert claude.variances[0].std.cost_usd > 0.0


def test_variance_markdown_shows_fallback_count() -> None:
    """Zone with 1 OK + 2 FALLBACK (arm A) -> n_fallback column = 2 (#165.3)."""
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
            grounding=1.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.FALLBACK,
        ),
        _rec(
            "claude-exp",
            "Roma",
            "Colosseo",
            rep=2,
            model_id="claude-sonnet-4-6",
            grounding=1.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.FALLBACK,
        ),
    ]
    groq = _arm("groq-exp", GROQ_MODEL, (0.70, 0.20, 1000, 0.0006))
    fclaude = fold_arm(claude_recs)
    fgroq = fold_arm(groq)
    cmp = compare_records(
        fclaude.mean_records, fgroq.mean_records, label_a="claude", label_b="groq"
    )
    md = variance_markdown(cmp, fclaude, fgroq, k=3)
    assert "n_fallback_claude" in md
    assert "n_fallback_groq" in md
    # the fallback cell of the claude arm is 2; groq 0.
    row = next(line for line in md.splitlines() if line.startswith("| Roma "))
    assert row.rstrip().endswith("| 2 | 0 |")


def test_build_repeated_report_writes_md_and_json(tmp_path: Path) -> None:
    _write_arm(
        tmp_path, _arm("claude-exp", "claude-sonnet-4-6", (0.90, 0.10, 3000, 0.012))
    )
    _write_arm(
        tmp_path,
        _arm("groq-exp", GROQ_MODEL, (0.70, 0.20, 1000, 0.0006)),
    )
    md_path, json_path = build_repeated_report(
        tmp_path, "claude-exp", "groq-exp", label_a="claude", label_b="groq", stem="cmp"
    )
    assert md_path.exists() and json_path.exists()
    md = md_path.read_text(encoding="utf-8")
    # #33 tables present + new sections
    assert "grounding_claude" in md
    assert "±" in md
    assert "claude" in md.lower()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["winner"]["winner"] == "claude"
    assert data["winner"]["deciding_axis"] == "hallucination"
    assert data["variance"]["k"] == 3
    assert len(data["variance"]["arm_a"]) == 1  # one zone
    assert "comparison" in data


def test_repeated_report_of_the_c3_pair_declares_the_variable_and_decides(
    tmp_path: Path,
) -> None:
    """#236: the report that carries the verdict declares what it isolates, and emits
    it.

    It is the defect that the new arm closes: against ``baseline`` the verdict
    was WITHHELD (#231), because a mute arm makes the quality axes
    vacuous. Here both generate, so the lexicographic criterion has
    material to pronounce on -- and the reader finds at the top the manipulated
    variable, not just a delta.
    """
    _write_arm(
        tmp_path,
        _arm("con-onto-exp", GROQ_MODEL, (0.90, 0.10, 3000, 0.0006)),
    )
    _write_arm(
        tmp_path,
        _arm(
            "senza-onto-exp",
            GROQ_MODEL,
            (0.50, 0.50, 2800, 0.0005),
            mode="no_ontology_prompt",
        ),
    )
    md_path, json_path = build_repeated_report(
        tmp_path,
        "con-onto-exp",
        "senza-onto-exp",
        label_a="con-ontologia",
        label_b="senza-ontologia",
        stem="c3",
    )
    md = md_path.read_text(encoding="utf-8")
    assert ISOLATED_VARIABLE_HEAD in md
    assert VACUOUS_CAVEAT_HEAD not in md
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["quality_verdict"]["applicable"] is True
    assert data["winner"] is not None
    assert data["comparison"]["isolated_variable"]


def test_the_c3_verdict_never_falls_back_on_speed_or_cost(tmp_path: Path) -> None:
    """Tied quality on the with/without-ontology pair: no winner.

    The ablated arm receives a structurally shorter prompt, so it is
    faster and cheaper by construction: if the tie-break went down to
    latency or cost, the report would say that removing the ontology "wins" -- a
    verdict on prompt length disguised as a verdict on quality.
    """
    _write_arm(
        tmp_path,
        _arm("con-onto-exp", GROQ_MODEL, (0.80, 0.10, 3000, 0.0009)),
    )
    _write_arm(
        tmp_path,
        _arm(
            "senza-onto-exp",
            GROQ_MODEL,
            (0.80, 0.10, 1000, 0.0002),
            mode="no_ontology_prompt",
        ),
    )
    md_path, json_path = build_repeated_report(
        tmp_path,
        "con-onto-exp",
        "senza-onto-exp",
        label_a="con-ontologia",
        label_b="senza-ontologia",
        stem="c3-pari",
    )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["winner"]["winner"] is None
    assert data["winner"]["deciding_axis"] is None
    assert [c["axis"] for c in data["winner"]["chain"]] == [
        "hallucination",
        "grounding",
    ]
    md = md_path.read_text(encoding="utf-8")
    assert "non decidibile" in md
    assert "ha scorato meglio" not in md


def test_the_model_pair_still_breaks_ties_on_speed(tmp_path: Path) -> None:
    """Non-regression #157: between two MODELS latency and cost stay tie-breaks.

    There the two arms receive the SAME prompt, so a latency difference
    is a property of the model -- a measurable merit, not an artefact of the
    length of the text sent.
    """
    _write_arm(
        tmp_path, _arm("claude-exp", "claude-sonnet-4-6", (0.80, 0.10, 3000, 0.012))
    )
    _write_arm(
        tmp_path,
        _arm("groq-exp", GROQ_MODEL, (0.80, 0.10, 1000, 0.0006)),
    )
    _, json_path = build_repeated_report(
        tmp_path,
        "claude-exp",
        "groq-exp",
        label_a="claude",
        label_b="groq",
        stem="modelli",
    )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["winner"]["deciding_axis"] == "latency_ms"
    assert data["winner"]["winner"] == "groq"


def test_main_compare_repeated_dispatch_writes_report(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Dispatch main() for compare-repeated (twin of compare, #157, M11).

    Drives ``eval.__main__.main`` with the argv of the ``compare-repeated`` subcommand:
    from the runs on disk (K repetitions per arm) it produces the MD/JSON report, with
    ``winner`` present in the JSON.
    """
    import sys

    import crime_risk_analyzer.eval.__main__ as eval_main

    _write_arm(
        tmp_path, _arm("claude-exp", "claude-sonnet-4-6", (0.90, 0.10, 3000, 0.012))
    )
    _write_arm(
        tmp_path,
        _arm("groq-exp", GROQ_MODEL, (0.70, 0.20, 1000, 0.0006)),
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
    """run->disk->fold->compare->winner: Claude (more accurate) wins on
    hallucination."""
    _write_arm(
        tmp_path, _arm("claude-exp", "claude-sonnet-4-6", (0.90, 0.10, 3000, 0.012))
    )
    _write_arm(
        tmp_path,
        _arm("groq-exp", GROQ_MODEL, (0.70, 0.20, 1000, 0.0006)),
    )
    md_path, json_path = build_repeated_report(
        tmp_path, "claude-exp", "groq-exp", label_a="claude", label_b="groq"
    )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["winner"]["winner"] == "claude"
    # non-zero variance (the 3 repetitions vary)
    assert data["variance"]["arm_a"][0]["std"]["grounding"] > 0.0
    assert "Esito del criterio proxy" in md_path.read_text(encoding="utf-8")


def test_build_repeated_report_default_stem_filename(tmp_path: Path) -> None:
    """Without --out/stem, the default file name is <a>_vs_<b>_repeated.{md,json}."""
    _write_arm(
        tmp_path, _arm("claude-exp", "claude-sonnet-4-6", (0.90, 0.10, 3000, 0.012))
    )
    _write_arm(
        tmp_path,
        _arm("groq-exp", GROQ_MODEL, (0.70, 0.20, 1000, 0.0006)),
    )
    md_path, json_path = build_repeated_report(tmp_path, "claude-exp", "groq-exp")
    assert md_path == tmp_path / "claude-exp_vs_groq-exp_repeated.md"
    assert json_path == tmp_path / "claude-exp_vs_groq-exp_repeated.json"
    assert md_path.exists() and json_path.exists()


def test_build_repeated_report_all_error_zone_excluded_from_variance_table(
    tmp_path: Path,
) -> None:
    """All-ERROR zone in an arm: no crash, excluded from the MD variance
    table but present in the JSON with n_reps=0 and among the excluded zones (#33)."""
    ok_a = _arm("claude-exp", "claude-sonnet-4-6", (0.90, 0.10, 3000, 0.012))
    ok_b = _arm("groq-exp", GROQ_MODEL, (0.70, 0.20, 1000, 0.0006))
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
            model_id=GROQ_MODEL,
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

    variance_section = md.split("### Varianza")[1].split(
        "### Esito del criterio proxy"
    )[0]
    assert "Milano" not in variance_section

    milano_a = next(v for v in data["variance"]["arm_a"] if v["zona"] == "Duomo")
    assert milano_a["n_reps"] == 0
    assert milano_a["n_dropped"] == 2
    assert any(f["zona"] == "Duomo" for f in data["comparison"]["failed"])


def test_report_flags_heterogeneous_k(tmp_path: Path) -> None:
    """Arms with different K (3 vs 2 reps on the same zone) -> range + warning."""
    claude = _arm(
        "claude-exp", "claude-sonnet-4-6", (0.90, 0.10, 3000, 0.012)
    )  # 3 reps
    groq = [
        _rec(
            "groq-exp",
            "Roma",
            "Colosseo",
            rep=r,
            model_id=GROQ_MODEL,
            grounding=0.70 + 0.01 * r,
            hallucination=0.20 - 0.01 * r,
            latency_ms=1000 + 10 * r,
            cost_usd=0.0006,
        )
        for r in range(2)  # only 2 repetitions
    ]
    _write_arm(tmp_path, claude)
    _write_arm(tmp_path, groq)
    md_path, _ = build_repeated_report(
        tmp_path, "claude-exp", "groq-exp", label_a="claude", label_b="groq", stem="het"
    )
    md = md_path.read_text(encoding="utf-8")
    assert "K=2..3" in md
    assert "disomogeneo" in md.lower()


def test_variance_markdown_header_shows_k_range() -> None:
    """variance_markdown with k_hi != k -> header with the range."""
    claude = fold_arm(_arm("c", "m", (0.90, 0.10, 3000, 0.012)))
    groq = fold_arm(_arm("g", "m", (0.70, 0.20, 1000, 0.0006)))
    cmp = compare_records(
        claude.mean_records, groq.mean_records, label_a="c", label_b="g"
    )
    md = variance_markdown(cmp, claude, groq, k=2, k_hi=3)
    assert "K=2..3" in md


def test_build_repeated_report_deep_tie_break_on_latency(tmp_path: Path) -> None:
    """hallucination/grounding tied at print precision -> decides on latency_ms."""
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
            model_id=GROQ_MODEL,
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


def test_build_repeated_report_refuses_overwrite_without_force(tmp_path: Path) -> None:
    _write_arm(
        tmp_path, _arm("claude-exp", "claude-sonnet-4-6", (0.90, 0.10, 3000, 0.012))
    )
    _write_arm(
        tmp_path,
        _arm("groq-exp", GROQ_MODEL, (0.70, 0.20, 1000, 0.0006)),
    )
    build_repeated_report(
        tmp_path, "claude-exp", "groq-exp", label_a="claude", label_b="groq", stem="dup"
    )
    with pytest.raises(FileExistsError):
        build_repeated_report(
            tmp_path,
            "claude-exp",
            "groq-exp",
            label_a="claude",
            label_b="groq",
            stem="dup",
        )
    # with force -> overwrites without raising
    build_repeated_report(
        tmp_path,
        "claude-exp",
        "groq-exp",
        label_a="claude",
        label_b="groq",
        stem="dup",
        force=True,
    )


def _all_error_arm(experiment: str, model_id: str) -> list[RunRecord]:
    """3 repetitions, both zones in ERROR: none folds to a usable output."""
    return [
        _rec(
            experiment,
            citta,
            zona,
            rep=r,
            model_id=model_id,
            grounding=0.0,
            hallucination=0.0,
            latency_ms=0,
            cost_usd=0.0,
            status=RunStatus.ERROR,
        )
        for citta, zona in (("Roma", "Colosseo"), ("Milano", "Duomo"))
        for r in range(3)
    ]


def test_build_repeated_report_writes_report_and_raises_when_all_reps_degenerate(
    tmp_path: Path,
) -> None:
    """#239: after the fold no zone remains valid -> report, not traceback."""
    _write_arm(tmp_path, _all_error_arm("claude-exp", "claude-sonnet-4-6"))
    _write_arm(tmp_path, _all_error_arm("groq-exp", GROQ_MODEL))

    with pytest.raises(NoUsableOutputError):
        build_repeated_report(
            tmp_path, "claude-exp", "groq-exp", label_a="claude", label_b="groq"
        )

    md_path = tmp_path / "claude-exp_vs_groq-exp_repeated.md"
    json_path = tmp_path / "claude-exp_vs_groq-exp_repeated.json"
    assert md_path.exists()
    assert json_path.exists()
    md_text = md_path.read_text(encoding="utf-8")
    assert "Nessun output utilizzabile" in md_text
    assert "Nessun verdetto" in md_text
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["winner"] is None
    assert len(payload["failed"]) == 2


def test_build_repeated_report_still_raises_no_usable_output_if_report_write_fails(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """#239 (review follow-up): an OSError in the write must not replace
    NoUsableOutputError, otherwise the CLI loses the clean exit code.
    """
    import crime_risk_analyzer.eval.repeated_comparison as repeated_mod

    _write_arm(tmp_path, _all_error_arm("claude-exp", "claude-sonnet-4-6"))
    _write_arm(tmp_path, _all_error_arm("groq-exp", GROQ_MODEL))

    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("permission denied (simulated)")

    monkeypatch.setattr(repeated_mod, "write_no_usable_output_report", _boom)

    with pytest.raises(NoUsableOutputError):
        build_repeated_report(
            tmp_path, "claude-exp", "groq-exp", label_a="claude", label_b="groq"
        )
    assert not (tmp_path / "claude-exp_vs_groq-exp_repeated.md").exists()


def test_build_repeated_report_propagates_file_exists_error_from_report_write(
    tmp_path: Path,
) -> None:
    """The anti-overwrite guard stays prioritary also on this branch."""
    _write_arm(tmp_path, _all_error_arm("claude-exp", "claude-sonnet-4-6"))
    _write_arm(tmp_path, _all_error_arm("groq-exp", GROQ_MODEL))
    (tmp_path / "claude-exp_vs_groq-exp_repeated.md").write_text(
        "gia' presente", encoding="utf-8"
    )

    with pytest.raises(FileExistsError):
        build_repeated_report(
            tmp_path, "claude-exp", "groq-exp", label_a="claude", label_b="groq"
        )


def test_main_compare_repeated_returns_1_on_no_usable_output(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """#239: the CLI command `compare-repeated` signals the failure with exit 1."""
    import sys

    import crime_risk_analyzer.eval.__main__ as eval_main

    _write_arm(tmp_path, _all_error_arm("claude-exp", "claude-sonnet-4-6"))
    _write_arm(tmp_path, _all_error_arm("groq-exp", GROQ_MODEL))

    argv = [
        "crime_risk_analyzer.eval",
        "compare-repeated",
        "--experiment-a",
        "claude-exp",
        "--experiment-b",
        "groq-exp",
        "--results",
        str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    rc = eval_main.main()
    assert rc == 1
    assert (tmp_path / "claude-exp_vs_groq-exp_repeated.md").exists()


# --- Withheld verdict on the mute arm (#231) ---------------------------
#
# On the first real run the report declared the `baseline` arm winner
# (no LLM, empty narrative) on the hallucination axis: 0.000 for absence of
# text to judge. Vacuity must be read on the RAW records, not on the
# folded ones: `repeat._mean_record` always zeroes `narrativa` (the mean of several
# texts does not exist), so deducing it from the fold would mark every arm mute.


def _silent_arm(experiment: str) -> list[RunRecord]:
    """Arm without LLM: 3 OK repetitions, no narrative (by design)."""
    return [
        _rec(
            experiment,
            "Roma",
            "Colosseo",
            rep=r,
            model_id="baseline",
            grounding=1.0,
            hallucination=0.0,
            latency_ms=2,
            cost_usd=0.0,
            narrativa="",
        )
        for r in range(3)
    ]


def test_repeated_report_withholds_verdict_when_an_arm_never_generates(
    tmp_path: Path,
) -> None:
    _write_arm(
        tmp_path,
        _arm("analyze-exp", GROQ_MODEL, (0.84, 0.16, 22697, 0.005)),
    )
    _write_arm(tmp_path, _silent_arm("baseline-exp"))
    md_path, json_path = build_repeated_report(
        tmp_path,
        "analyze-exp",
        "baseline-exp",
        label_a="analyze",
        label_b="baseline",
        stem="ablation",
    )
    md = md_path.read_text(encoding="utf-8")
    assert "NON APPLICABILE" in md
    assert "ha scorato meglio" not in md
    assert "`baseline`" in md
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["winner"] is None
    assert payload["quality_verdict"]["applicable"] is False
    assert payload["quality_verdict"]["vacuous_arms"] == ["baseline"]
    # #238: same encoding as write_comparison (ensure_ascii=False) -- the
    # same text must not end up \u-escaped just because it is written from here.
    assert "qualità" in json_path.read_text(encoding="utf-8")
    # Review finding: quality_verdict lives ONLY at the top level, not
    # duplicated inside "comparison" too (Comparison.quality_verdict would
    # include it there by construction if it were not explicitly removed).
    assert "quality_verdict" not in payload["comparison"]


def test_repeated_report_still_declares_verdict_when_both_arms_generate(
    tmp_path: Path,
) -> None:
    """No regression on the legitimate model-vs-model comparison."""
    _write_arm(
        tmp_path, _arm("claude-exp", "claude-sonnet-4-6", (0.90, 0.10, 3000, 0.012))
    )
    _write_arm(
        tmp_path,
        _arm("groq-exp", GROQ_MODEL, (0.70, 0.20, 1000, 0.0006)),
    )
    md_path, json_path = build_repeated_report(
        tmp_path, "claude-exp", "groq-exp", label_a="claude", label_b="groq", stem="due"
    )
    md = md_path.read_text(encoding="utf-8")
    assert "`claude` ha scorato meglio" in md
    assert "NON APPLICABILE" not in md
    assert VACUOUS_CAVEAT_HEAD not in md
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["winner"]["winner"] == "claude"


def _half_silent_arm(experiment: str) -> list[RunRecord]:
    """Arm that is silent on Roma (OK, empty narrative) and speaks on Milano."""
    silent = [
        _rec(
            experiment,
            "Roma",
            "Colosseo",
            rep=r,
            model_id="m",
            grounding=1.0,
            hallucination=0.0,
            latency_ms=10,
            cost_usd=0.0,
            narrativa="",
        )
        for r in range(3)
    ]
    speaking = [
        _rec(
            experiment,
            "Milano",
            "Duomo",
            rep=r,
            model_id="m",
            grounding=0.60,
            hallucination=0.40,
            latency_ms=10,
            cost_usd=0.0,
            narrativa="prosa reale",
        )
        for r in range(3)
    ]
    return silent + speaking


def _speaking_arm(experiment: str) -> list[RunRecord]:
    """Arm that speaks on both zones, with worse hallucination."""
    return [
        _rec(
            experiment,
            citta,
            zona,
            rep=r,
            model_id="m",
            grounding=0.50,
            hallucination=0.50,
            latency_ms=1000,
            cost_usd=0.001,
            narrativa="prosa reale",
        )
        for citta, zona in (("Roma", "Colosseo"), ("Milano", "Duomo"))
        for r in range(3)
    ]


def test_repeated_report_withholds_verdict_when_a_single_zone_is_vacuous(
    tmp_path: Path,
) -> None:
    """Review C2: the mute zone lowers the hallucination mean of the arm and
    would make it win the primary axis without any warning."""
    _write_arm(tmp_path, _speaking_arm("loud-exp"))
    _write_arm(tmp_path, _half_silent_arm("half-exp"))
    md_path, json_path = build_repeated_report(
        tmp_path, "loud-exp", "half-exp", label_a="loud", label_b="half", stem="mix"
    )
    md = md_path.read_text(encoding="utf-8")
    assert "ha scorato meglio" not in md
    assert "NON APPLICABILE" in md
    # #237: the prose must not promise an operational outcome that is never
    # computed nor printed -- "confrontabili" would imply a comparison made.
    # Case-insensitive: the same wording could survive elsewhere with a
    # different capitalization (at the start of a sentence vs mid-sentence).
    assert "restano confrontabili" not in md.lower()
    assert "non calcola né dichiara un esito" in md
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["winner"] is None
    assert payload["quality_verdict"]["applicable"] is False
    assert payload["comparison"]["vacuous_zones"][0]["zona"] == "Colosseo"


def test_repeated_report_keeps_operational_table_when_verdict_withheld(
    tmp_path: Path,
) -> None:
    """The table of the operational values stays visible with the withheld verdict:
    no comparison is declared on them (#237), but the raw data stay
    readable."""
    _write_arm(
        tmp_path,
        _arm("analyze-exp", GROQ_MODEL, (0.84, 0.16, 22697, 0.005)),
    )
    _write_arm(tmp_path, _silent_arm("baseline-exp"))
    md_path, _ = build_repeated_report(
        tmp_path,
        "analyze-exp",
        "baseline-exp",
        label_a="analyze",
        label_b="baseline",
        stem="op",
    )
    md = md_path.read_text(encoding="utf-8")
    assert "Costo e latenza (metriche operative)" in md
    # Both arms stay side by side on the operational axes, with the delta.
    assert "latency_ms_analyze" in md
    assert "cost_usd_baseline" in md
    assert "latency_ms_delta" in md


def test_repeated_report_marks_verdict_applicable_in_the_happy_path(
    tmp_path: Path,
) -> None:
    """The additive key exists also when the verdict is there (not only if vacuous)."""
    _write_arm(
        tmp_path, _arm("claude-exp", "claude-sonnet-4-6", (0.90, 0.10, 3000, 0.012))
    )
    _write_arm(
        tmp_path,
        _arm("groq-exp", GROQ_MODEL, (0.70, 0.20, 1000, 0.0006)),
    )
    _, json_path = build_repeated_report(
        tmp_path, "claude-exp", "groq-exp", label_a="claude", label_b="groq", stem="ok"
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["quality_verdict"]["applicable"] is True
    assert payload["quality_verdict"]["vacuous_arms"] == []
    assert payload["comparison"]["vacuous_zones"] == []


def test_repeated_report_of_the_istat_pair_gives_the_d12_reason(
    tmp_path: Path,
) -> None:
    """F4 (final review): on the ontology vs ontology + ISTAT pair, with
    narrative in both arms, the verdict is withheld for D12 and the report
    says so, instead of speaking of a mute arm that is not there."""
    base = _arm("base-exp", GROQ_MODEL, (0.80, 0.20, 1000, 0.0006))
    with_istat = [
        r.model_copy(
            update={
                "experiment": "istat-exp",
                "run_id": r.run_id.replace("base-exp", "istat-exp"),
                "provenance": r.provenance.model_copy(
                    update={"istat": True, "experiment": "istat-exp"}
                ),
            }
        )
        for r in _arm("base-exp", GROQ_MODEL, (0.85, 0.15, 1100, 0.0007))
    ]
    _write_arm(tmp_path, base)
    _write_arm(tmp_path, with_istat)
    md_path, json_path = build_repeated_report(
        tmp_path, "istat-exp", "base-exp", label_a="istat", label_b="base", stem="d12"
    )
    md = md_path.read_text(encoding="utf-8")
    assert ISTAT_NO_WINNER_REASON in md
    assert "NON APPLICABILE" not in md
    assert "non ha prodotto narrativa" not in md
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["winner"] is None
    assert payload["quality_verdict"]["reason"] == ISTAT_NO_WINNER_REASON


def _istat_metrics(version: int) -> IstatMetrics:
    return IstatMetrics(
        versione=version,
        cifre_totali=0,
        frasi_scartabili=0,
        voci_fornite=1,
        voci_citate=1,
        frasi_istat=1,
        frasi_istat_con_luogo=1,
        direzioni_totali=0,
        direzioni_coerenti=0,
        corrispondenze_non_dichiarate=0,
        numeri_in_lettere=0,
    )


@pytest.mark.parametrize(
    "versions",
    [
        # among the repetitions of the same zone: the fold's sum rejects them
        {("Colosseo", 0): 3, ("Colosseo", 1): 4, ("Termini", 0): 4, ("Termini", 1): 4},
        # among the zones: every zone is homogeneous, the arm is not
        {("Colosseo", 0): 3, ("Colosseo", 1): 3, ("Termini", 0): 4, ("Termini", 1): 4},
    ],
)
def test_repeated_report_refuses_an_arm_with_mixed_istat_versions(
    tmp_path: Path, versions: dict[tuple[str, int], int]
) -> None:
    """#369: the repeated comparison (and therefore the winner) rejects an arm whose
    ISTAT records have different versions: M1 is graded on different texts."""

    def rec(experiment: str, zona: str, rep: int) -> RunRecord:
        return _rec(
            experiment,
            "Roma",
            zona,
            rep=rep,
            model_id=GROQ_MODEL,
            grounding=0.8,
            hallucination=0.2,
            latency_ms=1000,
            cost_usd=0.0006,
        )

    base = [rec("base-exp", zona, rep) for zona, rep in versions]
    with_istat = [
        rec("istat-exp", zona, rep).model_copy(
            update={"istat_metrics": _istat_metrics(v)}
        )
        for (zona, rep), v in versions.items()
    ]
    _write_arm(tmp_path, base)
    _write_arm(tmp_path, with_istat)
    with pytest.raises(ValueError, match="versioni"):
        build_repeated_report(tmp_path, "istat-exp", "base-exp", stem="misto")
    assert not (tmp_path / "misto.md").exists()


@pytest.mark.parametrize(("version_b", "warning"), [(4, True), (3, False)])
def test_repeated_report_warns_when_istat_arms_have_different_versions(
    tmp_path: Path, version_b: int, warning: bool
) -> None:
    """#369, D2: two arms both with ISTAT but of different versions are
    compared also at K repetitions, and the report (Markdown and JSON) warns about it;
    with the same version no warning."""

    def arm(experiment: str, version: int) -> list[RunRecord]:
        return [
            _rec(
                experiment,
                "Roma",
                "Colosseo",
                rep=rep,
                model_id=GROQ_MODEL,
                grounding=0.8,
                hallucination=0.2,
                latency_ms=1000,
                cost_usd=0.0006,
            ).model_copy(update={"istat_metrics": _istat_metrics(version)})
            for rep in range(2)
        ]

    _write_arm(tmp_path, arm("v3-exp", 3))
    _write_arm(tmp_path, arm("altro-exp", version_b))
    md_path, json_path = build_repeated_report(
        tmp_path, "v3-exp", "altro-exp", label_a="v3", label_b="altro", stem="vers"
    )
    md = md_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    field = payload["comparison"]["avviso_versioni_istat"]
    if warning:
        assert md.index(ISTAT_VERSIONS_DIFFER_HEAD) < md.index("| citta |")
        assert f"`v3`: versione 3; `altro`: versione {version_b}" in md
        assert field.startswith(ISTAT_VERSIONS_DIFFER_HEAD)
    else:
        assert ISTAT_VERSIONS_DIFFER_HEAD not in md
        assert field == ""
