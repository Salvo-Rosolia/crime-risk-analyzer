"""Da fonti lette e controllate a :class:`SourceSet` pronto da attivare (#416)."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from rdflib import Graph

from crime_risk_analyzer.istat.dati import Luogo, dati_istat_o_none
from crime_risk_analyzer.poi_types import alias_table, poi_types
from crime_risk_analyzer.sources.context import DEFAULT_ID, bind
from crime_risk_analyzer.sources.model import (
    IstatSource,
    OntologyConfig,
    OsmBinding,
    SourceSet,
)
from crime_risk_analyzer.sources.parsing import ParsedSources
from crime_risk_analyzer.sources.report import SourceValidationError, ValidationReport
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

    Raises:
        SourceValidationError: due classi del binding OSM hanno lo stesso alias di
            ``tipo_poi`` (stessa etichetta IT, o etichetta uguale al nome di
            un'altra classe): il filtro non saprebbe quale scegliere.
    """
    config = OntologyConfig(
        namespace=parsed.vocabulary.namespace,
        hazard=parsed.vocabulary.hazard,
        critical_event=parsed.vocabulary.critical_event,
        performer=parsed.vocabulary.performer,
        vulnerability=parsed.vocabulary.vulnerability,
    )
    source_set = SourceSet(
        id=_nuovo_id(),
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
    _controlla_alias_tipo_poi(source_set)
    return source_set


def _nuovo_id() -> str:
    """Id di un set custom.

    INVARIANTE: mai ``DEFAULT_ID``. :func:`crime_risk_analyzer.poi_types` riconosce
    il default (e ne mette il catalogo in cache) guardando solo l'id: un set
    custom con id ``"default"`` verrebbe servito con il catalogo del default.
    """
    nuovo = f"custom-{uuid.uuid4().hex[:16]}"
    if nuovo == DEFAULT_ID:  # pragma: no cover - impossibile col prefisso
        msg = "un set custom non puo' avere l'id del default"
        raise ValueError(msg)
    return nuovo


def _controlla_alias_tipo_poi(source_set: SourceSet) -> None:
    """Rifiuta il set se due sue classi condividono un alias di ``tipo_poi``.

    Stesso calcolo del lookup a runtime (:func:`alias_table`), eseguito qui una
    volta sola: senza questo controllo ogni ``tipo_poi`` darebbe un 500.
    """
    with bind(source_set):
        _, conflitti = alias_table(poi_types())
    if not conflitti:
        return
    report = ValidationReport()
    for c in conflitti:
        report.error(
            "alias_tipo_poi_ambiguo",
            "osm_table",
            f"{c.message()}: dai a una delle due classi un'etichetta diversa",
        )
    raise SourceValidationError(report)


def fallback_luoghi() -> tuple[Luogo, ...]:
    """Confini nostri, per i luoghi dei dati che il file dei confini non copre."""
    dati = dati_istat_o_none()
    return dati.luoghi if dati is not None else ()
