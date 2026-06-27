"""Mapping OSM tag -> classe TERMINUS Crime (#13, ri-derivato #79).

Fonte autoritativa unica del binding ``OSM key=value -> classe TERMINUS`` (citata da
``docs/specs/tree/ontologia/city-agnostic.md`` e ``.../backend/sparql.md``). I valori
sono **nomi-classe bare reali** in ``Underscore_Case`` (es. ``"Bank"``,
``"National_police"``), tutti tra le 45 sottoclassi dirette di ``tc:System``
dell'ontologia ENEA TERMINUS-Crime v01; il prefisso ``tc:`` e' applicato a valle.

Il binding e' fisso e city-agnostico (``amenity=bank`` e' uguale ovunque). Si mappa
solo dove il match e' semanticamente difendibile (classe iperonimo/equivalente del
POI, hazard core applicabili); i tag senza match fedele NON compaiono qui e ricadono
su ``GENERIC_FALLBACK`` -> profilo rischi vuoto (POI "non coperto"), confidence
degradata a valle.

Le chiavi del dict SONO i selettori interrogati su Overpass (:data:`OSM_SELECTORS`):
nessuna divergenza possibile tra "cosa recuperiamo" e "cosa classifichiamo".
"""

from __future__ import annotations

#: Classe di fallback per i tag OSM non coperti (non e' una classe reale: a valle
#: ``RiskQueryExecutor.profile`` ritorna liste vuote senza errore).
GENERIC_FALLBACK = "GenericUrbanPOI"

#: Binding fisso OSM ``key=value`` -> classe TERMINUS reale bare.
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

#: Lista canonica dei selettori OSM ``key=value`` da interrogare su Overpass.
#: Derivata DAL dict: non duplicarla. (overpass_client la usa come default.)
OSM_SELECTORS: tuple[str, ...] = tuple(OSM_TO_TERMINUS)

#: Ordine di priorita' delle famiglie di chiavi OSM per ``_extract_osm_tag``: a
#: parita' di POI multi-tag, vince la prima famiglia (funzione umana prima della
#: struttura fisica). Invariante: copre esattamente le famiglie presenti nel dict.
ORDINE_FAMIGLIE: tuple[str, ...] = (
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


def map_to_terminus(osm_tag: str) -> str:
    """Mappa un selettore OSM ``chiave=valore`` a una classe TERMINUS bare reale.

    Ritorna il nome-classe corrispondente, oppure :data:`GENERIC_FALLBACK`
    (``"GenericUrbanPOI"``) per i tag non coperti. Il prefisso ``tc:`` va applicato
    a valle, nei template SPARQL.
    """
    return OSM_TO_TERMINUS.get(osm_tag, GENERIC_FALLBACK)
