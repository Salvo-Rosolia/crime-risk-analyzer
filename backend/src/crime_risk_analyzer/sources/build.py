"""Da fonti lette e controllate a :class:`SourceSet` pronto da attivare (#416)."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from rdflib import Graph

from crime_risk_analyzer.istat.dati import Luogo, dati_istat_o_none
from crime_risk_analyzer.sources.model import (
    IstatSource,
    OntologyConfig,
    OsmBinding,
    SourceSet,
)
from crime_risk_analyzer.sources.parsing import ParsedSources
from crime_risk_analyzer.sparql_module.query_executor import RiskQueryExecutor

__all__ = [
    "ExecutorFactory",
    "build_source_set",
    "default_executor_factory",
    "fallback_luoghi",
]

ExecutorFactory = Callable[[Graph, OntologyConfig], RiskQueryExecutor]


def default_executor_factory(graph: Graph, config: OntologyConfig) -> RiskQueryExecutor:
    """Executor sul grafo caricato.

    PUNTO DI COLLEGAMENTO con #412: oggi ``RiskQueryExecutor`` conosce solo il
    namespace e le proprieta' TERMINUS e ignora ``config``; quando l'executor
    accettera' un :class:`OntologyConfig` va passato qui, e solo qui.
    """
    del config
    return RiskQueryExecutor(graph)


def build_source_set(
    parsed: ParsedSources,
    *,
    executor_factory: ExecutorFactory = default_executor_factory,
) -> SourceSet:
    """Impacchetta le fonti controllate in un set con id nuovo e univoco.

    L'id e' diverso a ogni caricamento (anche con file identici): e' la parte
    della chiave di cache di zona e dell'impronta del contesto che separa le
    sessioni e che invalida la cache quando una sessione ricarica.
    """
    config = OntologyConfig(
        namespace=parsed.vocabulary.namespace,
        hazard=parsed.vocabulary.hazard,
        critical_event=parsed.vocabulary.critical_event,
        performer=parsed.vocabulary.performer,
        vulnerability=parsed.vocabulary.vulnerability,
    )
    return SourceSet(
        id=f"custom-{uuid.uuid4().hex[:16]}",
        kind="custom",
        graph=parsed.graph,
        ontology=config,
        executor=executor_factory(parsed.graph, config),
        osm=OsmBinding(
            osm_to_class=parsed.osm_to_class,
            ordine_famiglie=parsed.ordine_famiglie,
            selettori_cedevoli={},
        ),
        istat=IstatSource(
            dati=parsed.istat,
            mappatura=parsed.mappatura,
            voci_rottura=parsed.voci_rottura,
            versione=parsed.versione,
        ),
        labels=parsed.labels,
    )


def fallback_luoghi() -> tuple[Luogo, ...]:
    """Confini nostri, per i luoghi dei dati che il file dei confini non copre."""
    dati = dati_istat_o_none()
    return dati.luoghi if dati is not None else ()
