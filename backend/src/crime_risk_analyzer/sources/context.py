"""Set di fonti attivo per la richiesta corrente (#411).

``current()`` ritorna il set legato con :func:`bind` nel contesto corrente, o il
default. Si usa un :class:`~contextvars.ContextVar`: ogni task asyncio ha il suo
valore e il valore e' visibile nel threadpool di Starlette (copia del contesto).

Limiti noti: (a) un task lanciato con ``asyncio.create_task``/``to_thread`` che
sopravvive al blocco :func:`bind` conserva il set del contesto copiato alla
creazione; (b) :func:`default_set` congela dati, grafo ed executor alla prima
chiamata e non si azzera con ``svuota_cache()``/``cache_clear()`` delle cache
sottostanti (va svuotata anche ``default_set.cache_clear()``).
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache

from crime_risk_analyzer.istat.catalogo import VOCI_ROTTURA_2016
from crime_risk_analyzer.istat.dati import dati_istat_o_none
from crime_risk_analyzer.istat.mappatura import MAPPATURA
from crime_risk_analyzer.ontology import get_ontology
from crime_risk_analyzer.sources.model import (
    TERMINUS_CONFIG,
    IstatSource,
    OsmBinding,
    SourceSet,
)
from crime_risk_analyzer.sparql_module.osm_mapping import (
    ORDINE_FAMIGLIE,
    OSM_TO_TERMINUS,
    SELETTORI_CEDEVOLI,
)
from crime_risk_analyzer.sparql_module.query_executor import (
    RiskQueryExecutor,
    get_executor,
)

__all__ = ["bind", "current", "current_executor", "default_set"]

_ACTIVE: ContextVar[SourceSet | None] = ContextVar("active_source_set", default=None)


@lru_cache(maxsize=1)
def default_set() -> SourceSet:
    """Set TERMINUS + ISTAT costruito dai moduli esistenti (singleton)."""
    dati = dati_istat_o_none()
    return SourceSet(
        id="default",
        kind="default",
        graph=get_ontology(),
        ontology=TERMINUS_CONFIG,
        executor=get_executor(),
        osm=OsmBinding(
            osm_to_class=OSM_TO_TERMINUS,
            ordine_famiglie=ORDINE_FAMIGLIE,
            selettori_cedevoli=SELETTORI_CEDEVOLI,
        ),
        istat=IstatSource(
            dati=dati,
            mappatura=MAPPATURA,
            voci_rottura=VOCI_ROTTURA_2016,
            versione=dati.versione if dati is not None else None,
        ),
        labels=None,
    )


def current() -> SourceSet:
    """Set attivo nel contesto corrente, altrimenti il default."""
    active = _ACTIVE.get()
    return active if active is not None else default_set()


def current_executor() -> RiskQueryExecutor:
    """Executor SPARQL del set attivo (dipendenza delle rotte)."""
    return current().executor


@contextmanager
def bind(source_set: SourceSet) -> Generator[None]:
    """Rende ``source_set`` attivo nel blocco; all'uscita ripristina il precedente."""
    token = _ACTIVE.set(source_set)
    try:
        yield
    finally:
        _ACTIVE.reset(token)
