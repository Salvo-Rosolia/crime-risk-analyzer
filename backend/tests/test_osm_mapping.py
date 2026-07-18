"""Test del mapping OSM tag -> classe TERMINUS Crime (#13)."""

from crime_risk_analyzer.sparql_module.osm_mapping import (
    ORDINE_FAMIGLIE,
    OSM_SELECTORS,
    OSM_TO_TERMINUS,
    map_to_terminus,
)


def test_mapping_has_at_least_45_selectors() -> None:
    """Il binding fisso dal paper Minardi et al. 2023 ha >= 45 SELETTORI.

    Conta le ENTRY del dict (selettori OSM ``key=value``), NON le classi TERMINUS
    coperte: piu' selettori mappano sulla stessa classe (es. ``amenity=bank``,
    ``amenity=atm``, ``amenity=bureau_de_change`` -> ``Bank``). Per la copertura
    reale delle classi vedi ``test_mapping_covers_42_of_45_terminus_classes``.
    """
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
    """I binding chiave della spec, sui nomi-classe reali dell'ontologia."""
    assert OSM_TO_TERMINUS["amenity=bank"] == "Bank"
    assert OSM_TO_TERMINUS["tourism=museum"] == "Museum"
    assert OSM_TO_TERMINUS["railway=station"] == "Railway_station"
    assert OSM_TO_TERMINUS["amenity=place_of_worship"] == "Place_of_worship"
    assert OSM_TO_TERMINUS["tourism=attraction"] == "Historical_monument"
    assert OSM_TO_TERMINUS["amenity=police"] == "National_police"
    assert "aeroway=aerodrome" not in OSM_TO_TERMINUS


def test_map_to_terminus_known_tag() -> None:
    """Un tag noto ritorna la classe corrispondente."""
    assert map_to_terminus("amenity=bank") == "Bank"
    assert map_to_terminus("tourism=museum") == "Museum"


def test_map_to_terminus_unknown_tag_falls_back() -> None:
    """Un tag non coperto ricade su GenericUrbanPOI."""
    assert map_to_terminus("amenity=ice_cream") == "GenericUrbanPOI"
    assert map_to_terminus("") == "GenericUrbanPOI"
    assert map_to_terminus("garbage") == "GenericUrbanPOI"


#: Le 45 sottoclassi dirette di tc:System nell'ontologia ENEA TERMINUS-Crime v01.
#: HARDCODED: l'ontologia e' ghost/gitignored, non caricabile in CI. RISINCRONIZZARE
#: A MANO a ogni nuova consegna .owl (estrazione: subClassOf di tc:System via rdflib).
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
    """Guardia anti-drift: ogni valore mappato e' una classe reale di tc:System."""
    assert set(OSM_TO_TERMINUS.values()) <= REAL_TERMINUS_CLASSES


#: Le 3 sottoclassi di tc:System senza alcun selettore OSM che le mappi. Gap NOTO
#: e ACCETTATO (copertura parziale, non un bug): non esiste un tag OSM
#: semanticamente difendibile per queste classi entro il binding fisso #79.
#:  - ``Cathedral`` / ``Church``: OSM non distingue la denominazione religiosa
#:    del culto; tutti gli edifici di culto stanno sotto ``amenity=place_of_worship``,
#:    gia' mappato -> ``Place_of_worship`` (iperonimo). Nessun tag OSM canonico
#:    isola cattedrali/chiese senza euristiche sul nome (fuori scope, city-agnostic).
#:  - ``Fuel_sale``: la vendita di carburante coincide con ``amenity=fuel``, gia'
#:    mappato -> ``Petrol_station`` (la stazione di servizio come POI fisico).
#: La spec ghost (#79) registra esplicitamente "42 delle 45 classi coperte".
UNCOVERED_TERMINUS_CLASSES = frozenset({"Cathedral", "Church", "Fuel_sale"})


def test_mapping_covers_42_of_45_terminus_classes() -> None:
    """Documenta e blinda il gap di copertura: 42 delle 45 classi tc:System.

    Il mapping copre 42 classi reali; 3 restano senza selettore OSM
    (:data:`UNCOVERED_TERMINUS_CLASSES`). L'assert sull'insieme ESATTO delle classi
    non coperte rende il gap self-documenting E fallisce se cambia: aggiungere un
    selettore per una classe scoperta, o rimuovere l'ultimo selettore di una coperta,
    rompe il test e forza una revisione cosciente (e l'aggiornamento della spec #79).
    """
    covered = set(OSM_TO_TERMINUS.values())
    assert len(REAL_TERMINUS_CLASSES) == 45
    assert len(covered) == 42
    assert REAL_TERMINUS_CLASSES - covered == UNCOVERED_TERMINUS_CLASSES


def test_osm_selectors_mirror_mapping_keys() -> None:
    """OSM_SELECTORS e' esattamente l'elenco delle chiavi del dict (single source)."""
    assert OSM_SELECTORS == tuple(OSM_TO_TERMINUS)


def test_ordine_famiglie_matches_mapping_families() -> None:
    """ORDINE_FAMIGLIE copre esattamente le famiglie di chiavi presenti nel dict."""
    assert set(ORDINE_FAMIGLIE) == {k.split("=")[0] for k in OSM_TO_TERMINUS}


def test_spec_bindings_present_real_attraction() -> None:
    """tourism=attraction -> Historical_monument (non Archaeological_site)."""
    assert OSM_TO_TERMINUS["tourism=attraction"] == "Historical_monument"
    assert OSM_TO_TERMINUS["historic=archaeological_site"] == "Archaeological_site"
