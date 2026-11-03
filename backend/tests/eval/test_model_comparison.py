"""Claude vs Groq comparison (#33), entirely offline.

The two-arm comparator already lives in :mod:`crime_risk_analyzer.eval.compare`
(#32, GENERIC on free labels): #33 REUSES it for ``claude`` vs ``groq`` without
rebuilding it. Here two contracts of the #33 deliverable are locked:

1. the experiment configs versioned in ``backend/experiments/`` for the model
   comparison (both ``mode=analyze``, same 4 zones ``ROSTER[:4]`` -> iso-input);
2. the extensions of ``compare`` requested by the issue (JSON report,
   cost/latency table separate from quality, caveat on the textual proxies).

No live run: the ``RunRecord``s of the two arms are built by hand with
synthetic metrics (like the #32 tests). No LLM call (Claude is
paid and is not run; the Groq model is not queried in tests).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crime_risk_analyzer.eval.city_agnostic import ROSTER
from crime_risk_analyzer.eval.cli import load_config
from crime_risk_analyzer.eval.compare import (
    PROXY_CAVEAT,
    MetricValues,
    compare_records,
    operational_markdown,
    to_json,
    to_markdown,
    write_comparison,
)
from crime_risk_analyzer.eval.harness import make_snapshot_key
from crime_risk_analyzer.eval.metrics import compute_metrics
from crime_risk_analyzer.eval.schema import (
    Metrics,
    Provenance,
    RunRecord,
    RunStatus,
)
from crime_risk_analyzer.eval.winner import decide_winner
from crime_risk_analyzer.llm.client import GROQ_MODEL
from crime_risk_analyzer.models.vocab import ConfidenceSummary
from crime_risk_analyzer.orchestrator import AnalyzeResponse, GeoZone, PoiOut
from crime_risk_analyzer.rag.generation import Repro, RiskItem, RiskModel

#: backend/experiments (test_file -> eval -> tests -> backend).
EXPERIMENTS_DIR = Path(__file__).resolve().parents[2] / "experiments"

#: The two arms of the model comparison. The Claude arm reuses the already present
#: analyze/claude config (#32); the Groq arm is the new analyze/groq
#: config (it also serves for a future free ablation).
CLAUDE_ARM = "ablation-analyze"
GROQ_ARM = "ablation-analyze-groq"


def _zones(name: str) -> list[tuple[str, str]]:
    cfg = load_config(EXPERIMENTS_DIR / f"{name}.json")
    return [(c.citta, c.zona) for c in cfg.cases]


# --- config contract: the two arms analyze/claude and analyze/groq -----------


def test_groq_arm_config_parses_with_expected_name_mode_model() -> None:
    """The new analyze/groq config exists, parses and has the expected mode/model."""
    cfg = load_config(EXPERIMENTS_DIR / f"{GROQ_ARM}.json")
    assert cfg.name == GROQ_ARM
    assert cfg.mode == "analyze"
    assert cfg.model == "groq"


def test_claude_arm_is_analyze_claude() -> None:
    """The reused Claude arm is analyze/claude (documents the #32 reuse)."""
    cfg = load_config(EXPERIMENTS_DIR / f"{CLAUDE_ARM}.json")
    assert cfg.mode == "analyze"
    assert cfg.model == "claude"


def test_both_model_arms_share_the_same_four_zones() -> None:
    """Iso-input comparison: the two models run on the SAME 4 (citta, zona)."""
    zones_claude = _zones(CLAUDE_ARM)
    zones_groq = _zones(GROQ_ARM)
    assert len(zones_groq) == 4
    assert zones_claude == zones_groq


def test_model_arms_zones_anchored_to_c1_roster() -> None:
    """The 4 zones are the first 4 of the C1 validation roster (#31)."""
    roster_pairs = [(city.citta, city.zona) for city in ROSTER]
    assert _zones(GROQ_ARM) == roster_pairs[:4]


# --- two-model comparison (offline, synthetic records) --------------------

#: Synthetic metrics per zone (grounding, hallucination, latency_ms, cost_usd),
#: positionally aligned with ROSTER[:4]. Plausible but INVENTED scenario
#: (no real run): Claude more accurate but more expensive and slow; the Groq
#: arm cheaper and faster with lower proxy quality. They only serve to
#: make the deltas and the cost/latency separation verifiable offline.
_CLAUDE_METRICS: tuple[tuple[float, float, int, float], ...] = (
    (0.90, 0.10, 3200, 0.0120),
    (0.85, 0.15, 3000, 0.0110),
    (0.80, 0.20, 3100, 0.0100),
    (0.88, 0.12, 2900, 0.0105),
)
_GROQ_METRICS: tuple[tuple[float, float, int, float], ...] = (
    (0.70, 0.30, 1200, 0.0006),
    (0.65, 0.35, 1100, 0.0005),
    (0.60, 0.40, 1150, 0.00055),
    (0.72, 0.28, 1000, 0.00052),
)


def _rec(
    experiment: str,
    citta: str,
    zona: str,
    *,
    model_id: str,
    grounding: float,
    hallucination: float,
    latency_ms: int,
    cost_usd: float,
) -> RunRecord:
    """Synthetic ``analyze`` RunRecord; snapshot_id per (citta, zona) -> iso-input.

    The ``snapshot_id`` derives ONLY from (citta, zona) via
    :func:`make_snapshot_key` (like the harness, #110): the two arms on the same
    zone cite the same snapshot, so the comparison is iso-input.
    """
    return RunRecord(
        run_id=f"{experiment}__{citta}__{zona}".lower(),
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
            snapshot_id=make_snapshot_key(citta, zona),
            model_id=model_id,
            prompt_hash="p",
            temperature=0.0,
            seed=0,
            experiment=experiment,
        ),
    )


def _arm(
    experiment: str,
    model_id: str,
    metrics: tuple[tuple[float, float, int, float], ...],
) -> list[RunRecord]:
    return [
        _rec(
            experiment,
            city.citta,
            city.zona,
            model_id=model_id,
            grounding=g,
            hallucination=h,
            latency_ms=lat,
            cost_usd=cost,
        )
        for city, (g, h, lat, cost) in zip(ROSTER[:4], metrics, strict=True)
    ]


def _claude_arm() -> list[RunRecord]:
    return _arm(CLAUDE_ARM, "claude-sonnet-4-6", _CLAUDE_METRICS)


def _groq_arm() -> list[RunRecord]:
    return _arm(GROQ_ARM, GROQ_MODEL, _GROQ_METRICS)


def test_two_model_comparison_computes_per_zone_delta() -> None:
    """Reuse of compare_records on claude vs groq: delta = claude - groq."""
    cmp = compare_records(_claude_arm(), _groq_arm(), label_a="claude", label_b="groq")
    by_zone = {(z.citta, z.zona): z for z in cmp.zones}
    roma = by_zone[("Roma", "Colosseo")]
    assert roma.a.grounding == pytest.approx(0.90)
    assert roma.b.grounding == pytest.approx(0.70)
    assert roma.delta.grounding == pytest.approx(0.20)
    assert roma.delta.hallucination == pytest.approx(-0.20)
    assert roma.delta.latency_ms == pytest.approx(2000.0)
    assert roma.delta.cost_usd == pytest.approx(0.0114)


def test_two_model_comparison_labels_preserved() -> None:
    """The report labels are claude/groq (the comparator is generic)."""
    cmp = compare_records(_claude_arm(), _groq_arm(), label_a="claude", label_b="groq")
    assert (cmp.label_a, cmp.label_b) == ("claude", "groq")


def test_to_json_report_has_both_models_delta_and_aggregate() -> None:
    """JSON report: 4 metrics side by side claude/groq + delta, per case and mean."""
    cmp = compare_records(_claude_arm(), _groq_arm(), label_a="claude", label_b="groq")
    data = json.loads(to_json(cmp))
    assert data["label_a"] == "claude"
    assert data["label_b"] == "groq"
    zones = {(z["citta"], z["zona"]): z for z in data["zones"]}
    assert len(zones) == 4
    roma = zones[("Roma", "Colosseo")]
    for metric in ("grounding", "hallucination", "latency_ms", "cost_usd"):
        assert metric in roma["a"]
        assert metric in roma["b"]
        assert metric in roma["delta"]
    assert roma["a"]["cost_usd"] == pytest.approx(0.0120)
    assert roma["b"]["cost_usd"] == pytest.approx(0.0006)
    assert roma["delta"]["grounding"] == pytest.approx(0.20)
    # aggregate present
    assert "mean_a" in data and "mean_b" in data and "mean_delta" in data


def test_operational_markdown_has_only_cost_and_latency_columns() -> None:
    """Separate table: ONLY cost/latency, no quality metric."""
    cmp = compare_records(_claude_arm(), _groq_arm(), label_a="claude", label_b="groq")
    op = operational_markdown(cmp)
    for col in (
        "latency_ms_claude",
        "latency_ms_groq",
        "latency_ms_delta",
        "cost_usd_claude",
        "cost_usd_groq",
        "cost_usd_delta",
    ):
        assert col in op
    # the quality proxy metrics do NOT appear in the operational table
    assert "grounding" not in op
    assert "hallucination" not in op


def test_operational_markdown_marked_as_operational_with_mean_row() -> None:
    """The table is labelled as operational and carries the aggregate row."""
    cmp = compare_records(_claude_arm(), _groq_arm(), label_a="claude", label_b="groq")
    op = operational_markdown(cmp)
    assert "operativ" in op.lower()
    assert "MEDIA" in op


def test_proxy_caveat_flags_quality_metrics_as_textual_proxies() -> None:
    """The caveat warns that grounding/hallucination are TEXTUAL proxies."""
    lc = PROXY_CAVEAT.lower()
    assert "proxy" in lc
    assert "grounding" in lc
    assert "hallucination" in lc
    # distinguishes the direct operational measures (cost/latency)
    assert "cost" in lc or "latenz" in lc or "operativ" in lc


def test_to_markdown_embeds_main_table_operational_section_and_caveat() -> None:
    """The MD report joins: quality table + separate operational table + caveat."""
    cmp = compare_records(_claude_arm(), _groq_arm(), label_a="claude", label_b="groq")
    md = to_markdown(cmp)
    # main table with the 4 metrics side by side + delta
    assert "grounding_claude" in md
    assert "grounding_groq" in md
    assert "grounding_delta" in md
    # separate operational section, embedded verbatim
    assert operational_markdown(cmp).strip() in md
    # methodological caveat present
    assert PROXY_CAVEAT.strip() in md


def test_write_comparison_also_writes_json_sibling(tmp_path: Path) -> None:
    """write_comparison also emits <stem>.json next to .csv/.md (report #33)."""
    cmp = compare_records(_claude_arm(), _groq_arm(), label_a="claude", label_b="groq")
    csv_path, md_path = write_comparison(tmp_path, cmp, "claude_vs_groq")
    json_path = tmp_path / "claude_vs_groq.json"
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["label_a"] == "claude"
    assert data["label_b"] == "groq"
    # backward-compat #32: csv + md are still produced and the returned paths stay
    assert csv_path.exists() and md_path.exists()


# --- regression finding A (#163): metric -> verdict -----------------------


def _resp163(narrativa: str) -> AnalyzeResponse:
    """AnalyzeResponse with anchors {"banca a", "bank_robbery"}; given narrative."""
    return AnalyzeResponse(
        citta="Roma",
        zona_normalizzata="Centro",
        poi=[
            PoiOut(
                id="1",
                name="Banca A",
                terminus_class="Bank",
                lat=41.0,
                lon=12.0,
                confidence="verificato",
                sparql_path="Bank → havingHazard → Bank_robbery",
            )
        ],
        risk_models=[
            RiskModel(
                poi_id="1",
                poi="Banca A",
                risks=[
                    RiskItem(
                        hazard="Bank_robbery",
                        confidence="verificato",
                        tag="ONTOLOGIA",
                    )
                ],
            )
        ],
        narrativa=narrativa,
        confidence_summary=ConfidenceSummary(verificato=1),
        llm_used="claude-sonnet-4-6",
        latenza_ms=100,
        repro=Repro(temperature=0.0, seed=0, prompt_hash="ph"),
        cache_hit=False,
        fallback=False,
        contesto_hash="h-ctx",
        zona_geo=GeoZone(
            lat=41.0,
            lon=12.0,
            bbox_min_lat=40.9,
            bbox_min_lon=11.9,
            bbox_max_lat=41.1,
            bbox_max_lon=12.1,
        ),
        tokens_input=10,
        tokens_output=20,
    )


def _mv(resp: AnalyzeResponse) -> MetricValues:
    m = compute_metrics(resp)
    return MetricValues(
        grounding=m.grounding,
        hallucination=m.hallucination,
        latency_ms=float(m.latency_ms),
        cost_usd=m.cost_usd,
    )


def _ont163(*sentences: str) -> str:
    """Block narrative (#196/#229): body of the [ONTOLOGIA] block from the given
    sentences.

    M1 grades the body of the [ONTOLOGIA] block; the source is in the header, not
    inline.
    """
    body = "\n".join(sentences)
    return f"Sintesi della zona.\n\nRischi da ontologia [ONTOLOGIA]\n{body}"


def test_arm_padding_ontology_with_unanchored_claims_loses_on_hallucination() -> None:
    """End-to-end guard (M1 analogue of finding A #163): whoever fills the
    [ONTOLOGIA] block with NOT anchored assertions loses the hallucination axis.

    Both arms have the same cost/latency (same _resp163) -> only the
    hallucination axis decides. Under M1 (#229) the "citation" is no longer an inline
    tag but belonging to the [ONTOLOGIA] block: an arm that cites the data in every
    sentence in the block has hallucination 0.0; an arm that pads the block with 3
    assertions that name no real datum goes up to 0.75 and loses. (Metric values
    identical to the original #163 guard: only the form of the narrative goes from
    inline-tag to blocks.)
    """
    well = _mv(
        _ont163_resp(
            "Banca A presenta rischio rapina.",
            "Banca A subisce furti frequenti.",
        )
    )
    sparse = _mv(
        _ont163_resp(
            "Banca A presenta rischio rapina.",
            "La situazione desta preoccupazione di notte.",
            "I residenti restano inquieti.",
            "Resta un punto critico da monitorare.",
        )
    )
    verdict = decide_winner(well, sparse, label_a="claude", label_b="groq")
    assert verdict.winner == "claude"
    assert verdict.deciding_axis == "hallucination"


def _ont163_resp(*sentences: str) -> AnalyzeResponse:
    return _resp163(_ont163(*sentences))
