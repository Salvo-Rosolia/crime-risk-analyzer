"""Catalogo dei tipi POI selezionabili e normalizzazione di ``tipo_poi`` (#143).

Il catalogo e' l'insieme delle classi TERMINUS che il sistema puo' davvero
produrre: i valori distinti di
:data:`~crime_risk_analyzer.sparql_module.osm_mapping.OSM_TO_TERMINUS`. Il
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

from pydantic import BaseModel, ConfigDict

from crime_risk_analyzer.i18n.terminus_labels import label_it
from crime_risk_analyzer.sparql_module.osm_mapping import OSM_TO_TERMINUS


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


@lru_cache(maxsize=1)
def poi_types() -> tuple[PoiType, ...]:
    """Classi TERMINUS producibili dal mapping, ordinate per etichetta IT.

    Ordinamento per ``casefold`` dell'etichetta (spareggio sul nome-classe):
    deterministico e indipendente dal locale del processo.
    """
    entries = [
        PoiType(terminus_class=cls, label_it=label_it(cls))
        for cls in set(OSM_TO_TERMINUS.values())
    ]
    return tuple(
        sorted(entries, key=lambda t: (t.label_it.casefold(), t.terminus_class))
    )


@lru_cache(maxsize=1)
def _lookup() -> dict[str, str]:
    """Chiave normalizzata (nome-classe o etichetta IT) -> nome-classe canonico.

    Fail-fast sulle ambiguita': un alias che porta gia' a una classe DIVERSA e'
    un errore esplicito, non una sovrascrittura silenziosa che dirotterebbe il
    filtro. Un'etichetta che coincide col proprio nome (``Cinema``, ``Silo``) e'
    invece innocua.
    """
    table: dict[str, str] = {}
    for t in poi_types():
        for alias in (t.terminus_class, t.label_it):
            other = table.setdefault(_key(alias), t.terminus_class)
            if other != t.terminus_class:
                msg = f"alias tipo POI ambiguo {alias!r}: {other} e {t.terminus_class}"
                raise RuntimeError(msg)
    return table


def resolve_poi_type(raw: str | None) -> str | None:
    """Normalizza ``tipo_poi`` al nome-classe canonico.

    ``None`` o stringa vuota/di soli spazi -> ``None`` (nessun filtro). Altrimenti
    il nome-classe canonico, oppure :class:`UnknownPoiTypeError` se il valore non
    corrisponde ne' a un nome-classe ne' a un'etichetta IT del catalogo.
    """
    text = (raw or "").strip()
    if not text:
        return None
    canonical = _lookup().get(_key(text))
    if canonical is None:
        raise UnknownPoiTypeError(text)
    return canonical
