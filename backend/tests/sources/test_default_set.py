"""Il set di fonti di default raggruppa le costanti TERMINUS+ISTAT esistenti (#411)."""

from crime_risk_analyzer.istat.catalogo import VOCI_ROTTURA_2016
from crime_risk_analyzer.istat.mappatura import MAPPATURA
from crime_risk_analyzer.ontology import get_ontology
from crime_risk_analyzer.ontology_namespaces import TERMINUS
from crime_risk_analyzer.sources.context import default_set
from crime_risk_analyzer.sources.model import TERMINUS_CONFIG, OsmBinding
from crime_risk_analyzer.sparql_module.osm_mapping import (
    GENERIC_FALLBACK,
    ORDINE_FAMIGLIE,
    OSM_SELECTORS,
    OSM_TO_TERMINUS,
    SELETTORI_CEDEVOLI,
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


def test_default_set_osm() -> None:
    osm = default_set().osm
    assert dict(osm.osm_to_class) == OSM_TO_TERMINUS
    assert osm.ordine_famiglie == ORDINE_FAMIGLIE
    assert osm.selectors == OSM_SELECTORS
    assert dict(osm.selettori_cedevoli) == SELETTORI_CEDEVOLI
    assert osm.map("amenity=bank") == "Bank"
    assert osm.map("amenity=boh") == GENERIC_FALLBACK


def test_osm_binding_proprio() -> None:
    osm = OsmBinding(
        osm_to_class={"amenity=cafe": "Bar"},
        ordine_famiglie=("amenity",),
        selettori_cedevoli={},
    )
    assert osm.selectors == ("amenity=cafe",)
    assert osm.map("amenity=cafe") == "Bar"
    assert osm.map("amenity=bank") == GENERIC_FALLBACK


def test_default_set_istat() -> None:
    istat = default_set().istat
    assert istat.mappatura is MAPPATURA
    assert istat.voci_rottura == VOCI_ROTTURA_2016
    assert istat.dati is not None
    assert istat.versione == istat.dati.versione
