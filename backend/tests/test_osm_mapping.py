"""Test del mapping OSM tag -> classe TERMINUS Crime (#13)."""

from crime_risk_analyzer.sparql_module.osm_mapping import (
    OSM_TO_TERMINUS,
    map_to_terminus,
)


def test_mapping_has_at_least_45_entries() -> None:
    """Il binding fisso dal paper Minardi et al. 2023 ha >= 45 entry."""
    assert len(OSM_TO_TERMINUS) >= 45


def test_mapping_covers_required_categories() -> None:
    """Sono coperte almeno le categorie amenity/tourism/railway/shop."""
    prefixes = {tag.split("=", 1)[0] for tag in OSM_TO_TERMINUS}
    assert {"amenity", "tourism", "railway", "shop"} <= prefixes


def test_mapping_values_are_bare_class_names() -> None:
    """I valori sono nomi-classe bare (nessun prefisso tc:, niente vuoti)."""
    for terminus_class in OSM_TO_TERMINUS.values():
        assert terminus_class
        assert not terminus_class.startswith("tc:")
        assert ":" not in terminus_class


def test_spec_bindings_present() -> None:
    """I binding esplicitamente elencati nella spec sparql.md sono rispettati."""
    assert OSM_TO_TERMINUS["amenity=bank"] == "Bank"
    assert OSM_TO_TERMINUS["tourism=museum"] == "Museum"
    assert OSM_TO_TERMINUS["railway=station"] == "RailwayStation"
    assert OSM_TO_TERMINUS["amenity=place_of_worship"] == "ReligiousSite"
    assert OSM_TO_TERMINUS["tourism=attraction"] == "HeritageAttractionSite"
    assert OSM_TO_TERMINUS["aeroway=aerodrome"] == "Airport"


def test_map_to_terminus_known_tag() -> None:
    """Un tag noto ritorna la classe corrispondente."""
    assert map_to_terminus("amenity=bank") == "Bank"
    assert map_to_terminus("tourism=museum") == "Museum"


def test_map_to_terminus_unknown_tag_falls_back() -> None:
    """Un tag non coperto ricade su GenericUrbanPOI."""
    assert map_to_terminus("amenity=ice_cream") == "GenericUrbanPOI"
    assert map_to_terminus("") == "GenericUrbanPOI"
    assert map_to_terminus("garbage") == "GenericUrbanPOI"
