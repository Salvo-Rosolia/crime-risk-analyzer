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

from collections.abc import Generator, Mapping
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

__all__ = [
    "DEFAULT_ID",
    "bind",
    "current",
    "current_executor",
    "current_id",
    "current_labels",
    "current_osm",
    "default_set",
]

DEFAULT_ID = "default"

#: Binding OSM del default: costruito dalle costanti, senza costruire il set.
_DEFAULT_OSM = OsmBinding(
    osm_to_class=OSM_TO_TERMINUS,
    ordine_famiglie=ORDINE_FAMIGLIE,
    selettori_cedevoli=SELETTORI_CEDEVOLI,
)

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
        osm=_DEFAULT_OSM,
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


def current_id() -> str:
    """Id del set attivo, senza costruire il default (chiavi di cache e impronte)."""
    active = _ACTIVE.get()
    return active.id if active is not None else DEFAULT_ID


def current_osm() -> OsmBinding:
    """Binding OSM del set attivo; senza set, quello del default.

    Non costruisce il set di default (grafo, dati ISTAT): il percorso di Overpass
    e dei tool offline non ne ha bisogno.
    """
    active = _ACTIVE.get()
    return active.osm if active is not None else _DEFAULT_OSM


def current_labels() -> Mapping[str, tuple[str, str]] | None:
    """Etichette ``classe -> (IT, EN)`` del set attivo; ``None`` = JSON TERMINUS.

    Come :func:`current_osm`, non costruisce il default (che ha ``labels=None``).
    """
    active = _ACTIVE.get()
    return active.labels if active is not None else None


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
