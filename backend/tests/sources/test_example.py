"""Example set of the dynamic sources (#417)."""

from collections.abc import Iterator

import pytest
from rdflib import URIRef
from rdflib.namespace import RDFS

from crime_risk_analyzer import zone_context_cache
from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.istat.data import istat_data_or_none
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.orchestrator import run_baseline
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.sources.build import fallback_places
from crime_risk_analyzer.sources.context import bind, current_executor
from crime_risk_analyzer.sources.example import (
    EXAMPLE_VOCABULARY,
    example_files,
    example_set,
    example_warnings,
)
from crime_risk_analyzer.sources.model import TERMINUS_CONFIG
from crime_risk_analyzer.sources.parsing import check_sources
from crime_risk_analyzer.sources.vocabulary import TERMINUS_VOCABULARY


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    zone_context_cache.clear()
    yield
    zone_context_cache.clear()


def _poi_classes() -> set[str]:
    return set(example_set().osm.osm_to_class.values())


def test_example_files_have_no_errors() -> None:
    parsed, report = check_sources(
        example_files(), EXAMPLE_VOCABULARY, fallback_places=fallback_places()
    )
    assert report.errors == []
    assert parsed is not None


def test_example_set_has_kind_example_and_is_built_once() -> None:
    assert example_set().kind == "example"
    assert example_set().id == "example"
    assert example_set() is example_set()


def test_invented_ontology_with_about_ten_poi_classes() -> None:
    assert len(_poi_classes()) == 10
    assert EXAMPLE_VOCABULARY.namespace == "http://example.org/mini-crime#"
    assert EXAMPLE_VOCABULARY.namespace != TERMINUS_VOCABULARY.namespace
    assert set(EXAMPLE_VOCABULARY.properties).isdisjoint(TERMINUS_VOCABULARY.properties)
    assert example_set().ontology.namespace == EXAMPLE_VOCABULARY.namespace
    assert example_set().ontology != TERMINUS_CONFIG


def test_every_poi_class_has_at_least_one_hazard() -> None:
    executor = example_set().executor
    for cls in sorted(_poi_classes()):
        assert executor.profile(cls).hazards, cls


def test_profile_uses_the_examples_own_properties() -> None:
    profile = example_set().executor.profile("Bank")
    assert "Bank_robbery" in profile.hazards
    assert "Bank → hasRisk → Bank_robbery" in profile.sparql_paths
    assert profile.critical_events
    assert profile.stakeholders
    assert profile.vulnerabilities


def test_class_inherits_the_restrictions_of_the_superclass() -> None:
    assert "Theft" in example_set().executor.profile("Pharmacy").hazards


def test_labels_present_for_half_of_the_poi_classes() -> None:
    ss = example_set()
    with_labels = {
        str(c).rsplit("#", 1)[-1]
        for c in ss.graph.subjects(RDFS.label)
        if isinstance(c, URIRef)
    }
    assert len(with_labels & _poi_classes()) == 5
    labels = ss.labels
    assert labels is not None
    assert labels["Bank"] == ("Banca", "Bank")
    assert labels["Jewelry_shop"] == ("Jewelry shop", "Jewelry shop")  # fallback


def test_warnings_report_missing_labels() -> None:
    codes = {p.code for p in example_warnings()}
    assert "etichetta_mancante" in codes


def test_data_matches_delitti_json() -> None:
    real = istat_data_or_none()
    assert real is not None
    example = example_set().istat.dati
    assert example is not None
    compared = 0
    for place, per_item in example.delitti.valori.items():
        for item, per_year in per_item.items():
            for year, value in per_year.items():
                assert value == real.delitti.valori[place][item][year], (
                    place,
                    item,
                    year,
                )
                compared += 1
    assert compared >= 5
    # explicit sample of five values, with place, item and year
    sample = [
        ("058091", "ROBBER", 2024),
        ("015146", "THEFT", 2014),
        ("063049", "TOT", 2024),
        ("IT", "BANKROB", 2024),
        ("058091", "CARTHEF", 2014),
    ]
    for place, item, year in sample:
        assert example.delitti.valore(place, item, year) == real.delitti.valore(
            place, item, year
        )
        assert example.delitti.valore(place, item, year) is not None


def test_example_places_are_three_municipalities_with_our_boundaries() -> None:
    data = example_set().istat.dati
    assert data is not None
    assert {lg.nome_breve for lg in data.luoghi} == {"Roma", "Milano", "Napoli"}


def test_non_comparable_series_declared_in_the_table() -> None:
    assert example_set().istat.voci_rottura == {"DAMAGE", "TOT"}
    assert example_set().istat.mappatura["Burglary"].voce_istat is None


async def test_baseline_with_fake_pois_cites_the_example_ontology() -> None:
    async def geo(city: str, zone: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    async def poi_source(bbox: Bbox, city: str) -> list[Poi]:
        return [
            {
                "id": "node/1",
                "name": "Banca Esempio",
                "lat": 41.89,
                "lon": 12.49,
                "osm_tags": "amenity=bank",
                "terminus_class": "Bank",
                "citta": city,
            }
        ]

    with bind(example_set()):
        response = await run_baseline(
            "Roma",
            "Colosseo",
            executor=current_executor(),
            poi_source=poi_source,
            geo_source=geo,
        )
    risks = response.risk_models[0].risks
    assert risks
    assert all(r.tag == "ONTOLOGIA" for r in risks)
    assert {r.hazard for r in risks} == {"Bank_robbery", "Theft"}  # Theft: inherited
    for r in risks:
        assert r.source is not None
        cls, _prop, entity = (part.strip() for part in r.source.split("→"))
        assert (cls, entity) == ("Bank", r.hazard)
    assert response.poi[0].sparql_path is not None
    assert response.poi[0].terminus_label_it == "Banca"
