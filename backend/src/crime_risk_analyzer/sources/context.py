"""Source set active for the current request (#411).

``current()`` returns the set bound with :func:`bind` in the current context, or the
default. A :class:`~contextvars.ContextVar` is used: each asyncio task has its own
value and the value is visible in Starlette's threadpool (copy of the context).

Known limits: (a) a task launched with ``asyncio.create_task``/``to_thread`` that
outlives the :func:`bind` block keeps the set of the context copied at
creation; (b) :func:`default_set` freezes data, graph and executor at the first
call and is not reset by ``clear_cache()``/``cache_clear()`` of the
underlying caches (``default_set.cache_clear()`` must be emptied too).
"""

from __future__ import annotations

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache

from crime_risk_analyzer.istat.catalog import BREAK_ITEMS_2016
from crime_risk_analyzer.istat.data import data_version as _default_data_version
from crime_risk_analyzer.istat.data import istat_data_or_none
from crime_risk_analyzer.istat.mapping import HAZARD_MAPPING
from crime_risk_analyzer.ontology import get_ontology
from crime_risk_analyzer.sources.model import (
    TERMINUS_CONFIG,
    IstatSource,
    OntologyConfig,
    OsmBinding,
    SourceSet,
)
from crime_risk_analyzer.sparql_module.osm_mapping import (
    FAMILY_ORDER,
    OSM_TO_TERMINUS,
    YIELDING_SELECTORS,
)
from crime_risk_analyzer.sparql_module.query_executor import (
    RiskQueryExecutor,
    get_executor,
)

__all__ = [
    "DEFAULT_ID",
    "active_set",
    "active_istat",
    "bind",
    "bind_session",
    "current",
    "current_executor",
    "current_id",
    "current_labels",
    "current_ontology",
    "current_osm",
    "current_session_id",
    "default_set",
    "istat_data_version",
]

DEFAULT_ID = "default"

#: OSM binding of the default: built from the constants, without building the set.
_DEFAULT_OSM = OsmBinding(
    osm_to_class=OSM_TO_TERMINUS,
    family_order=FAMILY_ORDER,
    yielding_selectors=YIELDING_SELECTORS,
)

_ACTIVE: ContextVar[SourceSet | None] = ContextVar("active_source_set", default=None)

#: Client session of the current request (``X-Session-Id``), bound even when the
#: session has no set: per-session state (zone cache, #495) is keyed on it.
_SESSION: ContextVar[str | None] = ContextVar("active_session_id", default=None)


@lru_cache(maxsize=1)
def default_set() -> SourceSet:
    """TERMINUS + ISTAT set built from the existing modules (singleton)."""
    dati = istat_data_or_none()
    return SourceSet(
        id="default",
        kind="default",
        graph=get_ontology(),
        ontology=TERMINUS_CONFIG,
        executor=get_executor(),
        osm=_DEFAULT_OSM,
        istat=IstatSource(
            dati=dati,
            mappatura=HAZARD_MAPPING,
            voci_rottura=BREAK_ITEMS_2016,
            versione=dati.versione if dati is not None else None,
        ),
        labels=None,
    )


def current() -> SourceSet:
    """Active set in the current context, otherwise the default."""
    active = _ACTIVE.get()
    return active if active is not None else default_set()


def active_set() -> SourceSet | None:
    """Set bound with :func:`bind`; ``None`` if the default applies (no build)."""
    return _ACTIVE.get()


def current_id() -> str:
    """Id of the active set, without building the default (cache keys, fingerprints)."""
    active = _ACTIVE.get()
    return active.id if active is not None else DEFAULT_ID


def current_osm() -> OsmBinding:
    """OSM binding of the active set; without a set, that of the default.

    It does not build the default set (graph, ISTAT data): the Overpass path
    and the offline tools do not need it.
    """
    active = _ACTIVE.get()
    return active.osm if active is not None else _DEFAULT_OSM


def current_labels() -> Mapping[str, tuple[str, str]] | None:
    """Labels ``class -> (IT, EN)`` of the active set; ``None`` = TERMINUS JSON.

    Like :func:`current_osm`, it does not build the default (which has ``labels=None``).
    """
    active = _ACTIVE.get()
    return active.labels if active is not None else None


def current_ontology() -> OntologyConfig:
    """Ontology properties of the active set; without a set, the TERMINUS ones.

    Like :func:`current_osm`, it does not build the default (the grounding does not load
    the graph to read the property names).
    """
    active = _ACTIVE.get()
    return active.ontology if active is not None else TERMINUS_CONFIG


def active_istat() -> IstatSource | None:
    """ISTAT source of the set bound with :func:`bind`; ``None`` if the default applies.

    Outside ``bind`` it does NOT build the default: whoever reads ISTAT goes through the
    data caches (``istat_data_or_none``), as before #414. With a bound set
    the rows, the mapping and the version are ALWAYS those of the set, even if
    ``dati`` is ``None`` (no fallback on the default data).
    """
    active = _ACTIVE.get()
    return active.istat if active is not None else None


def istat_data_version() -> str | None:
    """Version of the ISTAT data of the active set, ``None`` if not available.

    Single source for response, fingerprint and comparison; with the default it
    coincides with :func:`crime_risk_analyzer.istat.data.data_version`.
    """
    istat = active_istat()
    return istat.versione if istat is not None else _default_data_version()


def current_executor() -> RiskQueryExecutor:
    """SPARQL executor of the active set (dependency of the routes)."""
    return current().executor


@contextmanager
def bind(source_set: SourceSet) -> Generator[None]:
    """Makes ``source_set`` active in the block; on exit restores the previous one."""
    token = _ACTIVE.set(source_set)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def current_session_id() -> str:
    """Session id of the current request; empty string without a session."""
    return _SESSION.get() or ""


@contextmanager
def bind_session(session_id: str) -> Generator[None]:
    """Makes ``session_id`` the current session in the block (#495)."""
    token = _SESSION.set(session_id)
    try:
        yield
    finally:
        _SESSION.reset(token)
