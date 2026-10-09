"""Ancoraggio ai rischi separato da quello ai nomi dei POI (#359).

La funzione lavora sullo stesso blocco e sulle stesse frasi di M1, ma divide le
frasi ancorate in due: quelle che nominano un rischio e quelle che nominano
soltanto un punto.
"""

from __future__ import annotations

import pytest

from crime_risk_analyzer.eval import metrics
from crime_risk_analyzer.eval.metrics import RiskAnchoring, risk_anchoring
from crime_risk_analyzer.models.vocab import ConfidenceSummary
from crime_risk_analyzer.orchestrator import AnalyzeResponse, PoiOut, ZonaGeo
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


def test_frase_con_etichetta_italiana_del_rischio() -> None:
    r = _calc(_onto("Possibile rapina in banca nella zona."))
    assert r is not None
    assert r == RiskAnchoring(
        frasi_misurate=1,
        frasi_ancorate_rischio=1,
        frasi_ancorate_solo_poi=0,
        conforme=True,
    )
    assert r.ancoraggio_rischi == 1.0


def test_frase_con_solo_il_nome_del_poi() -> None:
    r = _calc(_onto("La Banca X attira molte persone."))
    assert r is not None
    assert (r.frasi_ancorate_rischio, r.frasi_ancorate_solo_poi) == (0, 1)
    assert r.ancoraggio_rischi == 0.0


def test_frase_con_rischio_e_poi_conta_come_rischio() -> None:
    r = _calc(_onto("Alla Banca X e' possibile una rapina in banca."))
    assert r is not None
    assert (r.frasi_ancorate_rischio, r.frasi_ancorate_solo_poi) == (1, 0)


def test_frase_senza_ancoraggi() -> None:
    r = _calc(_onto("Zona molto frequentata. Rapina in banca possibile."))
    assert r is not None
    assert r.frasi_misurate == 2
    assert (r.frasi_ancorate_rischio, r.frasi_ancorate_solo_poi) == (1, 0)
    assert r.ancoraggio_rischi == pytest.approx(0.5)


def test_identifier_del_rischio_ancora() -> None:
    r = _calc(_onto("Rischio Bank_robbery."))
    assert r is not None and r.frasi_ancorate_rischio == 1


def test_narrativa_vuota_non_gradabile() -> None:
    assert _calc("") is None
    assert _calc("   ") is None


def test_nessun_ancoraggio_non_gradabile() -> None:
    assert (
        risk_anchoring(
            _onto("Rapina in banca."), mode="analyze", poi_names=[], risk_models=[]
        )
        is None
    )


def test_senza_blocco_misurato_non_conforme() -> None:
    r = _calc("Testo libero che parla di rapina in banca alla Banca X.")
    assert r is not None
    assert r == RiskAnchoring(
        frasi_misurate=0,
        frasi_ancorate_rischio=0,
        frasi_ancorate_solo_poi=0,
        conforme=False,
    )
    assert r.ancoraggio_rischi == 0.0


def test_blocco_dell_altro_braccio_non_conforme() -> None:
    # Il braccio ablato si misura sul suo blocco: [ONTOLOGIA] non conta.
    models = _models()
    r = risk_anchoring(
        _onto("Rapina in banca."),
        mode="no_ontology_prompt",
        poi_names=["Banca X"],
        risk_models=models,
    )
    assert r is not None and r.conforme is False


def test_braccio_ablato_misurato_sul_suo_blocco() -> None:
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
        conforme=True,
    )


def test_poi_senza_nome_scartato() -> None:
    # Un nome vuoto non deve ancorare ogni frase ("" in s e' sempre vero).
    r = _calc(_onto("Zona molto frequentata."), poi="")
    assert r is not None
    assert (r.frasi_ancorate_rischio, r.frasi_ancorate_solo_poi) == (0, 0)


def test_solo_poi_senza_nome_e_rischi_non_gradabile() -> None:
    assert (
        risk_anchoring(
            _onto("Zona."), mode="analyze", poi_names=["", "  "], risk_models=[]
        )
        is None
    )


def test_header_presente_ma_blocco_vuoto_non_conforme() -> None:
    r = _calc(
        "Sintesi della zona.\n\nRischi da ontologia [ONTOLOGIA]\n\n"
        "Rischi dal contesto [CONTESTO]\nRapina in banca alla Banca X."
    )
    assert r is not None
    assert r == RiskAnchoring(0, 0, 0, conforme=False)


_grade = metrics._grade  # pyright: ignore[reportPrivateUsage]


def _response(narrativa: str) -> AnalyzeResponse:
    poi = [
        PoiOut(
            id="1",
            name="Banca X",
            terminus_class="Bank",
            lat=1.0,
            lon=2.0,
            confidence="verificato",
            terminus_label_it="Banca",
            terminus_label_en="Bank",
        ),
        PoiOut(
            id="2",
            name="Bar Y",
            terminus_class="GenericUrbanPOI",
            lat=1.0,
            lon=2.0,
            confidence=None,
        ),
    ]
    return AnalyzeResponse(
        citta="Roma",
        zona_normalizzata="Centro",
        poi=poi,
        # Come in produzione: una voce per POI, anche senza rischi.
        risk_models=[*_models(), RiskModel(poi_id="2", poi="Bar Y", risks=[])],
        narrativa=narrativa,
        confidence_summary=ConfidenceSummary(verificato=1),
        llm_used="claude-x",
        latenza_ms=10,
        repro=Repro(temperature=0.0, seed=0, prompt_hash="h"),
        cache_hit=False,
        contesto_hash="h-ctx",
        zona_geo=ZonaGeo(
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
def test_rischio_piu_solo_poi_coincide_con_m1(body: str) -> None:
    # La scomposizione ripartisce esattamente cio' che M1 conta come ancorato.
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
            r.frasi_ancorate_rischio + r.frasi_ancorate_solo_poi,
            r.frasi_misurate,
        ) == graded
    else:
        # Non conforme: M1 da' (0, 1), qui zero frasi e ancoraggio 0.0.
        assert graded == (0, 1) and r.frasi_misurate == 0
