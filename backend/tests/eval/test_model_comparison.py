"""Confronto Claude vs Llama (#33), interamente offline.

Il comparatore a due bracci vive gia' in :mod:`crime_risk_analyzer.eval.compare`
(#32, GENERICO su label libere): #33 lo RIUSA per ``claude`` vs ``groq`` senza
ricostruirlo. Qui si blindano due contratti del deliverable #33:

1. le config esperimento versionate in ``backend/experiments/`` per il confronto
   modelli (entrambe ``mode=analyze``, stesse 4 zone ``ROSTER[:4]`` → iso-input);
2. le estensioni di ``compare`` richieste dall'issue (report JSON, tabella
   costo/latenza separata dalla qualita', caveat sui proxy testuali).

Nessuna run live: i ``RunRecord`` dei due bracci sono costruiti a mano con
metriche sintetiche (come i test di #32). Nessuna chiamata LLM (Claude e' a
pagamento e non si esegue; Llama non viene interrogato in test).
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
from crime_risk_analyzer.models.vocab import ConfidenceSummary
from crime_risk_analyzer.orchestrator import AnalyzeResponse, PoiOut
from crime_risk_analyzer.rag.generation import Repro, RiskItem, RiskModel

#: backend/experiments (test_file → eval → tests → backend).
EXPERIMENTS_DIR = Path(__file__).resolve().parents[2] / "experiments"

#: I due bracci del confronto modelli. Il braccio Claude riusa la config
#: analyze/claude gia' presente (#32); il braccio Groq e' la nuova config
#: analyze/groq (serve anche per un'ablation gratuita futura).
CLAUDE_ARM = "ablation-analyze"
GROQ_ARM = "ablation-analyze-groq"


def _zones(name: str) -> list[tuple[str, str]]:
    cfg = load_config(EXPERIMENTS_DIR / f"{name}.json")
    return [(c.citta, c.zona) for c in cfg.cases]


# --- contratto config: i due bracci analyze/claude e analyze/groq -----------


def test_groq_arm_config_parses_with_expected_name_mode_model() -> None:
    """La nuova config analyze/groq esiste, parsa e ha mode/model attesi."""
    cfg = load_config(EXPERIMENTS_DIR / f"{GROQ_ARM}.json")
    assert cfg.name == GROQ_ARM
    assert cfg.mode == "analyze"
    assert cfg.model == "groq"


def test_claude_arm_is_analyze_claude() -> None:
    """Il braccio Claude riusato e' analyze/claude (documenta il riuso #32)."""
    cfg = load_config(EXPERIMENTS_DIR / f"{CLAUDE_ARM}.json")
    assert cfg.mode == "analyze"
    assert cfg.model == "claude"


def test_both_model_arms_share_the_same_four_zones() -> None:
    """Confronto iso-input: i due modelli girano sulle STESSE 4 (citta, zona)."""
    zones_claude = _zones(CLAUDE_ARM)
    zones_groq = _zones(GROQ_ARM)
    assert len(zones_groq) == 4
    assert zones_claude == zones_groq


def test_model_arms_zones_anchored_to_c1_roster() -> None:
    """Le 4 zone sono le prime 4 del roster di validazione C1 (#31)."""
    roster_pairs = [(city.citta, city.zona) for city in ROSTER]
    assert _zones(GROQ_ARM) == roster_pairs[:4]


# --- confronto a due modelli (offline, record sintetici) --------------------

#: Metriche sintetiche per zona (grounding, hallucination, latency_ms, cost_usd),
#: allineate posizionalmente a ROSTER[:4]. Scenario plausibile ma INVENTATO
#: (nessuna run reale): Claude piu' accurato ma piu' caro e lento; Groq/Llama
#: piu' economico e veloce con qualita' proxy piu' bassa. Servono solo a rendere
#: delta e separazione costo/latenza verificabili offline.
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
    """RunRecord ``analyze`` sintetico; snapshot_id per (citta, zona) → iso-input.

    Lo ``snapshot_id`` deriva SOLO da (citta, zona) via
    :func:`make_snapshot_key` (come l'harness, #110): i due bracci sulla stessa
    zona citano lo stesso snapshot, quindi il confronto e' iso-input.
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
    return _arm(GROQ_ARM, "llama-3.3-70b-versatile", _GROQ_METRICS)


def test_two_model_comparison_computes_per_zone_delta() -> None:
    """Riuso di compare_records su claude vs groq: delta = claude - groq."""
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
    """Le label del report sono claude/groq (il comparatore e' generico)."""
    cmp = compare_records(_claude_arm(), _groq_arm(), label_a="claude", label_b="groq")
    assert (cmp.label_a, cmp.label_b) == ("claude", "groq")


def test_to_json_report_has_both_models_delta_and_aggregate() -> None:
    """Report JSON: 4 metriche affiancate claude/groq + delta, per-caso e medio."""
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
    # aggregato presente
    assert "mean_a" in data and "mean_b" in data and "mean_delta" in data


def test_operational_markdown_has_only_cost_and_latency_columns() -> None:
    """Tabella separata: SOLO costo/latenza, nessuna metrica di qualita'."""
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
    # le metriche-proxy di qualita' NON compaiono nella tabella operativa
    assert "grounding" not in op
    assert "hallucination" not in op


def test_operational_markdown_marked_as_operational_with_mean_row() -> None:
    """La tabella e' etichettata come operativa e porta la riga aggregata."""
    cmp = compare_records(_claude_arm(), _groq_arm(), label_a="claude", label_b="groq")
    op = operational_markdown(cmp)
    assert "operativ" in op.lower()
    assert "MEDIA" in op


def test_proxy_caveat_flags_quality_metrics_as_textual_proxies() -> None:
    """Il caveat avverte che grounding/hallucination sono proxy TESTUALI."""
    lc = PROXY_CAVEAT.lower()
    assert "proxy" in lc
    assert "grounding" in lc
    assert "hallucination" in lc
    # distingue le misure operative dirette (costo/latenza)
    assert "cost" in lc or "latenz" in lc or "operativ" in lc


def test_to_markdown_embeds_main_table_operational_section_and_caveat() -> None:
    """Il report MD unisce: tabella qualita' + tabella operativa separata + caveat."""
    cmp = compare_records(_claude_arm(), _groq_arm(), label_a="claude", label_b="groq")
    md = to_markdown(cmp)
    # tabella principale con le 4 metriche affiancate + delta
    assert "grounding_claude" in md
    assert "grounding_groq" in md
    assert "grounding_delta" in md
    # sezione operativa separata, embeddata verbatim
    assert operational_markdown(cmp).strip() in md
    # caveat metodologico presente
    assert PROXY_CAVEAT.strip() in md


def test_write_comparison_also_writes_json_sibling(tmp_path: Path) -> None:
    """write_comparison emette anche <stem>.json accanto a .csv/.md (report #33)."""
    cmp = compare_records(_claude_arm(), _groq_arm(), label_a="claude", label_b="groq")
    csv_path, md_path = write_comparison(tmp_path, cmp, "claude_vs_groq")
    json_path = tmp_path / "claude_vs_groq.json"
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["label_a"] == "claude"
    assert data["label_b"] == "groq"
    # backward-compat #32: csv + md restano prodotti e restano i path ritornati
    assert csv_path.exists() and md_path.exists()


# --- regressione reperto A (#163): metrica → verdetto -----------------------


def _resp163(narrativa: str) -> AnalyzeResponse:
    """AnalyzeResponse con ancoraggi {"banca a", "bank_robbery"}; narrativa data."""
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
                confidence="confermato",
                sparql_path="Bank → havingHazard → Bank_robbery",
            )
        ],
        risk_models=[
            RiskModel(
                poi="Banca A",
                risks=[
                    RiskItem(
                        hazard="Bank_robbery",
                        confidence="confermato",
                        tag="ONTOLOGIA",
                    )
                ],
            )
        ],
        narrativa=narrativa,
        confidence_summary=ConfidenceSummary(confermato=1),
        llm_used="claude-sonnet-4-6",
        latenza_ms=100,
        repro=Repro(temperature=0.0, seed=0, prompt_hash="ph"),
        cache_hit=False,
        fallback=False,
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


def test_reperto_a_sparsely_citing_arm_loses_on_hallucination() -> None:
    """Guard end-to-end del buco reperto A: chi cita poco perde l'asse allucinazione.

    Entrambi i bracci hanno stesso costo/latenza (stesso _resp163) → decide solo
    l'asse hallucination. Prima di #163 il braccio 'sparse' avrebbe hallucination
    0.0 (una sola frase taggata, ancorata) e avrebbe VINTO; col nuovo denominatore
    le 3 asserzioni non citate lo portano a 0.75 e perde.
    """
    well = _mv(
        _resp163(
            "[ONTOLOGIA] Banca A presenta rischio rapina. "
            "[ONTOLOGIA] Banca A subisce furti frequenti."
        )
    )
    sparse = _mv(
        _resp163(
            "[ONTOLOGIA] Banca A presenta rischio rapina. "
            "Banca A è pericolosa di notte. "
            "Banca A preoccupa i residenti. "
            "Banca A resta un punto critico."
        )
    )
    verdict = decide_winner(well, sparse, label_a="claude", label_b="groq")
    assert verdict.winner == "claude"
    assert verdict.deciding_axis == "hallucination"
