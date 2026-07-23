from __future__ import annotations

from crime_risk_analyzer.eval.metrics import grounding, hallucination
from crime_risk_analyzer.models.vocab import ConfidenceSummary
from crime_risk_analyzer.orchestrator import AnalyzeResponse, PoiOut
from crime_risk_analyzer.rag.generation import Repro, RiskItem, RiskModel


def _response(narrativa: str) -> AnalyzeResponse:
    return AnalyzeResponse(
        citta="Roma",
        zona_normalizzata="Centro",
        poi=[
            PoiOut(
                id="1",
                name="Banca X",
                terminus_class="Bank",
                lat=1.0,
                lon=2.0,
                confidence="verificato",
                terminus_label_it="Banca",
                terminus_label_en="Bank",
            )
        ],
        risk_models=[
            RiskModel(
                poi="Banca X",
                risks=[
                    RiskItem(
                        hazard="Bank_robbery",
                        confidence="verificato",
                        tag="ONTOLOGIA",
                        hazard_label_it="rapina in banca",
                        hazard_label_en="bank robbery",
                    )
                ],
            )
        ],
        narrativa=narrativa,
        confidence_summary=ConfidenceSummary(verificato=1),
        llm_used="claude-x",
        latenza_ms=10,
        repro=Repro(temperature=0.0, seed=0, prompt_hash="h"),
        cache_hit=False,
    )


def test_it_hazard_term_is_anchored() -> None:
    # La narrativa cita l'hazard SOLO in italiano: prima di #77 non era ancorato.
    resp = _response("Presente una rapina in banca [ONTOLOGIA].")
    assert grounding(resp) == 1.0
    assert hallucination(resp) == 0.0


def test_unrelated_it_sentence_is_not_anchored() -> None:
    resp = _response("Presente un furto di biciclette [ONTOLOGIA].")
    assert grounding(resp) == 0.0
    assert hallucination(resp) == 1.0
