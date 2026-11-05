"""Catalogue of the selectable POI types and normalisation of ``tipo_poi`` (#143).

The catalogue is the set of classes that the system can really produce: the
distinct values of the OSM binding of the active set (for the default, the
constants of :mod:`~crime_risk_analyzer.sparql_module.osm_mapping`). The
fallback for uncovered tags (``GENERIC_FALLBACK``) is not part of it: it is not
an ontology class and filtering by "not covered" makes no sense for the operator.

The label is that of the controlled vocabulary #77 (:func:`label_it`). Today
all the mapping classes have a real IT label; if one were ever missing,
:func:`label_it` degrades to the EN label and then to the normalised name, and
the class stays in the catalogue: excluding it would make it unfilterable even
though it is produced by the mapping.

``tipo_poi`` arrives from a free text field, so the normalisation accepts,
case-insensitively and with equivalent spaces/underscores, both the class name
(``"railway_station"``) and the IT label (``"stazione ferroviaria"``), and always
returns the canonical name. A value that matches nothing is
:class:`UnknownPoiTypeError` (422 in :mod:`~crime_risk_analyzer.errors`) instead
of a silent empty list.
"""

from __future__ import annotations

import weakref
from functools import lru_cache
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict

from crime_risk_analyzer.i18n.terminus_labels import label_it
from crime_risk_analyzer.sources.context import (
    DEFAULT_ID,
    active_set,
    current_id,
    current_osm,
)
from crime_risk_analyzer.sources.model import SourceSet


class PoiType(BaseModel):
    """Entry of the catalogue exposed by ``GET /poi-types``.

    Immutable: the instances live in the cache of :func:`poi_types`, shared among
    requests.
    """

    model_config = ConfigDict(frozen=True)

    ontology_class: str
    label_it: str


class PoiTypeEntry(PoiType):
    """Item of the ``GET /poi-types`` body: a catalogue entry plus the id of the
    set it belongs to (#473).

    ``source_set_id`` is the same on every item (the list shape is kept so that
    existing clients still parse it); the client compares it with the id it holds
    to notice that the server serves a different set.
    """

    source_set_id: str


class UnknownPoiTypeError(Exception):
    """``tipo_poi`` does not match any class of the catalogue (-> 422)."""

    def __init__(self, raw: str) -> None:
        super().__init__(f"Tipo POI non riconosciuto: {raw!r}")


#: Apostrophe variants that a keyboard or a spell-checker can produce
#: (typographic, modifier, grave/acute accent): all equivalent to ``'``.
_APOSTROPHES = str.maketrans(
    dict.fromkeys(map(chr, (0x2019, 0x2018, 0x02BC, 0x0060, 0x00B4)), "'")
)


def _key(text: str) -> str:
    """Comparison key: casefold, unified apostrophes, underscore as space,
    compacted spaces."""
    normalized = text.translate(_APOSTROPHES).replace("_", " ").casefold()
    return " ".join(normalized.split())


def _catalog() -> tuple[PoiType, ...]:
    """Catalogue of the active set, sorted by IT label.

    Sorted by ``casefold`` of the label (tie-break on the class name):
    deterministic and independent of the process locale.
    """
    entries = [
        PoiType(ontology_class=cls, label_it=label_it(cls))
        for cls in set(current_osm().osm_to_class.values())
    ]
    return tuple(
        sorted(entries, key=lambda t: (t.label_it.casefold(), t.ontology_class))
    )


@lru_cache(maxsize=1)
def _default_catalog() -> tuple[PoiType, ...]:
    return _catalog()


#: Catalogue of each custom set, computed once. Weak keys: the entry dies with
#: the (immutable) set, so an expired session leaves nothing behind. The values
#: do not reference the key, otherwise it would never be collected.
_CUSTOM_CATALOGS: weakref.WeakKeyDictionary[SourceSet, tuple[PoiType, ...]] = (
    weakref.WeakKeyDictionary()
)


def _is_default() -> bool:
    return current_id() == DEFAULT_ID


def poi_type_entries() -> list[PoiTypeEntry]:
    """Catalogue of the active set, each entry tagged with the set id (#473)."""
    set_id = current_id()
    return [
        PoiTypeEntry(
            ontology_class=t.ontology_class, label_it=t.label_it, source_set_id=set_id
        )
        for t in poi_types()
    ]


def poi_types() -> tuple[PoiType, ...]:
    """Classes producible by the OSM binding of the active set, sorted by IT label.

    The default's catalogue is cached for the process; that of a custom set is
    computed once per :class:`SourceSet` (immutable) and lives as long as the set,
    so two different sets never get mixed and an expired set is not retained.
    """
    active = active_set()
    if active is None or _is_default():
        return _default_catalog()
    catalog = _CUSTOM_CATALOGS.get(active)
    if catalog is None:
        catalog = _CUSTOM_CATALOGS[active] = _catalog()
    return catalog


class AliasConflict(NamedTuple):
    """An alias of ``tipo_poi`` that leads to two different classes."""

    alias: str
    first: str
    second: str

    def message(self) -> str:
        return f"alias tipo POI ambiguo {self.alias!r}: {self.first} e {self.second}"


def alias_table(
    types: tuple[PoiType, ...],
) -> tuple[dict[str, str], list[AliasConflict]]:
    """Normalised key (class name or IT label) -> canonical class name,
    plus the ambiguous aliases.

    An alias that already leads to a DIFFERENT class is a conflict, not a
    silent overwrite that would hijack the filter. A label that
    coincides with its own name (``Cinema``, ``Silo``) is instead harmless. Single
    logic: used both by the runtime lookup and by the check at the upload of a set.
    """
    table: dict[str, str] = {}
    conflicts: list[AliasConflict] = []
    for t in types:
        for alias in (t.ontology_class, t.label_it):
            other = table.setdefault(_key(alias), t.ontology_class)
            if other != t.ontology_class:
                conflicts.append(AliasConflict(alias, other, t.ontology_class))
    return table, conflicts


def _alias_table(types: tuple[PoiType, ...]) -> dict[str, str]:
    """Alias table; fail-fast on ambiguities (``RuntimeError``)."""
    table, conflicts = alias_table(types)
    if conflicts:
        raise RuntimeError(conflicts[0].message())
    return table


@lru_cache(maxsize=1)
def _lookup() -> dict[str, str]:
    """Alias table of the default set (cached, like its catalogue)."""
    return _alias_table(poi_types())


def _active_lookup() -> dict[str, str]:
    return _lookup() if _is_default() else _alias_table(poi_types())


def resolve_poi_type(raw: str | None) -> str | None:
    """Normalises ``tipo_poi`` to the canonical class name.

    ``None`` or empty/whitespace-only string -> ``None`` (no filter). Otherwise
    the canonical class name, or :class:`UnknownPoiTypeError` if the value
    matches neither a class name nor an IT label of the catalogue.
    """
    text = (raw or "").strip()
    if not text:
        return None
    canonical = _active_lookup().get(_key(text))
    if canonical is None:
        raise UnknownPoiTypeError(text)
    return canonical
