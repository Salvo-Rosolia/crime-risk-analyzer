"""SPARQL executor on the OWL restriction pattern of TERMINUS Crime (#76).

Given a POI class (e.g. ``Bank``), it extracts from the ontology graph the associated
risks — hazard, critical event, vulnerability, stakeholder — by querying
the **OWL restriction** pattern with which TERMINUS encodes the associations:

    tc:Bank rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty tc:havingHazard ; owl:someValuesFrom tc:Bank_robbery ] .

The risks are NOT direct triples ``?poi tc:havingHazard ?h``: a query on
direct triples returns 0 results. The associations live in the
``owl:Restriction`` nodes attached via ``rdfs:subClassOf``, and a class also inherits
the restrictions declared on the superclasses (``rdfs:subClassOf*`` closure).
**No reasoner**: the ontology is a pure TBox (0 individuals) and rdflib's
``subClassOf*`` closure is enough.

Architecture (build-once, query-many — consistent with "the graph is loaded once
in the lifespan, not per request"):

* :class:`RiskQueryExecutor` indexes **once** all the restrictions of the
  graph with a **parametrised** SPARQL query (:func:`prepareQuery`): the POI
  class never enters by string concatenation. The indexing is the only
  expensive part (it enumerates the restriction nodes) and is independent of the POI, so
  it must be done at startup, within the graph loading budget.
* :meth:`RiskQueryExecutor.profile` answers for each POI with a native
  ``subClassOf*`` closure (``rdflib.Graph.transitive_objects``, C level) plus a
  selection on the index: a few tenths of a millisecond, well under the 100
  ms per query budget of the done criterion (on the real graph; on the fixture it is
  trivial).

Query shape and output schema: ``docs/specs/tree/backend/sparql.md``.
Citation layer: each filler produces a linear one-hop ``sparql_path``
(``Class → property → entity``, Unicode glyph U+2192 as per the canonical schema)
consumed by the grounding for the ``[ONTOLOGIA]`` tag.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDFS
from rdflib.plugins.sparql import prepareQuery

from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.ontology import get_ontology
from crime_risk_analyzer.sources.vocabulary import (
    TERMINUS_VOCABULARY,
    OntologyVocabulary,
)

__all__ = [
    "InvalidIriError",
    "PoiRiskProfile",
    "RiskQueryExecutor",
    "get_executor",
]

logger = logging.getLogger(__name__)


#: Historical TERMINUS names of the risk properties. The executor's default is
#: :data:`TERMINUS_VOCABULARY`; these constants remain as a reference that
#: tests/sources/test_default_set.py compares with it (and with TERMINUS_CONFIG)
#: to avoid drift.
_HAZARD = "havingHazard"
_CRITICAL_EVENT = "havingCriticalEvent"
_PERFORMER = "havingPerformer"
_VULNERABILITY_PROPS = ("isVulnerableTo", "havingVulnerability")


class InvalidIriError(ValueError):
    """Namespace or property names not valid as IRIs (rejected early)."""


#: Parametrised query on the graph that enumerates, for each class ``?c`` with an
#: ``owl:Restriction``, the pair ``(property, filler)``. Static and
#: independent of the configured namespaces/properties: the risk properties are
#: selected afterwards, in Python, by comparing ``URIRef`` (no string
#: interpolation in the query). Executed ONCE in
#: :meth:`RiskQueryExecutor.__init__`.
_RESTRICTION_QUERY = prepareQuery(
    """
    SELECT DISTINCT ?c ?prop ?filler WHERE {
        ?c rdfs:subClassOf ?r .
        ?r a owl:Restriction ;
           owl:onProperty ?prop ;
           owl:someValuesFrom ?filler .
    }
    """,
    initNs={
        "owl": URIRef("http://www.w3.org/2002/07/owl#"),
        "rdfs": RDFS,
    },
)


def _local_name(term: URIRef) -> str:
    """Local class name (Underscore_Case) from a TERMINUS ``URIRef``."""
    text = str(term)
    return text.rsplit("#", 1)[-1] if "#" in text else text.rsplit("/", 1)[-1]


class RiskQueryExecutor:
    """Index of the risk restrictions, built once on the graph.

    Namespace and property names are configurable (default TERMINUS).

    Building the executor runs the parametrised query that enumerates all the
    restrictions of the graph (expensive part, POI-independent). From then on
    :meth:`profile` answers in constant time for each POI. It must be instantiated once
    at startup (lifespan) and exposed via dependency injection, not recreated
    per request.
    """

    def __init__(
        self,
        graph: Graph,
        *,
        vocabulary: OntologyVocabulary = TERMINUS_VOCABULARY,
    ) -> None:
        """Indexes the risk restrictions of the graph.

        Args:
            graph: already loaded ontology.
            vocabulary: namespace and names of the five risk properties.
                Default: TERMINUS.

        Raises:
            InvalidIriError: vocabulary not valid as IRIs (checked before
                any query of the graph).
        """
        problems = vocabulary.problems()
        if problems:
            raise InvalidIriError("; ".join(problems))
        ns = Namespace(vocabulary.namespace)
        wanted = {ns[name]: name for name in vocabulary.properties}
        self._vocabulary = vocabulary
        self._ns = ns
        self._graph = graph
        # Map class-with-restriction -> (property, filler) pairs already as local
        # names. Only the classes that declare at least one restriction appear.
        self._by_class: dict[URIRef, list[tuple[str, str]]] = {}
        for row in graph.query(_RESTRICTION_QUERY):
            cls, prop, filler = row[0], row[1], row[2]  # type: ignore[misc]
            if not isinstance(prop, URIRef) or prop not in wanted:
                continue  # restriction on a non-risk property
            if isinstance(cls, URIRef) and isinstance(filler, URIRef):
                self._by_class.setdefault(cls, []).append(
                    (wanted[prop], _local_name(filler))
                )
            else:
                # Restriction with a non-URIRef term: typically an
                # ``owl:someValuesFrom`` on an anonymous node (BNode), e.g. a
                # ``owl:unionOf`` class. We discard it as before (no
                # functional change), but we log it: a filler lost silently
                # would mask an ontology drift (#116). The ``!r`` makes it
                # diagnosable *which* term is not a URIRef (the repr
                # distinguishes BNode/Literal/URIRef) and *which* triple carries it.
                detail = f"cls={cls!r} prop={prop!r} filler={filler!r}"
                logger.warning(
                    "TERMINUS restriction discarded (non-URIRef term): %s", detail
                )

    def _fillers_by_property(self, terminus_class: str) -> dict[str, list[str]]:
        """Fillers reachable from ``terminus_class``, grouped by property.

        Closes ``rdfs:subClassOf*`` on the class (native rdflib traversal) and
        collects the restrictions of all the ancestors that declare any. The fillers
        are deduplicated and sorted for determinism (rdflib does not guarantee a
        stable order on the blank nodes of the restrictions).
        """
        ancestors = self._graph.transitive_objects(
            self._ns[terminus_class], RDFS.subClassOf
        )
        collected: dict[str, set[str]] = {}
        for ancestor in ancestors:
            if not isinstance(ancestor, URIRef):
                continue
            for prop, filler in self._by_class.get(ancestor, ()):
                collected.setdefault(prop, set()).add(filler)
        return {prop: sorted(fillers) for prop, fillers in collected.items()}

    def profile(
        self, terminus_class: str, *, poi_name: str | None = None
    ) -> PoiRiskProfile:
        """Risk profile of the class ``terminus_class``.

        An unmapped / non-existent / ``GenericUrbanPOI`` class simply produces
        empty lists: no exception, because it does not appear in the
        index (done criterion #76, handling of unmapped POIs in
        ``sparql.md``).

        Args:
            terminus_class: bare TERMINUS class name (e.g. ``"Bank"``), without
                prefix.
            poi_name: readable name of the OSM POI, reported as is.

        Returns:
            :class:`PoiRiskProfile` with hazard, critical event, vulnerabilities,
            stakeholders and the related ``sparql_path`` (one hop per filler).
        """
        by_prop = self._fillers_by_property(terminus_class)

        voc = self._vocabulary
        hazards = by_prop.get(voc.hazard, [])
        critical_events = by_prop.get(voc.critical_event, [])
        stakeholders = by_prop.get(voc.performer, [])
        vulnerabilities = sorted(
            {f for prop in voc.vulnerability for f in by_prop.get(prop, [])}
        )

        # One sparql_path per filler, with the real property that links it (one hop).
        # Unicode arrow glyph "→" (U+2192) as per the canonical schema of sparql.md /
        # orchestrator.md / grounding.md: byte-consistent with the citation layer (#24).
        sparql_paths = [
            f"{terminus_class} → {prop} → {filler}"
            for prop in (
                voc.hazard,
                voc.critical_event,
                *voc.vulnerability,
                voc.performer,
            )
            for filler in by_prop.get(prop, [])
        ]

        return PoiRiskProfile(
            poi_name=poi_name,
            terminus_class=terminus_class,
            hazards=hazards,
            critical_events=critical_events,
            vulnerabilities=vulnerabilities,
            stakeholders=stakeholders,
            sparql_paths=sparql_paths,
        )


@lru_cache
def get_executor() -> RiskQueryExecutor:
    """Cached DI provider of the SPARQL executor (singleton on the cached graph)."""
    return RiskQueryExecutor(get_ontology())
