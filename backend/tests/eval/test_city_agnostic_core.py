from __future__ import annotations

from rdflib import OWL, RDF, Graph

from crime_risk_analyzer.eval import city_agnostic as ca
from crime_risk_analyzer.eval.geometry import CityBoundary
from crime_risk_analyzer.ontology_namespaces import TERMINUS
from crime_risk_analyzer.overpass_client import Poi

# Quadrato che contiene (12.0, 41.0): usato come confine città nelle fixture.
_SQUARE = CityBoundary(
    polygons=[[[(11.0, 40.0), (13.0, 40.0), (13.0, 42.0), (11.0, 42.0)]]]
)
# Quadrato lontano: nessun POI dentro.
_ELSEWHERE = CityBoundary(polygons=[[[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]]])


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


def _capture(
    pois: list[Poi], boundary: CityBoundary, switch_ms: int = 1200
) -> ca.CityCapture:
    return ca.CityCapture(
        citta="Roma",
        zona="Colosseo",
        lat=41.0,
        lon=12.0,
        bbox=(41.0, 12.0, 41.5, 12.5),
        switch_ms=switch_ms,
        pois=pois,
        boundary=boundary,
    )


def test_class_exists_true_for_declared_class() -> None:
    assert ca.class_exists(_graph(), "Bank") is True


def test_class_exists_false_for_absent_class() -> None:
    assert ca.class_exists(_graph(), "Nonexistent") is False


def test_class_exists_false_for_generic_fallback() -> None:
    assert ca.class_exists(_graph(), "GenericUrbanPOI") is False


def test_compute_coverage_verbatim_below_derived() -> None:
    pois = [_poi("a", "Bank"), _poi("b", "Prison"), _poi("c", "GenericUrbanPOI")]
    verbatim, derived = ca.compute_coverage(pois, _graph())
    assert derived == 2 / 3
    assert verbatim == 1 / 3


def test_compute_coverage_empty_is_zero() -> None:
    assert ca.compute_coverage([], _graph()) == (0.0, 0.0)


def test_bbox_valid_true_for_valid_bbox() -> None:
    assert ca.bbox_valid((41.0, 12.0, 41.5, 12.5)) is True


def test_bbox_valid_false_for_degenerate_bbox() -> None:
    assert ca.bbox_valid((41.0, 12.0, 41.0, 12.5)) is False


def test_bbox_valid_false_for_degenerate_lon() -> None:
    assert ca.bbox_valid((41.0, 12.0, 41.5, 12.0)) is False


def test_compute_boundary_coverage_all_inside() -> None:
    pois = [_poi("a", "Bank"), _poi("b", "Museum")]
    assert ca.compute_boundary_coverage(pois, _SQUARE) == 1.0


def test_compute_boundary_coverage_all_outside() -> None:
    pois = [_poi("a", "Bank"), _poi("b", "Museum")]
    assert ca.compute_boundary_coverage(pois, _ELSEWHERE) == 0.0


def test_compute_boundary_coverage_empty_is_zero() -> None:
    assert ca.compute_boundary_coverage([], _SQUARE) == 0.0


def test_build_record_sets_pass_flags() -> None:
    rec = ca.build_record(
        _capture([_poi("a", "Bank"), _poi("b", "Museum")], _SQUARE), _graph(), "hash123"
    )
    assert rec.n_poi == 2
    assert rec.coverage_verbatim == 1.0
    assert rec.coverage_derived == 1.0
    assert rec.bbox_valid is True
    assert rec.pois_in_boundary == 1.0
    assert rec.pass_boundary is True
    assert rec.pass_verbatim is True
    assert rec.pass_derived is True
    assert rec.pass_switch is True
    assert rec.ontology_hash == "hash123"


def test_build_record_sets_fail_flags() -> None:
    capture = ca.CityCapture(
        citta="X",
        zona="Y",
        lat=41.0,
        lon=12.0,
        bbox=(41.0, 12.0, 41.5, 12.5),
        switch_ms=6000,
        pois=[_poi("a", "GenericUrbanPOI"), _poi("b", "GenericUrbanPOI")],
        boundary=_ELSEWHERE,
    )
    rec = ca.build_record(capture, _graph(), "h")
    assert rec.coverage_verbatim == 0.0
    assert rec.coverage_derived == 0.0
    assert rec.pass_verbatim is False
    assert rec.pass_derived is False
    assert rec.pass_switch is False
    assert rec.pois_in_boundary == 0.0
    assert rec.pass_boundary is False
    assert rec.bbox_valid is True
