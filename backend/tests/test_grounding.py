"""Test del grounding layer (#24): RetrievalContext grezzo -> context validato.

ground() e' una funzione PURA: nessun I/O, nessun mock. I RetrievalContext sono
costruiti a mano. Il caso 8 aggancia l'output al consumer reale (generation).
"""

from __future__ import annotations

from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.models.vocab import ConfidenceSummary
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.rag.generation import RiskItem, build_context_str
from crime_risk_analyzer.rag.grounding import ground
from crime_risk_analyzer.rag.retrieval import RetrievalContext, RetrievalStats


def _poi(poi_id: str, name: str, terminus_class: str) -> Poi:
    return Poi(
        id=poi_id,
        name=name,
        lat=41.9,
        lon=12.5,
        osm_tags="amenity=bank",
        terminus_class=terminus_class,
        citta="Roma",
    )


def _profile(
    terminus_class: str,
    *,
    hazards: list[str] | None = None,
    vulnerabilities: list[str] | None = None,
    sparql_paths: list[str] | None = None,
) -> PoiRiskProfile:
    return PoiRiskProfile(
        terminus_class=terminus_class,
        hazards=hazards or [],
        vulnerabilities=vulnerabilities or [],
        sparql_paths=sparql_paths or [],
    )


def _ctx(
    pois: list[Poi], profiles: dict[str, PoiRiskProfile], *, zona: str = "Centro"
) -> RetrievalContext:
    return RetrievalContext(
        citta="Roma",
        zona=zona,
        geo=GeoResult(
            lat=41.9,
            lon=12.5,
            bbox=Bbox(min_lat=41.88, min_lon=12.48, max_lat=41.9, max_lon=12.5),
        ),
        pois=pois,
        profiles=profiles,
        stats=RetrievalStats(n_pois=len(pois), n_classes=len(profiles)),
    )


def test_ground_happy_path_multi_class() -> None:
    bank = _profile(
        "Bank",
        hazards=["Robbery"],
        vulnerabilities=["Poor_surveillance"],
        sparql_paths=[
            "Bank → havingHazard → Robbery",
            "Bank → isVulnerableTo → Poor_surveillance",
        ],
    )
    museum = _profile(
        "Museum", hazards=["Theft"], sparql_paths=["Museum → havingHazard → Theft"]
    )
    out = ground(
        _ctx(
            [_poi("1", "Banca A", "Bank"), _poi("2", "Museo", "Museum")],
            {"Bank": bank, "Museum": museum},
        )
    )

    assert out["zona"] == "Centro"
    assert len(out["validated_risks"]) == 2
    vr0 = out["validated_risks"][0]
    assert vr0["poi"] == "Banca A"
    assert vr0["terminus_class"] == "Bank"
    assert vr0["risks"] == [
        {
            "hazard": "Robbery",
            "tag": "ONTOLOGIA",
            "confidence": "verificato",
            "source": "Bank → havingHazard → Robbery",
        }
    ]
    assert vr0["vulnerabilities"] == ["Poor_surveillance"]
    assert vr0["sparql_path"] == "Bank → havingHazard → Robbery"


def test_ground_source_uses_inherited_path() -> None:
    # hazard ereditato: il path cita System (superclasse), non Bank
    prof = _profile(
        "Bank",
        hazards=["Crime_explosion"],
        sparql_paths=["System → havingHazard → Crime_explosion"],
    )
    out = ground(_ctx([_poi("1", "Banca", "Bank")], {"Bank": prof}))

    assert (
        out["validated_risks"][0]["risks"][0]["source"]
        == "System → havingHazard → Crime_explosion"
    )


def test_ground_source_fallback_when_missing() -> None:
    # nessun path havingHazard per Robbery -> source sintetizzato sulla classe del POI
    prof = _profile(
        "Bank",
        hazards=["Robbery"],
        sparql_paths=["Bank → havingCriticalEvent → Heist"],
    )
    out = ground(_ctx([_poi("1", "Banca", "Bank")], {"Bank": prof}))

    assert (
        out["validated_risks"][0]["risks"][0]["source"]
        == "Bank → havingHazard → Robbery"
    )


def test_ground_includes_generic_poi_with_empty_risks() -> None:
    out = ground(
        _ctx(
            [_poi("1", "Bar", "GenericUrbanPOI")],
            {"GenericUrbanPOI": _profile("GenericUrbanPOI")},
        )
    )

    vr = out["validated_risks"][0]
    assert vr["poi"] == "Bar"
    assert vr["risks"] == []
    assert vr["vulnerabilities"] == []
    assert vr["sparql_path"] is None


def test_ground_zero_pois() -> None:
    out = ground(_ctx([], {}))

    assert out["validated_risks"] == []
    assert out["confidence_summary"] == {
        "verificato": 0,
        "da_confermare": 0,
        "ipotesi": 0,
    }


def test_ground_confidence_summary_counts_all_verificato() -> None:
    # POI tutti con nome OSM -> ogni rischio e' verificato (doppio ancoraggio)
    bank = _profile(
        "Bank",
        hazards=["Robbery", "Fraud"],
        sparql_paths=[
            "Bank → havingHazard → Robbery",
            "Bank → havingHazard → Fraud",
        ],
    )
    museum = _profile(
        "Museum", hazards=["Theft"], sparql_paths=["Museum → havingHazard → Theft"]
    )
    out = ground(
        _ctx(
            [_poi("1", "A", "Bank"), _poi("2", "B", "Museum")],
            {"Bank": bank, "Museum": museum},
        )
    )

    assert out["confidence_summary"] == {
        "verificato": 3,
        "da_confermare": 0,
        "ipotesi": 0,
    }


def test_ground_named_poi_risks_are_verificato() -> None:
    # #202: POI con nome OSM = entita' verificabile -> hazard ontologico verificato
    # (doppio ancoraggio: ontologia + POI OSM identificabile).
    prof = _profile(
        "Bank", hazards=["Robbery"], sparql_paths=["Bank → havingHazard → Robbery"]
    )
    out = ground(_ctx([_poi("1", "Banca A", "Bank")], {"Bank": prof}))

    risk = out["validated_risks"][0]["risks"][0]
    assert risk["confidence"] == "verificato"
    assert risk["tag"] == "ONTOLOGIA"


def test_ground_anonymous_poi_risks_are_da_confermare() -> None:
    # #202: feature OSM senza nome = ancoraggio OSM debole -> hazard ontologico
    # da_confermare. La FONTE resta l'ontologia: il tag NON cambia (cambia solo la
    # forza probatoria).
    prof = _profile(
        "Bank", hazards=["Robbery"], sparql_paths=["Bank → havingHazard → Robbery"]
    )
    out = ground(_ctx([_poi("1", "", "Bank")], {"Bank": prof}))

    risk = out["validated_risks"][0]["risks"][0]
    assert risk["confidence"] == "da_confermare"
    assert risk["tag"] == "ONTOLOGIA"


def test_ground_whitespace_name_poi_is_da_confermare() -> None:
    # #202: un nome di soli whitespace e' una feature anonima -> da_confermare.
    prof = _profile(
        "Bank", hazards=["Robbery"], sparql_paths=["Bank → havingHazard → Robbery"]
    )
    out = ground(_ctx([_poi("1", "   ", "Bank")], {"Bank": prof}))

    assert out["validated_risks"][0]["risks"][0]["confidence"] == "da_confermare"


def test_ground_confidence_summary_mixed_counts() -> None:
    # #202: input reale misto -> conteggi reali con verificato>0 E da_confermare>0,
    # ipotesi resta 0 (rimandato, fuori scope).
    bank = _profile(
        "Bank",
        hazards=["Robbery", "Fraud"],
        sparql_paths=[
            "Bank → havingHazard → Robbery",
            "Bank → havingHazard → Fraud",
        ],
    )
    museum = _profile(
        "Museum", hazards=["Theft"], sparql_paths=["Museum → havingHazard → Theft"]
    )
    out = ground(
        _ctx(
            [_poi("1", "Banca A", "Bank"), _poi("2", "", "Museum")],
            {"Bank": bank, "Museum": museum},
        )
    )

    assert out["confidence_summary"] == {
        "verificato": 2,
        "da_confermare": 1,
        "ipotesi": 0,
    }


def test_ground_poi_without_hazards_has_none_sparql_path() -> None:
    # classe reale ma profilo senza hazard -> risks vuoti, sparql_path None
    out = ground(_ctx([_poi("1", "X", "Bank")], {"Bank": _profile("Bank")}))

    vr = out["validated_risks"][0]
    assert vr["risks"] == []
    assert vr["sparql_path"] is None


def test_ground_output_conforms_to_generation_consumer() -> None:
    bank = _profile(
        "Bank",
        hazards=["Robbery"],
        vulnerabilities=["Poor_surveillance"],
        sparql_paths=["Bank → havingHazard → Robbery"],
    )
    out = ground(_ctx([_poi("1", "Banca", "Bank")], {"Bank": bank}, zona="Centro"))

    # build_context_str (consumer pubblico) non solleva e serializza zona + POI
    prompt = build_context_str(dict(out))
    assert "Centro" in prompt
    assert "Banca" in prompt
    assert "Robbery" in prompt

    # ogni rischio e' un RiskItem valido (cio' che _risk_models_from_context costruisce)
    for vr in out["validated_risks"]:
        for risk in vr["risks"]:
            item = RiskItem.model_validate(
                {
                    "hazard": risk["hazard"],
                    "confidence": risk["confidence"],
                    "tag": risk["tag"],
                }
            )
            assert item.tag == "ONTOLOGIA"
            assert item.confidence == "verificato"

    # confidence_summary validabile dal modello canonico
    cs = ConfidenceSummary.model_validate(out["confidence_summary"])
    assert cs.verificato == 1
    assert cs.da_confermare == 0
    assert cs.ipotesi == 0
