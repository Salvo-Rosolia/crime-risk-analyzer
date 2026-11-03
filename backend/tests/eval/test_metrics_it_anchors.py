from __future__ import annotations

from crime_risk_analyzer.eval.metrics import grounding, hallucination
from crime_risk_analyzer.models.vocab import ConfidenceSummary
from crime_risk_analyzer.orchestrator import AnalyzeResponse, GeoZone, PoiOut
from crime_risk_analyzer.rag.generation import Repro, RiskItem, RiskModel


def _response(narrativa: str) -> AnalyzeResponse:
    return AnalyzeResponse(
        citta="Roma",
        zona_normalizzata="Centro",
        poi=[
            PoiOut(
                id="1",
                name="Banca X",
                ontology_class="Bank",
                lat=1.0,
                lon=2.0,
                confidence="verificato",
                ontology_label_it="Banca",
                ontology_label_en="Bank",
            )
        ],
        risk_models=[
            RiskModel(
                poi_id="1",
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
        contesto_hash="h-ctx",
        zona_geo=GeoZone(
            lat=41.0,
            lon=12.0,
            bbox_min_lat=40.9,
            bbox_min_lon=11.9,
            bbox_max_lat=41.1,
            bbox_max_lon=12.1,
        ),
    )


# #229 (M1): real block form (#196), the proxy grades the body of the
# [ONTOLOGIA] block. The controlled IT label of the hazard (#77) no longer anchors on
# its own (#264): the POI name is needed, even when the narrative cites the hazard in
# Italian.
def _ontology_narrative(body: str) -> str:
    return f"Sintesi della zona.\n\nRischi da ontologia [ONTOLOGIA]\n{body}"


def test_it_hazard_term_alone_is_not_anchored() -> None:
    # #264: rule 6 imposes the label, so the IT label alone does not anchor.
    resp = _response(_ontology_narrative("Presente una rapina in banca."))
    assert grounding(resp) == 0.0
    assert hallucination(resp) == 1.0


def test_it_hazard_term_with_the_poi_is_anchored() -> None:
    resp = _response(_ontology_narrative("Alla Banca X presente una rapina in banca."))
    assert grounding(resp) == 1.0
    assert hallucination(resp) == 0.0


def test_unrelated_it_sentence_is_not_anchored() -> None:
    resp = _response(_ontology_narrative("Presente un furto di biciclette."))
    assert grounding(resp) == 0.0
    assert hallucination(resp) == 1.0
