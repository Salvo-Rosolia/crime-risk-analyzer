import pytest

from crime_risk_analyzer.eval.metrics import (
    compute_metrics,
    cost_usd_of,
    grounding,
    hallucination,
    latency_ms,
)
from crime_risk_analyzer.models.vocab import ConfidenceSummary
from crime_risk_analyzer.orchestrator import AnalyzeResponse, PoiOut
from crime_risk_analyzer.rag.generation import Repro, RiskItem, RiskModel


def _resp(
    narrativa: str,
    *,
    with_citation: bool = True,
    tokens: tuple[int, int] = (10, 20),
) -> AnalyzeResponse:
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
                sparql_path=(
                    "Bank → havingHazard → Bank_robbery" if with_citation else None
                ),
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
        latenza_ms=120,
        repro=Repro(temperature=0.0, seed=0, prompt_hash="ph"),
        cache_hit=False,
        fallback=False,
        tokens_input=tokens[0],
        tokens_output=tokens[1],
    )


def test_grounding_full_when_tagged_claim_backed() -> None:
    r = _resp("[ONTOLOGIA] Banca A presenta rischio rapina.")
    assert grounding(r) == 1.0


def test_grounding_zero_when_narrativa_untagged() -> None:
    r = _resp("La zona presenta alcuni rischi generici.")
    assert grounding(r) == 0.0


def test_hallucination_flags_unbacked_ontologia_claim() -> None:
    r = _resp("[ONTOLOGIA] Il Museo X presenta rischio incendio.")
    assert hallucination(r) == 1.0


def test_hallucination_zero_when_backed() -> None:
    r = _resp("[ONTOLOGIA] Banca A presenta rischio.")
    assert hallucination(r) == 0.0


def test_latency_passthrough() -> None:
    assert latency_ms(_resp("x")) == 120


def test_compute_metrics_cost() -> None:
    m = compute_metrics(_resp("[ONTOLOGIA] Banca A rischio.", tokens=(1_000_000, 0)))
    assert m.cost_usd == pytest.approx(3.0)
    assert 0.0 <= m.grounding <= 1.0


def test_empty_narrativa_is_vacuously_grounded() -> None:
    r = _resp("", tokens=(0, 0))
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0


def test_cost_usd_of_zero_when_no_llm() -> None:
    r = _resp("[ONTOLOGIA] Banca A rischio.", tokens=(1_000_000, 0)).model_copy(
        update={"llm_used": ""}
    )
    assert cost_usd_of(r) == 0.0
