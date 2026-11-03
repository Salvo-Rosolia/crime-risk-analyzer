"""Tests for the OSM tag -> TERMINUS Crime class mapping (#13)."""

from crime_risk_analyzer.sparql_module.osm_mapping import (
    FAMILY_ORDER,
    OSM_SELECTORS,
    OSM_TO_TERMINUS,
    YIELDING_SELECTORS,
    map_to_terminus,
)


def test_mapping_has_at_least_45_selectors() -> None:
    """The fixed binding from the Minardi et al. 2023 paper has >= 45 SELECTORS.

    Counts the dict ENTRIES (OSM ``key=value`` selectors), NOT the TERMINUS
    classes covered: several selectors map to the same class (e.g.
    ``amenity=bank``, ``amenity=atm``, ``amenity=bureau_de_change`` -> ``Bank``).
    For the real class coverage see
    ``test_mapping_covers_42_of_45_terminus_classes``.
    """
    assert len(OSM_TO_TERMINUS) >= 45


def test_mapping_covers_required_categories() -> None:
    """At least the amenity/tourism/railway/shop categories are covered."""
    prefixes = {tag.split("=", 1)[0] for tag in OSM_TO_TERMINUS}
    assert {"amenity", "tourism", "railway", "shop"} <= prefixes


def test_mapping_values_are_bare_class_names() -> None:
    """Values are bare class names (no tc: prefix, none empty)."""
    for ontology_class in OSM_TO_TERMINUS.values():
        assert ontology_class
        assert not ontology_class.startswith("tc:")
        assert ":" not in ontology_class


def test_spec_bindings_present() -> None:
    """The key bindings of the spec, on the real class names of the ontology."""
    assert OSM_TO_TERMINUS["amenity=bank"] == "Bank"
    assert OSM_TO_TERMINUS["tourism=museum"] == "Museum"
    assert OSM_TO_TERMINUS["railway=station"] == "Railway_station"
    assert OSM_TO_TERMINUS["amenity=place_of_worship"] == "Place_of_worship"
    assert OSM_TO_TERMINUS["tourism=attraction"] == "Historical_monument"
    assert OSM_TO_TERMINUS["amenity=police"] == "National_police"
    assert "aeroway=aerodrome" not in OSM_TO_TERMINUS


def test_map_to_terminus_known_tag() -> None:
    """A known tag returns the corresponding class."""
    assert map_to_terminus("amenity=bank") == "Bank"
    assert map_to_terminus("tourism=museum") == "Museum"


def test_map_to_terminus_unknown_tag_falls_back() -> None:
    """An uncovered tag falls back to GenericUrbanPOI."""
    assert map_to_terminus("amenity=ice_cream") == "GenericUrbanPOI"
    assert map_to_terminus("") == "GenericUrbanPOI"
    assert map_to_terminus("garbage") == "GenericUrbanPOI"


#: The 45 direct subclasses of tc:System in the ENEA TERMINUS-Crime v01 ontology.
#: HARDCODED: the ontology is ghost/gitignored, not loadable in CI. RESYNC BY
#: HAND on every new .owl delivery (extraction: subClassOf of tc:System via rdflib).
REAL_TERMINUS_CLASSES = frozenset(
    {
        "Archaeological_site",
        "Bank",
        "Beach_resort",
        "Bus_stops",
        "Cathedral",
        "Church",
        "Cinema",
        "Drinking_water_system",
        "Electric_generator",
        "Electrical_substation",
        "Fire_station",
        "Fuel_sale",
        "Gas_cylinder_dealer",
        "Government_office",
        "Grandstand",
        "Helipad",
        "Highways_and_junctions",
        "Historical_monument",
        "Hospital",
        "Jewellery",
        "Kindergarten",
        "Lighthouse",
        "Marketplace",
        "Museum",
        "National_police",
        "Petrol_station",
        "Pharmacy",
        "Pier",
        "Pipeline",
        "Place_of_worship",
        "Playground",
        "Post_office",
        "Prison",
        "Public_building",
        "Pyrotechnic_material_for_sale",
        "Railway_station",
        "School",
        "Shopping_center",
        "Silo",
        "Storage_tank",
        "Tobacco_store",
        "Town_hall",
        "Transmission_line",
        "Warehouse",
        "Wooded_area",
    }
)


def test_all_values_are_real_terminus_classes() -> None:
    """Anti-drift guard: every mapped value is a real tc:System class."""
    assert set(OSM_TO_TERMINUS.values()) <= REAL_TERMINUS_CLASSES


#: The 3 tc:System subclasses with no OSM selector mapping them. KNOWN and
#: ACCEPTED gap (partial coverage, not a bug): there is no semantically
#: defensible OSM tag for these classes within the fixed binding #79.
#:  - ``Cathedral`` / ``Church``: OSM does not distinguish the religious
#:    denomination of the place of worship; all places of worship sit under
#:    ``amenity=place_of_worship``, already mapped -> ``Place_of_worship``
#:    (hypernym). No canonical OSM tag isolates cathedrals/churches without
#:    heuristics on the name (out of scope, city-agnostic).
#:  - ``Fuel_sale``: fuel sale coincides with ``amenity=fuel``, already mapped
#:    -> ``Petrol_station`` (the service station as a physical POI).
#: The ghost spec (#79) explicitly records "42 of 45 classes covered".
UNCOVERED_TERMINUS_CLASSES = frozenset({"Cathedral", "Church", "Fuel_sale"})


def test_mapping_covers_42_of_45_terminus_classes() -> None:
    """Documents and pins the coverage gap: 42 of the 45 tc:System classes.

    The mapping covers 42 real classes; 3 remain without an OSM selector
    (:data:`UNCOVERED_TERMINUS_CLASSES`). The assert on the EXACT set of
    uncovered classes makes the gap self-documenting AND fails if it changes:
    adding a selector for an uncovered class, or removing the last selector of a
    covered one, breaks the test and forces a conscious review (and the update
    of spec #79).
    """
    covered = set(OSM_TO_TERMINUS.values())
    assert len(REAL_TERMINUS_CLASSES) == 45
    assert len(covered) == 42
    assert REAL_TERMINUS_CLASSES - covered == UNCOVERED_TERMINUS_CLASSES


def test_osm_selectors_mirror_mapping_keys() -> None:
    """OSM_SELECTORS is exactly the list of the dict keys (single source)."""
    assert OSM_SELECTORS == tuple(OSM_TO_TERMINUS)


def test_family_order_matches_mapping_families() -> None:
    """FAMILY_ORDER covers exactly the key families present in the dict."""
    assert set(FAMILY_ORDER) == {k.split("=")[0] for k in OSM_TO_TERMINUS}


def test_spec_bindings_present_real_attraction() -> None:
    """tourism=attraction -> Historical_monument (not Archaeological_site)."""
    assert OSM_TO_TERMINUS["tourism=attraction"] == "Historical_monument"
    assert OSM_TO_TERMINUS["historic=archaeological_site"] == "Archaeological_site"


def test_yielding_selectors_yield_to_a_later_mapped_family() -> None:
    """Every generic selector is in the binding and yields to a mapping family
    that comes AFTER its own in FAMILY_ORDER (otherwise it would already win by
    order)."""
    for selector, family in YIELDING_SELECTORS.items():
        assert selector in OSM_TO_TERMINUS
        own = selector.split("=")[0]
        assert FAMILY_ORDER.index(family) > FAMILY_ORDER.index(own)


def test_tourism_attraction_yields_to_historic() -> None:
    """#373: on the same element a mapped ``historic=*`` wins over
    ``tourism=attraction`` (Colosseo -> Archaeological_site)."""
    assert YIELDING_SELECTORS == {"tourism=attraction": "historic"}
