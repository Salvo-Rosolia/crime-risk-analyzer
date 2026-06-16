"""Mapping OSM tag -> classe TERMINUS Crime (#13).

Fonte autoritativa unica del binding ``OSM tag -> classe TERMINUS`` (citata da
``ontologia/city-agnostic.md`` e ``backend/sparql.md``). Il binding e' fisso e
universale: deriva dalle classi di POI dell'ontologia TERMINUS Crime (Minardi
et al., 2023) e non va esteso per citta' specifiche (``amenity=bank`` e' uguale
in qualsiasi citta'). I valori sono **nomi-classe bare** (es. ``"Bank"``); il
prefisso ``tc:`` viene applicato altrove, nei template SPARQL.

I sei binding elencati esplicitamente nella spec ``sparql.md`` sono riprodotti
fedelmente; i restanti completano in modo coerente le categorie OSM piu' comuni
(``amenity``/``tourism``/``railway``/``shop``/``aeroway``) mappandole alle classi
TERMINUS piu' vicine. POI senza corrispondenza ricadono su ``GenericUrbanPOI``.
"""

from __future__ import annotations

#: Classe di fallback per i tag OSM non coperti (confidence degradata a valle).
GENERIC_FALLBACK = "GenericUrbanPOI"

#: Binding fisso OSM tag -> classe TERMINUS bare. Single source of truth.
OSM_TO_TERMINUS: dict[str, str] = {
    # --- amenity (servizi e funzioni urbane) ---
    "amenity=bank": "Bank",  # spec sparql.md
    "amenity=atm": "Bank",
    "amenity=bureau_de_change": "Bank",
    "amenity=hospital": "Hospital",
    "amenity=clinic": "Hospital",
    "amenity=pharmacy": "Pharmacy",
    "amenity=police": "PoliceStation",
    "amenity=fire_station": "FireStation",
    "amenity=townhall": "GovernmentBuilding",
    "amenity=courthouse": "GovernmentBuilding",
    "amenity=embassy": "Embassy",
    "amenity=prison": "Prison",
    "amenity=school": "School",
    "amenity=college": "School",
    "amenity=university": "University",
    "amenity=kindergarten": "School",
    "amenity=library": "Library",
    "amenity=place_of_worship": "ReligiousSite",  # spec sparql.md (Vaticano)
    "amenity=marketplace": "Market",
    "amenity=fuel": "FuelStation",
    "amenity=parking": "ParkingFacility",
    "amenity=bus_station": "BusStation",
    "amenity=nightclub": "Nightclub",
    "amenity=bar": "Bar",
    "amenity=pub": "Bar",
    "amenity=restaurant": "Restaurant",
    "amenity=cafe": "Restaurant",
    "amenity=cinema": "EntertainmentVenue",
    "amenity=theatre": "EntertainmentVenue",
    "amenity=casino": "Casino",
    # --- tourism (attrazioni e ricettivo) ---
    "tourism=museum": "Museum",  # spec sparql.md
    "tourism=attraction": "HeritageAttractionSite",  # spec sparql.md (Colosseo)
    "tourism=gallery": "Museum",
    "tourism=hotel": "Hotel",
    "tourism=hostel": "Hotel",
    "tourism=motel": "Hotel",
    "tourism=guest_house": "Hotel",
    "tourism=viewpoint": "HeritageAttractionSite",
    "tourism=theme_park": "EntertainmentVenue",
    "tourism=zoo": "EntertainmentVenue",
    # --- railway / public transport ---
    "railway=station": "RailwayStation",  # spec sparql.md
    "railway=halt": "RailwayStation",
    "railway=subway_entrance": "MetroStation",
    "railway=tram_stop": "TramStop",
    # --- aeroway ---
    "aeroway=aerodrome": "Airport",  # spec sparql.md
    "aeroway=terminal": "Airport",
    # --- shop (commercio) ---
    "shop=mall": "ShoppingMall",
    "shop=supermarket": "Supermarket",
    "shop=department_store": "ShoppingMall",
    "shop=jewelry": "JewelryStore",
    "shop=convenience": "Supermarket",
}


def map_to_terminus(osm_tag: str) -> str:
    """Mappa un tag OSM ``chiave=valore`` a una classe TERMINUS bare.

    Ritorna il nome di classe corrispondente, oppure :data:`GENERIC_FALLBACK`
    (``"GenericUrbanPOI"``) per i tag non coperti dal binding. Il prefisso
    ``tc:`` va applicato a valle, nei template SPARQL.
    """
    return OSM_TO_TERMINUS.get(osm_tag, GENERIC_FALLBACK)
