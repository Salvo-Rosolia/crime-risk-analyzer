from __future__ import annotations

from rdflib import OWL, RDF, Graph

from crime_risk_analyzer.eval import city_agnostic as ca
from crime_risk_analyzer.ontology_namespaces import TERMINUS
from crime_risk_analyzer.overpass_client import Poi


def _poi(name: str, terminus_class: str) -> Poi:
    return {
        "id": name,
        "name": name,
        "lat": 41.0,
        "lon": 12.0,
        "osm_tags": "amenity=bank",
        "terminus_class": terminus_class,
        "citta": "Roma",
    }


def _graph() -> Graph:
    g = Graph()
    g.add((TERMINUS["Bank"], RDF.type, OWL.Class))
    g.add((TERMINUS["Museum"], RDF.type, OWL.Class))
    return g


def test_class_exists_true_for_declared_class() -> None:
    assert ca.class_exists(_graph(), "Bank") is True


def test_class_exists_false_for_absent_class() -> None:
    assert ca.class_exists(_graph(), "Nonexistent") is False


def test_class_exists_false_for_generic_fallback() -> None:
    assert ca.class_exists(_graph(), "GenericUrbanPOI") is False


def test_compute_coverage_verbatim_below_derived() -> None:
    # Bank: esiste (verbatim+derived). Prison: mappata ma assente dal grafo
    # (solo derived). GenericUrbanPOI: nessuna delle due.
    pois = [_poi("a", "Bank"), _poi("b", "Prison"), _poi("c", "GenericUrbanPOI")]
    verbatim, derived = ca.compute_coverage(pois, _graph())
    assert derived == 2 / 3  # Bank + Prison mappate
    assert verbatim == 1 / 3  # solo Bank esiste nel grafo


def test_compute_coverage_empty_is_zero() -> None:
    assert ca.compute_coverage([], _graph()) == (0.0, 0.0)


def test_boundary_ok_true_for_valid_bbox() -> None:
    assert ca.boundary_ok((41.0, 12.0, 41.5, 12.5)) is True


def test_boundary_ok_false_for_degenerate_bbox() -> None:
    assert ca.boundary_ok((41.0, 12.0, 41.0, 12.5)) is False


def test_build_record_sets_pass_flags() -> None:
    capture = ca.CityCapture(
        citta="Roma",
        zona="Colosseo",
        lat=41.89,
        lon=12.49,
        bbox=(41.0, 12.0, 41.5, 12.5),
        switch_ms=1200,
        pois=[_poi("a", "Bank"), _poi("b", "Museum")],
    )
    rec = ca.build_record(capture, _graph(), "hash123")
    assert rec.n_poi == 2
    assert rec.coverage_verbatim == 1.0
    assert rec.coverage_derived == 1.0
    assert rec.boundary_ok is True
    assert rec.pass_verbatim is True
    assert rec.pass_derived is True
    assert rec.pass_switch is True
    assert rec.ontology_hash == "hash123"
