"""Oggetto :class:`SourceSet`: tutto cio' che dipende dalle fonti in uso (#411).

Raggruppa quanto oggi vive in costanti di modulo o cache uniche (grafo, executor,
binding OSM, dati ISTAT, mappatura hazard -> voce, etichette), cosi' che una
richiesta possa lavorare su un set diverso dal default. Il set e' un valore
immutabile e condivisibile; quello attivo si legge da
:mod:`crime_risk_analyzer.sources.context`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from rdflib import Graph

from crime_risk_analyzer.istat.dati import DatiIstat
from crime_risk_analyzer.istat.mappatura import Mappatura
from crime_risk_analyzer.ontology_namespaces import TERMINUS_IRI
from crime_risk_analyzer.sparql_module.osm_mapping import GENERIC_FALLBACK
from crime_risk_analyzer.sparql_module.query_executor import RiskQueryExecutor

__all__ = [
    "TERMINUS_CONFIG",
    "IstatSource",
    "OntologyConfig",
    "OsmBinding",
    "SourceKind",
    "SourceSet",
]

SourceKind = Literal["default", "example", "custom"]


@dataclass(frozen=True)
class OntologyConfig:
    """Namespace e nomi delle proprieta' con cui l'ontologia lega POI e rischi.

    ``namespace`` termina con ``#`` o ``/``; le altre voci sono nomi locali.
    ``vulnerability`` ammette piu' proprieta' (TERMINUS ne usa due).
    """

    namespace: str
    hazard: str
    critical_event: str
    performer: str
    vulnerability: tuple[str, ...]


#: Valori attuali di ``query_executor.py``.
TERMINUS_CONFIG = OntologyConfig(
    namespace=f"{TERMINUS_IRI}#",
    hazard="havingHazard",
    critical_event="havingCriticalEvent",
    performer="havingPerformer",
    vulnerability=("isVulnerableTo", "havingVulnerability"),
)


@dataclass(frozen=True)
class OsmBinding:
    """Binding ``chiave=valore`` OSM -> nome classe dell'ontologia."""

    osm_to_class: Mapping[str, str]
    ordine_famiglie: tuple[str, ...]
    selettori_cedevoli: Mapping[str, str]

    @property
    def selectors(self) -> tuple[str, ...]:
        """Selettori da interrogare su Overpass (le chiavi del binding)."""
        return tuple(self.osm_to_class)

    def map(self, osm_tag: str) -> str:
        """Classe del tag, o ``GENERIC_FALLBACK`` se non coperto."""
        return self.osm_to_class.get(osm_tag, GENERIC_FALLBACK)


@dataclass(frozen=True)
class IstatSource:
    """Dati statistici del set e tabella di mappatura hazard -> voce.

    ``dati`` e' ``None`` se non disponibili (il grounding prosegue senza).
    """

    dati: DatiIstat | None
    mappatura: Mapping[str, Mappatura]
    voci_rottura: frozenset[str]
    versione: str | None


@dataclass(frozen=True, eq=False)
class SourceSet:
    """Fonti attive per una richiesta. Uguaglianza per identita' (contiene un Graph).

    ``id`` identifica il set nelle chiavi di cache (``"default"`` per quello
    interno). ``labels`` mappa nome classe -> (etichetta IT, etichetta EN);
    ``None`` = si usa il JSON TERMINUS.
    """

    id: str
    kind: SourceKind
    graph: Graph
    ontology: OntologyConfig
    executor: RiskQueryExecutor
    osm: OsmBinding
    istat: IstatSource
    labels: Mapping[str, tuple[str, str]] | None = None
