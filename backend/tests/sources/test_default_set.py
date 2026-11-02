"""Il set di fonti di default raggruppa le costanti TERMINUS+ISTAT esistenti (#411)."""

from crime_risk_analyzer.istat.catalog import BREAK_ITEMS_2016
from crime_risk_analyzer.istat.mapping import HAZARD_MAPPING
from crime_risk_analyzer.ontology import get_ontology
from crime_risk_analyzer.ontology_namespaces import TERMINUS
from crime_risk_analyzer.sources.context import default_set
from crime_risk_analyzer.sources.model import TERMINUS_CONFIG, OsmBinding
from crime_risk_analyzer.sources.vocabulary import TERMINUS_VOCABULARY
from crime_risk_analyzer.sparql_module.osm_mapping import (
    FAMILY_ORDER,
    GENERIC_FALLBACK,
    OSM_SELECTORS,
    OSM_TO_TERMINUS,
    YIELDING_SELECTORS,
)
from crime_risk_analyzer.sparql_module.query_executor import (
    _CRITICAL_EVENT,  # pyright: ignore[reportPrivateUsage]
    _HAZARD,  # pyright: ignore[reportPrivateUsage]
    _PERFORMER,  # pyright: ignore[reportPrivateUsage]
    _VULNERABILITY_PROPS,  # pyright: ignore[reportPrivateUsage]
    get_executor,
)


def test_default_set_identita() -> None:
    s = default_set()
    assert s.kind == "default"
    assert s.id == "default"
    assert s.labels is None


def test_default_set_e_cached() -> None:
    assert default_set() is default_set()


def test_default_set_riusa_grafo_ed_executor_esistenti() -> None:
    s = default_set()
    assert s.graph is get_ontology()
    assert s.executor is get_executor()


def test_default_set_config_ontologia_terminus() -> None:
    # Importa i privati di query_executor (oggi unica sorgente dei nomi di
    # proprieta'): il test fallisce se TERMINUS_CONFIG diverge da quei valori.
    assert default_set().ontology == TERMINUS_CONFIG
    assert TERMINUS_CONFIG.hazard == _HAZARD
    assert TERMINUS_CONFIG.critical_event == _CRITICAL_EVENT
    assert TERMINUS_CONFIG.performer == _PERFORMER
    assert TERMINUS_CONFIG.vulnerability == _VULNERABILITY_PROPS
    assert TERMINUS_CONFIG.namespace == str(TERMINUS)


def test_terminus_vocabulary_coincide_con_costanti_storiche() -> None:
    # Le costanti private di query_executor sono il riferimento storico: il
    # default effettivo dell'executor e' TERMINUS_VOCABULARY, che non deve driftare.
    assert TERMINUS_VOCABULARY.hazard == _HAZARD
    assert TERMINUS_VOCABULARY.critical_event == _CRITICAL_EVENT
    assert TERMINUS_VOCABULARY.performer == _PERFORMER
    assert TERMINUS_VOCABULARY.vulnerability == _VULNERABILITY_PROPS


def test_default_set_osm() -> None:
    osm = default_set().osm
    assert dict(osm.osm_to_class) == OSM_TO_TERMINUS
    assert osm.family_order == FAMILY_ORDER
    assert osm.selectors == OSM_SELECTORS
    assert dict(osm.yielding_selectors) == YIELDING_SELECTORS
    assert osm.map("amenity=bank") == "Bank"
    assert osm.map("amenity=boh") == GENERIC_FALLBACK


def test_osm_binding_proprio() -> None:
    osm = OsmBinding(
        osm_to_class={"amenity=cafe": "Bar"},
        family_order=("amenity",),
        yielding_selectors={},
    )
    assert osm.selectors == ("amenity=cafe",)
    assert osm.map("amenity=cafe") == "Bar"
    assert osm.map("amenity=bank") == GENERIC_FALLBACK


def test_default_set_istat() -> None:
    istat = default_set().istat
    assert istat.mappatura is HAZARD_MAPPING
    assert istat.voci_rottura == BREAK_ITEMS_2016
    assert istat.dati is not None
    assert istat.versione == istat.dati.versione
