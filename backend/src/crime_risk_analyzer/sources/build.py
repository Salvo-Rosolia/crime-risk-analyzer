"""From read and checked sources to a :class:`SourceSet` ready to activate (#416)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Literal

from rdflib import Graph

from crime_risk_analyzer.istat.data import Place, istat_data_or_none
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
from crime_risk_analyzer.sources.vocabulary import OntologyVocabulary
from crime_risk_analyzer.sparql_module.query_executor import RiskQueryExecutor

__all__ = [
    "EXAMPLE_ID",
    "ExecutorFactory",
    "build_source_set",
    "default_executor_factory",
    "fallback_places",
]

ExecutorFactory = Callable[[Graph, OntologyConfig], RiskQueryExecutor]


#: Id of the example set: fixed, because the set is single and shared (built
#: once); the ``custom`` sets instead have a new id at every upload.
EXAMPLE_ID = "example"


def default_executor_factory(graph: Graph, config: OntologyConfig) -> RiskQueryExecutor:
    """Executor on the loaded graph, with the namespace and properties of the set."""
    return RiskQueryExecutor(
        graph,
        vocabulary=OntologyVocabulary(
            namespace=config.namespace,
            hazard=config.hazard,
            critical_event=config.critical_event,
            performer=config.performer,
            vulnerability=config.vulnerability,
        ),
    )


def build_source_set(
    parsed: ParsedSources,
    *,
    kind: Literal["example", "custom"] = "custom",
    executor_factory: ExecutorFactory = default_executor_factory,
) -> SourceSet:
    """Packages the checked sources into a set.

    A ``custom`` set has a new and unique id at every upload (even with identical
    files): it is the part of the zone cache key and of the context fingerprint
    that separates the sessions and that invalidates the cache when a session
    uploads again. The ``example`` set has the fixed id :data:`EXAMPLE_ID`: whoever uses
    it builds it only once and shares it.

    Raises:
        SourceValidationError: two classes of the OSM binding have the same
            ``tipo_poi`` alias (same IT label, or a label equal to the name of
            another class): the filter would not know which to choose.
    """
    config = OntologyConfig(
        namespace=parsed.vocabulary.namespace,
        hazard=parsed.vocabulary.hazard,
        critical_event=parsed.vocabulary.critical_event,
        performer=parsed.vocabulary.performer,
        vulnerability=parsed.vocabulary.vulnerability,
    )
    source_set = SourceSet(
        id=_new_id() if kind == "custom" else EXAMPLE_ID,
        kind=kind,
        graph=parsed.graph,
        ontology=config,
        executor=executor_factory(parsed.graph, config),
        osm=OsmBinding(
            osm_to_class=parsed.osm_to_class,
            family_order=parsed.family_order,
            yielding_selectors={},
        ),
        istat=IstatSource(
            dati=parsed.istat,
            mappatura=parsed.mappatura,
            voci_rottura=parsed.voci_rottura,
            versione=parsed.versione,
        ),
        labels=parsed.labels,
    )
    _check_poi_type_aliases(source_set)
    return source_set


def _new_id() -> str:
    """Id of a custom set.

    INVARIANT: never ``DEFAULT_ID``. :func:`crime_risk_analyzer.poi_types` recognises
    the default (and caches its catalogue) by looking only at the id: a custom
    set with id ``"default"`` would be served with the default's catalogue.
    """
    new_id = f"custom-{uuid.uuid4().hex[:16]}"
    if new_id == DEFAULT_ID:  # pragma: no cover - impossible with the prefix
        msg = "un set custom non puo' avere l'id del default"
        raise ValueError(msg)
    return new_id


def _check_poi_type_aliases(source_set: SourceSet) -> None:
    """Rejects the set if two of its classes share a ``tipo_poi`` alias.

    Same computation as the runtime lookup (:func:`alias_table`), executed here once
    only: without this check every ``tipo_poi`` would give a 500.
    """
    with bind(source_set):
        _, conflicts = alias_table(poi_types())
    if not conflicts:
        return
    report = ValidationReport()
    for c in conflicts:
        report.error(
            "alias_tipo_poi_ambiguo",
            "osm_table",
            f"{c.message()}: dai a una delle due classi un'etichetta diversa",
        )
    raise SourceValidationError(report)


def fallback_places() -> tuple[Place, ...]:
    """Our own boundaries, for the places the boundaries file does not cover."""
    dati = istat_data_or_none()
    return dati.luoghi if dati is not None else ()
