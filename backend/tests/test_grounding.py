"""Tests for the grounding layer (#24): raw RetrievalContext -> validated context.

ground() calls neither network nor model: the RetrievalContext objects are built
by hand and need no mock. It is no longer a pure function in the strict sense
(#345): with the ISTAT data it reads the local copy of the data, loaded once
and kept in cache. Case 8 hooks the output to the real consumer (generation).
"""

from __future__ import annotations

import pytest as _pytest

from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.geocoding import GeoResult as _GeoResult
from crime_risk_analyzer.istat import rows as _rows_mod
from crime_risk_analyzer.istat.rows import IstatPoi as _IstatPoi
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.geo import Bbox as _Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.models.risk import PoiRiskProfile as _Profile
from crime_risk_analyzer.models.vocab import ConfidenceSummary
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.overpass_client import Poi as _Poi
from crime_risk_analyzer.rag.generation import RiskItem, build_context_str
from crime_risk_analyzer.rag.grounding import ground
from crime_risk_analyzer.rag.grounding import ground as _ground
from crime_risk_analyzer.rag.retrieval import RetrievalContext, RetrievalStats
from crime_risk_analyzer.rag.retrieval import RetrievalContext as _Ctx
from crime_risk_analyzer.rag.retrieval import RetrievalStats as _Stats
from crime_risk_analyzer.sources.model import SourceSet


def _poi(poi_id: str, name: str, ontology_class: str) -> Poi:
    return Poi(
        id=poi_id,
        name=name,
        lat=41.9,
        lon=12.5,
        osm_tags="amenity=bank",
        ontology_class=ontology_class,
        citta="Roma",
    )


def _profile(
    ontology_class: str,
    *,
    hazards: list[str] | None = None,
    critical_events: list[str] | None = None,
    vulnerabilities: list[str] | None = None,
    stakeholders: list[str] | None = None,
    sparql_paths: list[str] | None = None,
) -> PoiRiskProfile:
    """Synthetic profile. The axes are passed from here and not with
    ``model_copy(update=)``, which would bypass the Pydantic validation of the
    model."""
    return PoiRiskProfile(
        ontology_class=ontology_class,
        hazards=hazards or [],
        critical_events=critical_events or [],
        vulnerabilities=vulnerabilities or [],
        stakeholders=stakeholders or [],
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
    # The id is born here: it is the key with which the risks stay attributable to
    # the point.
    assert vr0["poi_id"] == "1"
    assert out["validated_risks"][1]["poi_id"] == "2"
    assert vr0["ontology_class"] == "Bank"
    assert vr0["risks"] == [
        {
            "hazard": "Robbery",
            "tag": "ONTOLOGIA",
            "confidence": "verificato",
            "source": "Bank → havingHazard → Robbery",
        }
    ]
    # Since #256 every axis carries its own citation, not just the name.
    assert vr0["vulnerabilities"] == [
        {
            "name": "Poor_surveillance",
            "source": "Bank → isVulnerableTo → Poor_surveillance",
        }
    ]
    assert vr0["sparql_path"] == "Bank → havingHazard → Robbery"


def test_ground_anchors_all_four_axes_with_their_own_path() -> None:
    """The executor extracts four TERMINUS axes: the grounding anchors them all (#270).

    Before, only the hazards became risks with a citation; the critical events were
    computed at every request and read by nobody, and the vulnerabilities reached
    the prompt as bare strings, without the path that anchors them to the ontology.
    An axis without a citation is not verifiable, so it cannot be shown next to
    those that are. The stakeholder stayed out until #270, when the controlled
    vocabulary covered the 72 fillers without an Italian label.
    """
    prof = _profile(
        "Bank",
        hazards=["Robbery"],
        critical_events=["Heist"],
        vulnerabilities=["Poor_surveillance"],
        stakeholders=["Mayor"],
        sparql_paths=[
            "Bank → havingHazard → Robbery",
            "Bank → havingCriticalEvent → Heist",
            "Bank → isVulnerableTo → Poor_surveillance",
            "Bank → havingPerformer → Mayor",
        ],
    )

    vr = ground(_ctx([_poi("1", "Banca A", "Bank")], {"Bank": prof}))[
        "validated_risks"
    ][0]

    assert vr["critical_events"] == [
        {"name": "Heist", "source": "Bank → havingCriticalEvent → Heist"}
    ]
    assert vr["vulnerabilities"] == [
        {
            "name": "Poor_surveillance",
            "source": "Bank → isVulnerableTo → Poor_surveillance",
        }
    ]
    assert vr["stakeholders"] == [
        {"name": "Mayor", "source": "Bank → havingPerformer → Mayor"}
    ]


def test_ground_finds_the_path_also_on_the_second_vulnerability_property() -> None:
    """The vulnerability uses TWO properties (divergence #78): both must be searched.

    If ``OntologyConfig.vulnerability`` lost ``havingVulnerability``, a filler that
    in the ontology comes from that property would not find its own path and
    ``_source_for`` would SYNTHESIZE one on ``isVulnerableTo``: a syntactically
    perfect and FALSE citation, silent, indistinguishable downstream from a real
    one -- in a layer that exists for verifiability. Without this test the mutation
    left the suite green.
    """
    prof = _profile(
        "Bank",
        vulnerabilities=["Poor_surveillance"],
        sparql_paths=["Bank → havingVulnerability → Poor_surveillance"],
    )

    vr = ground(_ctx([_poi("1", "Banca", "Bank")], {"Bank": prof}))["validated_risks"][
        0
    ]

    assert vr["vulnerabilities"] == [
        {
            "name": "Poor_surveillance",
            "source": "Bank → havingVulnerability → Poor_surveillance",
        }
    ]


def test_ground_source_uses_inherited_path() -> None:
    # inherited hazard: the path cites System (superclass), not Bank
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
    # no havingHazard path for Robbery -> source synthesized on the POI class
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
    # Even a POI without risks carries its own id: the consumer hooks all the points
    # by id, not only those covered by the ontology.
    assert vr["poi_id"] == "1"
    assert vr["risks"] == []
    assert vr["vulnerabilities"] == []
    assert vr["stakeholders"] == []
    assert vr["sparql_path"] is None


def test_ground_zero_pois() -> None:
    out = ground(_ctx([], {}))

    assert out["validated_risks"] == []
    assert out["confidence_summary"] == {
        "verificato": 0,
        "da_confermare": 0,
    }


def test_ground_confidence_summary_counts_all_verificato() -> None:
    # POIs all with an OSM name -> every risk is verified (double anchoring)
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
    }


def test_ground_named_poi_risks_are_verificato() -> None:
    # #202: POI with an OSM name = verifiable entity -> verified ontological hazard
    # (double anchoring: ontology + identifiable OSM POI).
    prof = _profile(
        "Bank", hazards=["Robbery"], sparql_paths=["Bank → havingHazard → Robbery"]
    )
    out = ground(_ctx([_poi("1", "Banca A", "Bank")], {"Bank": prof}))

    risk = out["validated_risks"][0]["risks"][0]
    assert risk["confidence"] == "verificato"
    assert risk["tag"] == "ONTOLOGIA"


def test_ground_anonymous_poi_risks_are_da_confermare() -> None:
    # #202: OSM feature without a name = weak OSM anchoring -> ontological hazard
    # da_confermare. The SOURCE stays the ontology: the tag does NOT change (only the
    # probative force changes).
    prof = _profile(
        "Bank", hazards=["Robbery"], sparql_paths=["Bank → havingHazard → Robbery"]
    )
    out = ground(_ctx([_poi("1", "", "Bank")], {"Bank": prof}))

    risk = out["validated_risks"][0]["risks"][0]
    assert risk["confidence"] == "da_confermare"
    assert risk["tag"] == "ONTOLOGIA"


def test_ground_whitespace_name_poi_is_da_confermare() -> None:
    # #202: a whitespace-only name is an anonymous feature -> da_confermare.
    prof = _profile(
        "Bank", hazards=["Robbery"], sparql_paths=["Bank → havingHazard → Robbery"]
    )
    out = ground(_ctx([_poi("1", "   ", "Bank")], {"Bank": prof}))

    assert out["validated_risks"][0]["risks"][0]["confidence"] == "da_confermare"


def test_ground_confidence_summary_mixed_counts() -> None:
    # #202: real mixed input -> real counts with verificato>0 AND da_confermare>0.
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
    }


def test_ground_poi_without_hazards_has_none_sparql_path() -> None:
    # real class but profile without hazards -> empty risks, sparql_path None
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

    # build_context_str (public consumer) does not raise and serializes zone + POI
    prompt = build_context_str(dict(out))
    assert "Centro" in prompt
    assert "Banca" in prompt
    assert "Robbery" in prompt

    # every risk is a valid RiskItem (what _risk_models_from_context builds)
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

    # confidence_summary validatable by the canonical model
    cs = ConfidenceSummary.model_validate(out["confidence_summary"])
    assert cs.verificato == 1
    assert cs.da_confermare == 0


# --- #345: place and ISTAT rows computed in the grounding ---


def _istat_context(lat: float, lon: float, hazards: list[str]) -> _Ctx:
    poi = _Poi(
        id="node/1",
        name="Banca A",
        lat=lat,
        lon=lon,
        osm_tags="amenity=bank",
        ontology_class="Bank",
        citta="Roma",
    )
    ontology_profile = _Profile(
        ontology_class="Bank",
        hazards=hazards,
        sparql_paths=[f"Bank → havingHazard → {h}" for h in hazards],
    )
    return _Ctx(
        citta="Roma",
        zona="Colosseo",
        geo=_GeoResult(
            lat=lat, lon=lon, bbox=_Bbox(lat - 0.01, lon - 0.01, lat + 0.01, lon + 0.01)
        ),
        pois=[poi],
        profiles={"Bank": ontology_profile},
        stats=_Stats(n_pois=1, n_classes=1),
    )


def test_ground_computes_the_istat_rows_from_the_poi_coordinates() -> None:
    out = _ground(_istat_context(41.8902, 12.4922, ["Bank_robbery", "Landslide"]))
    istat = out["validated_risks"][0].get("istat")
    assert isinstance(istat, _IstatPoi)
    assert istat.cornice.luogo_codice == "058091"
    assert [r.voce for r in istat.righe] == ["BANKROB"]
    assert istat.righe[0].collegamenti[0].hazard == "Bank_robbery"


def test_ground_without_istat_rows_outside_the_polygons_or_without_voci() -> None:
    sea = _ground(_istat_context(41.0, 12.0, ["Bank_robbery"]))
    without_voci = _ground(_istat_context(41.8902, 12.4922, ["Landslide"]))
    assert sea["validated_risks"][0].get("istat") is None
    assert without_voci["validated_risks"][0].get("istat") is None


def test_ground_without_istat_data_does_not_fail(
    monkeypatch: _pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_rows_mod, "istat_data_or_none", lambda: None)
    out = _ground(_istat_context(41.8902, 12.4922, ["Bank_robbery"]))
    assert out["validated_risks"][0].get("istat") is None
    assert out["validated_risks"][0]["risks"][0]["hazard"] == "Bank_robbery"


def _custom_ontology_set() -> SourceSet:
    import dataclasses

    from crime_risk_analyzer.sources.context import default_set
    from crime_risk_analyzer.sources.model import OntologyConfig

    return dataclasses.replace(
        default_set(),
        id="proprieta-custom",
        kind="custom",
        ontology=OntologyConfig(
            namespace="http://example.org/o#",
            hazard="hasRisk",
            critical_event="hasEvent",
            performer="hasActor",
            vulnerability=("weakTo",),
        ),
    )


def test_ground_uses_the_active_ontology_properties_in_the_fallback() -> None:
    """Without a path in the ``sparql_paths`` the synthesized citation uses the
    properties of the active set, not the TERMINUS ones: ``Bank -> havingHazard``
    does not exist in an ontology that calls the property ``hasRisk`` (#434)."""
    from crime_risk_analyzer.sources.context import bind

    custom = _custom_ontology_set()
    prof = _profile(
        "Bank",
        hazards=["Robbery"],
        critical_events=["Alarm"],
        vulnerabilities=["Poor_surveillance"],
        stakeholders=["Guard"],
    )
    with bind(custom):
        out = ground(_ctx([_poi("1", "Banca", "Bank")], {"Bank": prof}))

    vr = out["validated_risks"][0]
    assert vr["risks"][0]["source"] == "Bank → hasRisk → Robbery"
    assert vr["critical_events"][0]["source"] == "Bank → hasEvent → Alarm"
    assert vr["vulnerabilities"][0]["source"] == "Bank → weakTo → Poor_surveillance"
    assert vr["stakeholders"][0]["source"] == "Bank → hasActor → Guard"
    assert vr["sparql_path"] == "Bank → hasRisk → Robbery"


def test_ground_recognizes_the_paths_with_the_active_ontology_properties() -> None:
    """A real path inherited from a superclass with a custom property is taken from the
    ``sparql_paths`` and not synthesized from ``ontology_class``."""
    from crime_risk_analyzer.sources.context import bind

    custom = _custom_ontology_set()
    prof = _profile(
        "Bank",
        hazards=["Robbery"],
        sparql_paths=["Building → hasRisk → Robbery"],
    )
    with bind(custom):
        out = ground(_ctx([_poi("1", "Banca", "Bank")], {"Bank": prof}))

    assert out["validated_risks"][0]["risks"][0]["source"] == (
        "Building → hasRisk → Robbery"
    )
