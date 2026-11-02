"""The :class:`SourceSet` object: everything that depends on the sources in use (#411).

It groups what today lives in module constants or single caches (graph, executor,
OSM binding, ISTAT data, hazard -> item mapping, labels), so that a
request can work on a set different from the default. The set is an
immutable and shareable value; the active one is read from
:mod:`crime_risk_analyzer.sources.context`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from rdflib import Graph

from crime_risk_analyzer.istat.data import IstatData
from crime_risk_analyzer.istat.mapping import HazardMapping
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
    """Namespace and names of the properties with which the ontology links POIs and
    risks.

    ``namespace`` ends with ``#`` or ``/``; the other entries are local names.
    ``vulnerability`` admits several properties (TERMINUS uses two).
    """

    namespace: str
    hazard: str
    critical_event: str
    performer: str
    vulnerability: tuple[str, ...]


#: Current values of ``query_executor.py``.
TERMINUS_CONFIG = OntologyConfig(
    namespace=f"{TERMINUS_IRI}#",
    hazard="havingHazard",
    critical_event="havingCriticalEvent",
    performer="havingPerformer",
    vulnerability=("isVulnerableTo", "havingVulnerability"),
)


@dataclass(frozen=True)
class OsmBinding:
    """OSM ``key=value`` binding -> ontology class name."""

    osm_to_class: Mapping[str, str]
    family_order: tuple[str, ...]
    yielding_selectors: Mapping[str, str]

    @property
    def selectors(self) -> tuple[str, ...]:
        """Selectors to query on Overpass (the keys of the binding)."""
        return tuple(self.osm_to_class)

    def map(self, osm_tag: str) -> str:
        """Class of the tag, or ``GENERIC_FALLBACK`` if not covered."""
        return self.osm_to_class.get(osm_tag, GENERIC_FALLBACK)


@dataclass(frozen=True)
class IstatSource:
    """Statistical data of the set and hazard -> item mapping table.

    ``dati`` is ``None`` if not available (the grounding goes on without).
    """

    dati: IstatData | None
    mappatura: Mapping[str, HazardMapping]
    voci_rottura: frozenset[str]
    versione: str | None


@dataclass(frozen=True, eq=False)
class SourceSet:
    """Sources active for a request. Equality by identity (it contains a Graph).

    ``id`` identifies the set in the cache keys (``"default"`` for the
    internal one). ``labels`` maps class name -> (IT label, EN label);
    ``None`` = the TERMINUS JSON is used.
    """

    id: str
    kind: SourceKind
    graph: Graph
    ontology: OntologyConfig
    executor: RiskQueryExecutor
    osm: OsmBinding
    istat: IstatSource
    labels: Mapping[str, tuple[str, str]] | None = None
