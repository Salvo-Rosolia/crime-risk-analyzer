"""Risk anchoring separate from the one on POI names (#359).

The function works on the same block and the same sentences as M1, but splits the
anchored sentences in two: those that name a risk and those that name
only a point.
"""

from __future__ import annotations

import pytest

from crime_risk_analyzer.eval import metrics
from crime_risk_analyzer.eval.metrics import RiskAnchoring, risk_anchoring
from crime_risk_analyzer.models.vocab import ConfidenceSummary
from crime_risk_analyzer.orchestrator import AnalyzeResponse, GeoZone, PoiOut
from crime_risk_analyzer.rag.generation import Repro, RiskItem, RiskModel


def _models(poi: str = "Banca X") -> list[RiskModel]:
    return [
        RiskModel(
            poi_id="1",
            poi=poi,
            risks=[
                RiskItem(
                    hazard="Bank_robbery",
                    confidence="verificato",
                    tag="ONTOLOGIA",
                    hazard_label_it="Rapina in banca",
                    hazard_label_en="Bank robbery",
                )
            ],
        )
    ]


def _onto(body: str) -> str:
    return f"Sintesi della zona.\n\nRischi da ontologia [ONTOLOGIA]\n{body}"


def _calc(narrativa: str, poi: str = "Banca X") -> RiskAnchoring | None:
    models = _models(poi)
    return risk_anchoring(
        narrativa,
        mode="analyze",
        poi_names=[m.poi for m in models],
        risk_models=models,
    )


def test_sentence_with_italian_risk_label() -> None:
    r = _calc(_onto("Possibile rapina in banca nella zona."))
    assert r is not None
    assert r == RiskAnchoring(
        frasi_misurate=1,
        frasi_ancorate_rischio=1,
        frasi_ancorate_solo_poi=0,
        frasi_ancorate_poi_e_rischio=0,
        conforme=True,
    )
    assert r.ancoraggio_rischi == 1.0


def test_sentence_with_only_the_poi_name() -> None:
    r = _calc(_onto("La Banca X attira molte persone."))
    assert r is not None
    assert (r.frasi_ancorate_rischio, r.frasi_ancorate_solo_poi) == (0, 1)
    assert r.ancoraggio_rischi == 0.0


def test_sentence_with_risk_and_poi_counts_as_risk() -> None:
    r = _calc(_onto("Alla Banca X e' possibile una rapina in banca."))
    assert r is not None
    assert (r.frasi_ancorate_rischio, r.frasi_ancorate_solo_poi) == (1, 0)


def test_sentence_without_anchors() -> None:
    r = _calc(_onto("Zona molto frequentata. Rapina in banca possibile."))
    assert r is not None
    assert r.frasi_misurate == 2
    assert (r.frasi_ancorate_rischio, r.frasi_ancorate_solo_poi) == (1, 0)
    assert r.ancoraggio_rischi == pytest.approx(0.5)


def test_risk_identifier_anchors() -> None:
    r = _calc(_onto("Rischio Bank_robbery."))
    assert r is not None and r.frasi_ancorate_rischio == 1


def test_empty_narrative_not_gradable() -> None:
    assert _calc("") is None
    assert _calc("   ") is None


def test_no_anchor_not_gradable() -> None:
    assert (
        risk_anchoring(
            _onto("Rapina in banca."), mode="analyze", poi_names=[], risk_models=[]
        )
        is None
    )


def test_without_measured_block_not_conforming() -> None:
    r = _calc("Testo libero che parla di rapina in banca alla Banca X.")
    assert r is not None
    assert r == RiskAnchoring(
        frasi_misurate=0,
        frasi_ancorate_rischio=0,
        frasi_ancorate_solo_poi=0,
        frasi_ancorate_poi_e_rischio=0,
        conforme=False,
    )
    assert r.ancoraggio_rischi == 0.0


def test_other_arms_block_not_conforming() -> None:
    # The ablated arm is measured on its own block: [ONTOLOGIA] does not count.
    models = _models()
    r = risk_anchoring(
        _onto("Rapina in banca."),
        mode="no_ontology_prompt",
        poi_names=["Banca X"],
        risk_models=models,
    )
    assert r is not None and r.conforme is False


def test_ablated_arm_measured_on_its_own_block() -> None:
    models = _models()
    r = risk_anchoring(
        "Sintesi.\n\nRischi dalla sintesi del modello [SINTESI-LLM]\n"
        "La Banca X e' frequentata. Possibile rapina in banca.",
        mode="no_ontology_prompt",
        poi_names=["Banca X"],
        risk_models=models,
    )
    assert r == RiskAnchoring(
        frasi_misurate=2,
        frasi_ancorate_rischio=1,
        frasi_ancorate_solo_poi=1,
        frasi_ancorate_poi_e_rischio=0,
        conforme=True,
    )


def test_sentence_with_poi_and_risk_counts_in_both_items() -> None:
    # The stricter rule "POI and risk in the same sentence" (#264): the sentence
    # with the point and the risk is anchored by the risk and counts here too.
    r = _calc(_onto("Alla Banca X c'e' rischio di rapina in banca. Rapina in banca."))
    assert r == RiskAnchoring(
        frasi_misurate=2,
        frasi_ancorate_rischio=2,
        frasi_ancorate_solo_poi=0,
        frasi_ancorate_poi_e_rischio=1,
        conforme=True,
    )


def test_nameless_poi_discarded() -> None:
    # An empty name must not anchor every sentence ("" in s is always true).
    # Since #264 without a POI with a name there is nothing to anchor a sentence: not
    # gradable.
    assert _calc(_onto("Zona molto frequentata."), poi="") is None


def test_only_nameless_poi_and_risks_not_gradable() -> None:
    assert (
        risk_anchoring(
            _onto("Zona."), mode="analyze", poi_names=["", "  "], risk_models=[]
        )
        is None
    )


def test_header_present_but_empty_block_not_conforming() -> None:
    r = _calc(
        "Sintesi della zona.\n\nRischi da ontologia [ONTOLOGIA]\n\n"
        "Rischi dal contesto [CONTESTO]\nRapina in banca alla Banca X."
    )
    assert r is not None
    assert r == RiskAnchoring(0, 0, 0, 0, conforme=False)


_grade = metrics._grade  # pyright: ignore[reportPrivateUsage]


def _response(narrativa: str) -> AnalyzeResponse:
    poi = [
        PoiOut(
            id="1",
            name="Banca X",
            ontology_class="Bank",
            lat=1.0,
            lon=2.0,
            confidence="verificato",
            ontology_label_it="Banca",
            ontology_label_en="Bank",
        ),
        PoiOut(
            id="2",
            name="Bar Y",
            ontology_class="GenericUrbanPOI",
            lat=1.0,
            lon=2.0,
            confidence=None,
        ),
    ]
    return AnalyzeResponse(
        citta="Roma",
        zona_normalizzata="Centro",
        poi=poi,
        # As in production: one entry per POI, even without risks.
        risk_models=[*_models(), RiskModel(poi_id="2", poi="Bar Y", risks=[])],
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


@pytest.mark.parametrize(
    "body",
    [
        "Rapina in banca. Il Bar Y e' aperto. Alla Banca X Bank robbery. Folla.",
        "Zona tranquilla.",
        "",
    ],
)
def test_poi_plus_poi_and_risk_matches_m1(body: str) -> None:
    # M1 counts as anchored the sentence that names a POI (#264): POI only, or POI and
    # risk.
    resp = _response(_onto(body))
    graded = _grade(resp, "analyze")
    r = risk_anchoring(
        resp.narrativa,
        mode="analyze",
        poi_names=[m.poi for m in resp.risk_models],
        risk_models=resp.risk_models,
    )
    assert graded is not None and r is not None
    if r.conforme:
        assert (
            r.frasi_ancorate_poi_e_rischio + r.frasi_ancorate_solo_poi,
            r.frasi_misurate,
        ) == graded
    else:
        # Not conforming: M1 gives (0, 1), here zero sentences and anchoring 0.0.
        assert graded == (0, 1) and r.frasi_misurate == 0
