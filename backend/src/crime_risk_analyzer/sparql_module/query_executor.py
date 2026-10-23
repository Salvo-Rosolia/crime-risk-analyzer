"""Executor SPARQL sul pattern OWL restriction di TERMINUS Crime (#76).

Data una classe POI (es. ``Bank``), estrae dal grafo ontologico i rischi
associati — hazard, critical event, vulnerabilita', stakeholder — interrogando
il pattern a **OWL restriction** con cui TERMINUS codifica le associazioni:

    tc:Bank rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty tc:havingHazard ; owl:someValuesFrom tc:Bank_robbery ] .

I rischi NON sono triple dirette ``?poi tc:havingHazard ?h``: una query a triple
dirette restituisce 0 risultati. Le associazioni vivono nei nodi
``owl:Restriction`` agganciati via ``rdfs:subClassOf``, e una classe eredita anche
le restrizioni dichiarate sulle superclassi (chiusura ``rdfs:subClassOf*``).
**Nessun reasoner**: l'ontologia e' una TBox pura (0 individui) e la chiusura
``subClassOf*`` di rdflib basta.

Architettura (build-once, query-many — coerente con "il grafo si carica una volta
nel lifespan, non per richiesta"):

* :class:`RiskQueryExecutor` indicizza **una volta** tutte le restrizioni del
  grafo con una query SPARQL **parametrizzata** (:func:`prepareQuery`): la classe
  POI non entra mai per concatenazione di stringa. L'indicizzazione e' l'unica
  parte costosa (enumera i nodi restrizione) ed e' indipendente dal POI, quindi
  va fatta a startup, dentro il budget di caricamento del grafo.
* :meth:`RiskQueryExecutor.profile` risponde per ogni POI con una chiusura
  ``subClassOf*`` nativa (``rdflib.Graph.transitive_objects``, livello C) piu' una
  selezione sull'indice: pochi decimi di millisecondo, ben sotto il budget di 100
  ms per query del criterio di done (sul grafo reale; sulla fixture e' banale).

Forma di query e schema di output: ``docs/specs/tree/backend/sparql.md``.
Citation layer: ogni filler produce un ``sparql_path`` lineare a un salto
(``Classe → property → entita``, glyph Unicode U+2192 come da schema canonico)
consumato dal grounding per il tag ``[ONTOLOGIA]``.
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


#: Nomi TERMINUS storici delle property di rischio. Il default dell'executor e'
#: :data:`TERMINUS_VOCABULARY`; queste costanti restano come riferimento che
#: tests/sources/test_default_set.py confronta con esso (e con TERMINUS_CONFIG)
#: per evitare drift.
_HAZARD = "havingHazard"
_CRITICAL_EVENT = "havingCriticalEvent"
_PERFORMER = "havingPerformer"
_VULNERABILITY_PROPS = ("isVulnerableTo", "havingVulnerability")


class InvalidIriError(ValueError):
    """Namespace o nomi di property non validi come IRI (rifiutati in anticipo)."""


#: Query parametrica sul grafo che enumera, per ogni classe ``?c`` con una
#: restrizione ``owl:Restriction``, la coppia ``(property, filler)``. Statica e
#: indipendente da namespace/property configurati: le property di rischio si
#: selezionano dopo, in Python, confrontando ``URIRef`` (nessuna interpolazione
#: di stringhe nella query). Eseguita UNA volta in
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
    """Nome-classe locale (Underscore_Case) da una ``URIRef`` TERMINUS."""
    text = str(term)
    return text.rsplit("#", 1)[-1] if "#" in text else text.rsplit("/", 1)[-1]


class RiskQueryExecutor:
    """Indice delle restrizioni di rischio, costruito una volta sul grafo.

    Namespace e nomi delle property sono configurabili (default TERMINUS).

    Costruire l'executor esegue la query parametrizzata che enumera tutte le
    restrizioni del grafo (parte costosa, POI-indipendente). Da li' in poi
    :meth:`profile` risponde in tempo costante per ogni POI. Va istanziato una
    volta a startup (lifespan) ed esposto via dependency injection, non ricreato
    per richiesta.
    """

    def __init__(
        self,
        graph: Graph,
        *,
        vocabulary: OntologyVocabulary = TERMINUS_VOCABULARY,
    ) -> None:
        """Indicizza le restrizioni di rischio del grafo.

        Args:
            graph: ontologia gia' caricata.
            vocabulary: namespace e nomi delle cinque property di rischio.
                Default: TERMINUS.

        Raises:
            InvalidIriError: vocabolario non valido come IRI (controllato prima
                di qualunque interrogazione del grafo).
        """
        problems = vocabulary.problems()
        if problems:
            raise InvalidIriError("; ".join(problems))
        ns = Namespace(vocabulary.namespace)
        wanted = {ns[name]: name for name in vocabulary.properties}
        self._vocabulary = vocabulary
        self._ns = ns
        self._graph = graph
        # Mappa classe-con-restrizione -> coppie (property, filler) gia' come nomi
        # locali. Solo le classi che dichiarano almeno una restrizione compaiono.
        self._by_class: dict[URIRef, list[tuple[str, str]]] = {}
        for row in graph.query(_RESTRICTION_QUERY):
            cls, prop, filler = row[0], row[1], row[2]  # type: ignore[misc]
            if not isinstance(prop, URIRef) or prop not in wanted:
                continue  # restrizione su una property non di rischio
            if isinstance(cls, URIRef) and isinstance(filler, URIRef):
                self._by_class.setdefault(cls, []).append(
                    (wanted[prop], _local_name(filler))
                )
            else:
                # Restrizione con un termine non-URIRef: tipicamente un
                # ``owl:someValuesFrom`` su nodo anonimo (BNode), es. una classe
                # ``owl:unionOf``. La scartiamo come prima (nessun cambio
                # funzionale), ma la logghiamo: un filler perso in silenzio
                # mascherebbe un drift dell'ontologia (#116). Il ``!r`` rende
                # diagnosticabile *quale* termine non e' una URIRef (il repr
                # distingue BNode/Literal/URIRef) e *quale* triple lo porta.
                detail = f"cls={cls!r} prop={prop!r} filler={filler!r}"
                logger.warning(
                    "Restrizione TERMINUS scartata (termine non-URIRef): %s", detail
                )

    def _fillers_by_property(self, terminus_class: str) -> dict[str, list[str]]:
        """Filler raggiungibili da ``terminus_class``, raggruppati per property.

        Chiude ``rdfs:subClassOf*`` sulla classe (traversata nativa rdflib) e
        raccoglie le restrizioni di tutti gli antenati che ne dichiarano. I filler
        sono deduplicati e ordinati per determinismo (rdflib non garantisce un
        ordine stabile sui blank node delle restrizioni).
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
        """Profilo di rischio della classe ``terminus_class``.

        Una classe non mappata / inesistente / ``GenericUrbanPOI`` produce
        semplicemente liste vuote: nessuna eccezione, perche' non compare
        nell'indice (criterio di done #76, gestione POI non mappati di
        ``sparql.md``).

        Args:
            terminus_class: nome-classe TERMINUS bare (es. ``"Bank"``), senza
                prefisso.
            poi_name: nome leggibile del POI OSM, riportato tale e quale.

        Returns:
            :class:`PoiRiskProfile` con hazard, critical event, vulnerabilita',
            stakeholder e i relativi ``sparql_path`` (un salto per filler).
        """
        by_prop = self._fillers_by_property(terminus_class)

        voc = self._vocabulary
        hazards = by_prop.get(voc.hazard, [])
        critical_events = by_prop.get(voc.critical_event, [])
        stakeholders = by_prop.get(voc.performer, [])
        vulnerabilities = sorted(
            {f for prop in voc.vulnerability for f in by_prop.get(prop, [])}
        )

        # Un sparql_path per filler, con la property reale che lo lega (un salto).
        # Glyph arrow Unicode "→" (U+2192) come da schema canonico di sparql.md /
        # orchestrator.md / grounding.md: byte-consistente col citation layer (#24).
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
    """Provider DI cached dell'executor SPARQL (singleton sul grafo cached)."""
    return RiskQueryExecutor(get_ontology())
