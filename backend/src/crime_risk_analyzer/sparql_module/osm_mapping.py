"""Mapping OSM tag -> TERMINUS Crime class (#13, re-derived #79).

Single authoritative source of the binding ``OSM key=value -> TERMINUS class`` (cited
by ``docs/specs/tree/ontologia/city-agnostic.md`` and ``.../backend/sparql.md``). The
values are **real bare class names** in ``Underscore_Case`` (e.g. ``"Bank"``,
``"National_police"``), all among the 45 direct subclasses of ``tc:System``
of the ENEA TERMINUS-Crime v01 ontology; the ``tc:`` prefix is applied downstream.

The binding is fixed and city-agnostic (``amenity=bank`` is the same everywhere). It
maps only where the match is semantically defensible (hypernym/equivalent class of the
POI, applicable core hazards); tags without a faithful match do NOT appear here and fall
back to ``GENERIC_FALLBACK`` -> empty risk profile ("uncovered" POI), confidence
degraded downstream.

The keys of the dict ARE the selectors queried on Overpass (:data:`OSM_SELECTORS`):
no divergence is possible between "what we retrieve" and "what we classify".
"""

from __future__ import annotations

#: Fallback class for uncovered OSM tags (it is not a real class: downstream
#: ``RiskQueryExecutor.profile`` returns empty lists without error).
GENERIC_FALLBACK = "GenericUrbanPOI"

#: Fixed binding OSM ``key=value`` -> real bare TERMINUS class.
#: Single source of truth.
OSM_TO_TERMINUS: dict[str, str] = {
    # --- amenity ---
    "amenity=bank": "Bank",
    "amenity=atm": "Bank",
    "amenity=bureau_de_change": "Bank",
    "amenity=hospital": "Hospital",
    "amenity=clinic": "Hospital",
    "amenity=pharmacy": "Pharmacy",
    "amenity=police": "National_police",
    "amenity=fire_station": "Fire_station",
    "amenity=townhall": "Town_hall",
    "amenity=courthouse": "Government_office",
    "amenity=embassy": "Government_office",
    "amenity=prison": "Prison",
    "amenity=school": "School",
    "amenity=college": "School",
    "amenity=kindergarten": "Kindergarten",
    "amenity=library": "Public_building",
    "amenity=community_centre": "Public_building",
    "amenity=place_of_worship": "Place_of_worship",
    "amenity=marketplace": "Marketplace",
    "amenity=fuel": "Petrol_station",
    "amenity=bus_station": "Bus_stops",
    "amenity=post_office": "Post_office",
    "amenity=cinema": "Cinema",
    # --- shop ---
    "shop=mall": "Shopping_center",
    "shop=department_store": "Shopping_center",
    "shop=supermarket": "Shopping_center",
    "shop=jewelry": "Jewellery",
    "shop=tobacco": "Tobacco_store",
    "shop=gas": "Gas_cylinder_dealer",
    "shop=fireworks": "Pyrotechnic_material_for_sale",
    # --- tourism ---
    "tourism=museum": "Museum",
    "tourism=gallery": "Museum",
    "tourism=attraction": "Historical_monument",
    # --- historic ---
    "historic=archaeological_site": "Archaeological_site",
    "historic=monument": "Historical_monument",
    "historic=memorial": "Historical_monument",
    "historic=castle": "Historical_monument",
    "historic=fort": "Historical_monument",
    "historic=ruins": "Historical_monument",
    # --- leisure ---
    "leisure=playground": "Playground",
    "leisure=beach_resort": "Beach_resort",
    "leisure=grandstand": "Grandstand",
    # --- aeroway ---
    "aeroway=helipad": "Helipad",
    "aeroway=heliport": "Helipad",
    # --- railway ---
    "railway=station": "Railway_station",
    "railway=halt": "Railway_station",
    "railway=subway_entrance": "Railway_station",
    # --- man_made ---
    "man_made=pier": "Pier",
    "man_made=lighthouse": "Lighthouse",
    "man_made=pipeline": "Pipeline",
    "man_made=silo": "Silo",
    "man_made=storage_tank": "Storage_tank",
    "man_made=tank": "Storage_tank",
    "man_made=water_works": "Drinking_water_system",
    "man_made=water_tower": "Drinking_water_system",
    # --- power ---
    "power=substation": "Electrical_substation",
    "power=generator": "Electric_generator",
    "power=line": "Transmission_line",
    "power=tower": "Transmission_line",
    # --- building ---
    "building=warehouse": "Warehouse",
    # --- office ---
    "office=government": "Government_office",
    # --- highway ---
    "highway=bus_stop": "Bus_stops",
    "highway=motorway_junction": "Highways_and_junctions",
    # --- natural / landuse ---
    "natural=wood": "Wooded_area",
    "landuse=forest": "Wooded_area",
}

#: Canonical list of the OSM ``key=value`` selectors to query on Overpass.
#: Derived FROM the dict: do not duplicate it. (overpass_client uses it as default.)
OSM_SELECTORS: tuple[str, ...] = tuple(OSM_TO_TERMINUS)

#: Priority order of the OSM key families for ``_extract_osm_tag``: for a
#: multi-tag POI, the first family wins (human function before
#: physical structure). Invariant: it covers exactly the families present in the dict.
FAMILY_ORDER: tuple[str, ...] = (
    "amenity",
    "shop",
    "tourism",
    "historic",
    "leisure",
    "aeroway",
    "railway",
    "man_made",
    "power",
    "building",
    "office",
    "highway",
    "natural",
    "landuse",
)

#: Generic selectors that, on the same element, yield to a mapped tag
#: of a later family in :data:`FAMILY_ORDER` (#373).
#: ``tourism=attraction`` only says that the place is visited, while ``historic=*``
#: says what it is: the Colosseo carries both and must be classified
#: ``Archaeological_site``, not ``Historical_monument``. It touches only this pair:
#: ``tourism=museum``/``gallery`` stay ahead of ``historic``.
YIELDING_SELECTORS: dict[str, str] = {"tourism=attraction": "historic"}


def map_to_terminus(osm_tag: str) -> str:
    """Maps an OSM selector ``key=value`` to a real bare TERMINUS class.

    Returns the corresponding class name, or :data:`GENERIC_FALLBACK`
    (``"GenericUrbanPOI"``) for uncovered tags. The ``tc:`` prefix must be applied
    downstream, in the SPARQL templates.
    """
    return OSM_TO_TERMINUS.get(osm_tag, GENERIC_FALLBACK)
