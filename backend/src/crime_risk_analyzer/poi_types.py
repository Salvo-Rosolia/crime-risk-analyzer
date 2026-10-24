"""Catalogo dei tipi POI selezionabili e normalizzazione di ``tipo_poi`` (#143).

Il catalogo e' l'insieme delle classi che il sistema puo' davvero produrre: i
valori distinti del binding OSM del set attivo (per il default, le costanti di
:mod:`~crime_risk_analyzer.sparql_module.osm_mapping`). Il
fallback dei tag non coperti (``GENERIC_FALLBACK``) non ne fa parte: non e' una
classe dell'ontologia e filtrare per "non coperto" non ha senso per l'operatore.

L'etichetta e' quella del vocabolario controllato #77 (:func:`label_it`). Oggi
tutte le classi del mapping hanno un'etichetta IT reale; se un domani ne mancasse
una, :func:`label_it` degrada all'etichetta EN e poi al nome normalizzato, e la
classe resta nel catalogo: escluderla la renderebbe non filtrabile pur essendo
prodotta dal mapping.

``tipo_poi`` arriva da un campo di testo libero, quindi la normalizzazione
accetta, senza distinzione di maiuscole e con spazi/underscore equivalenti, sia
il nome della classe (``"railway_station"``) sia l'etichetta IT
(``"stazione ferroviaria"``), e restituisce sempre il nome canonico. Un valore
che non corrisponde a nulla e' :class:`UnknownPoiTypeError` (422 in
:mod:`~crime_risk_analyzer.errors`) invece di una lista vuota silenziosa.
"""

from __future__ import annotations

from functools import lru_cache
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict

from crime_risk_analyzer.i18n.terminus_labels import label_it
from crime_risk_analyzer.sources.context import DEFAULT_ID, current_id, current_osm


class PoiType(BaseModel):
    """Voce del catalogo esposto da ``GET /poi-types``.

    Immutabile: le istanze vivono nella cache di :func:`poi_types`, condivisa fra
    le richieste.
    """

    model_config = ConfigDict(frozen=True)

    terminus_class: str
    label_it: str


class UnknownPoiTypeError(Exception):
    """``tipo_poi`` non corrisponde a nessuna classe del catalogo (-> 422)."""

    def __init__(self, raw: str) -> None:
        super().__init__(f"Tipo POI non riconosciuto: {raw!r}")


#: Varianti di apostrofo che una tastiera o un correttore possono produrre
#: (tipografico, modificatore, accento grave/acuto): tutte equivalgono a ``'``.
_APOSTROPHES = str.maketrans(
    dict.fromkeys(map(chr, (0x2019, 0x2018, 0x02BC, 0x0060, 0x00B4)), "'")
)


def _key(text: str) -> str:
    """Chiave di confronto: casefold, apostrofi unificati, underscore come spazio,
    spazi compattati."""
    normalized = text.translate(_APOSTROPHES).replace("_", " ").casefold()
    return " ".join(normalized.split())


def _catalogo() -> tuple[PoiType, ...]:
    """Catalogo del set attivo, ordinato per etichetta IT.

    Ordinamento per ``casefold`` dell'etichetta (spareggio sul nome-classe):
    deterministico e indipendente dal locale del processo.
    """
    entries = [
        PoiType(terminus_class=cls, label_it=label_it(cls))
        for cls in set(current_osm().osm_to_class.values())
    ]
    return tuple(
        sorted(entries, key=lambda t: (t.label_it.casefold(), t.terminus_class))
    )


@lru_cache(maxsize=1)
def _catalogo_default() -> tuple[PoiType, ...]:
    return _catalogo()


def _e_default() -> bool:
    return current_id() == DEFAULT_ID


def poi_types() -> tuple[PoiType, ...]:
    """Classi producibili dal binding OSM del set attivo, ordinate per etichetta IT.

    Solo il catalogo del default e' in cache (il suo contenuto e' fisso per il
    processo); quello di un set custom si ricalcola a ogni chiamata, cosi' due
    set diversi non si mescolano mai e nessun set custom resta agganciato a una
    cache globale.
    """
    return _catalogo_default() if _e_default() else _catalogo()


class AliasConflict(NamedTuple):
    """Un alias di ``tipo_poi`` che porta a due classi diverse."""

    alias: str
    first: str
    second: str

    def message(self) -> str:
        return f"alias tipo POI ambiguo {self.alias!r}: {self.first} e {self.second}"


def alias_table(
    tipi: tuple[PoiType, ...],
) -> tuple[dict[str, str], list[AliasConflict]]:
    """Chiave normalizzata (nome-classe o etichetta IT) -> nome-classe canonico,
    piu' gli alias ambigui.

    Un alias che porta gia' a una classe DIVERSA e' un conflitto, non una
    sovrascrittura silenziosa che dirotterebbe il filtro. Un'etichetta che
    coincide col proprio nome (``Cinema``, ``Silo``) e' invece innocua. Logica
    unica: la usano sia il lookup a runtime sia il controllo all'upload di un set.
    """
    table: dict[str, str] = {}
    conflicts: list[AliasConflict] = []
    for t in tipi:
        for alias in (t.terminus_class, t.label_it):
            other = table.setdefault(_key(alias), t.terminus_class)
            if other != t.terminus_class:
                conflicts.append(AliasConflict(alias, other, t.terminus_class))
    return table, conflicts


def _tabella_alias(tipi: tuple[PoiType, ...]) -> dict[str, str]:
    """Tabella degli alias; fail-fast sulle ambiguita' (``RuntimeError``)."""
    table, conflicts = alias_table(tipi)
    if conflicts:
        raise RuntimeError(conflicts[0].message())
    return table


@lru_cache(maxsize=1)
def _lookup() -> dict[str, str]:
    """Tabella degli alias del set di default (in cache, come il suo catalogo)."""
    return _tabella_alias(poi_types())


def _lookup_attivo() -> dict[str, str]:
    return _lookup() if _e_default() else _tabella_alias(poi_types())


def resolve_poi_type(raw: str | None) -> str | None:
    """Normalizza ``tipo_poi`` al nome-classe canonico.

    ``None`` o stringa vuota/di soli spazi -> ``None`` (nessun filtro). Altrimenti
    il nome-classe canonico, oppure :class:`UnknownPoiTypeError` se il valore non
    corrisponde ne' a un nome-classe ne' a un'etichetta IT del catalogo.
    """
    text = (raw or "").strip()
    if not text:
        return None
    canonical = _lookup_attivo().get(_key(text))
    if canonical is None:
        raise UnknownPoiTypeError(text)
    return canonical
