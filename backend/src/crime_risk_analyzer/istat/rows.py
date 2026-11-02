"""ISTAT rows of a POI and their format in the prompt (#345, spec 4.4).

For every (place, item) a PURE function produces the values of ``Y`` and ``Y-10``,
the national rate and the ten-year variation. The variation is an integer computed
on the COUNTS (not on the rounded rate); it is not computed if a count is below
:data:`TREND_THRESHOLD`, if a year is missing or if the item is touched by the 2016
decriminalisation: the row states the reason.

In the prompt the row is in words (#365 D7, :func:`format_row`): comparison with
the already classified Italian rate (:func:`compare_to_italy`) and trend, without
figures or codes. The figures stay in the :class:`IstatRow`: the sentence check
(:mod:`~crime_risk_analyzer.istat.figures`) recognises them and verifies the
comparison with the SAME function, the interface shows them.

Place and item names come from fixed labels (data and mapping): no text from
untrusted external sources enters the rows.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from crime_risk_analyzer.i18n.terminus_labels import label_it
from crime_risk_analyzer.istat.catalog import BREAK_ITEMS_2016
from crime_risk_analyzer.istat.data import (
    ITALY_CODE,
    TOTAL_ITEM,
    IstatData,
    Place,
    PlaceType,
    istat_data_or_none,
)
from crime_risk_analyzer.istat.mapping import HAZARD_MAPPING, MatchKind
from crime_risk_analyzer.istat.places import place_of
from crime_risk_analyzer.sources.context import active_istat

__all__ = [
    "COMPARISON_WORDING",
    "HIGHER_THRESHOLD",
    "LOWER_THRESHOLD",
    "REASON_BELOW_THRESHOLD",
    "REASON_BREAK_2016",
    "REASON_MISSING_YEAR",
    "TREND_THRESHOLD",
    "ItalyComparison",
    "IstatPoi",
    "IstatRow",
    "Link",
    "compare_to_italy",
    "format_row",
    "istat_for_poi",
    "istat_row",
    "variation_direction",
    "variation",
]

#: Below this number of offences in one of the two years the variation is not
#: computed: on small counts a percentage amplifies noise (spec 4.4).
TREND_THRESHOLD = 20
REASON_BREAK_2016 = "serie interrotta dalla depenalizzazione del 2016 (d.lgs. 7/2016)"
REASON_MISSING_YEAR = "dato mancante in uno dei due anni"
REASON_BELOW_THRESHOLD = f"meno di {TREND_THRESHOLD} delitti in uno dei due anni"

#: Comparison of the place's rate with the Italian one (#365 D2): ratio
#: ``rate / italy_rate`` at least 1.10 = higher, at most 0.90 = lower, in between
#: = similar.
ItalyComparison = Literal["piu_alto", "piu_basso", "simile"]
HIGHER_THRESHOLD = Decimal("1.10")
LOWER_THRESHOLD = Decimal("0.90")
COMPARISON_WORDING: dict[ItalyComparison, str] = {
    "piu_alto": "tasso più alto di quello italiano",
    "piu_basso": "tasso più basso di quello italiano",
    "simile": "tasso simile a quello italiano",
}

_MATCH_WORDING: dict[MatchKind, str] = {
    "esatta": "corrispondenza esatta",
    "piu_larga": "voce più ampia del rischio",
    "piu_stretta": "voce che copre solo una parte del rischio",
}
_MATCH_ORDER: tuple[MatchKind, ...] = (
    "esatta",
    "piu_larga",
    "piu_stretta",
)


class Link(BaseModel):
    """A hazard of the POI linked to the item, with its match kind (D3)."""

    model_config = ConfigDict(frozen=True)

    hazard: str
    hazard_label_it: str
    corrispondenza: MatchKind


class IstatRow(BaseModel):
    """Values of an item (or of the total) in a place, already computed."""

    model_config = ConfigDict(frozen=True)

    luogo_codice: str
    luogo_nome: str
    luogo_breve: str
    luogo_tipo: PlaceType
    voce: str
    voce_label: str
    anno: int
    anno_confronto: int
    delitti: int | None
    delitti_confronto: int | None
    tasso: float | None
    tasso_sotto_soglia: bool = False
    tasso_italia: float | None
    tasso_italia_sotto_soglia: bool = False
    variazione_pct: int | None
    motivo_senza_variazione: str | None = None
    rottura_2016: bool = False
    collegamenti: tuple[Link, ...] = ()


class IstatPoi(BaseModel):
    """ISTAT data of a POI: frame of the place (D10) and items linked to its risks."""

    model_config = ConfigDict(frozen=True)

    cornice: IstatRow
    righe: tuple[IstatRow, ...]


def variation(
    offences: int | None, comparison_offences: int | None, *, break_2016: bool
) -> tuple[int | None, str | None]:
    """Integer % variation ``Y-10 -> Y`` on the counts, or ``(None, reason)``."""
    if break_2016:
        return None, REASON_BREAK_2016
    if offences is None or comparison_offences is None:
        return None, REASON_MISSING_YEAR
    if offences < TREND_THRESHOLD or comparison_offences < TREND_THRESHOLD:
        return None, REASON_BELOW_THRESHOLD
    pct = Decimal(offences - comparison_offences) * 100 / Decimal(comparison_offences)
    return int(pct.quantize(Decimal(1), rounding=ROUND_HALF_UP)), None


def istat_row(
    data: IstatData,
    place: Place,
    item: str,
    *,
    links: tuple[Link, ...] = (),
    break_items: frozenset[str] | None = None,
) -> IstatRow:
    """Row of ``item`` (or of the total) in ``place``.

    ``break_items`` (non-comparable series) by default comes from the active set
    (#414): those of the catalog with the default set.
    """
    file = data.delitti
    current = file.valore(place.codice, item, file.anno)
    past = file.valore(place.codice, item, file.anno_confronto)
    italy = file.valore(ITALY_CODE, item, file.anno)
    if break_items is None:
        active = active_istat()
        break_items = BREAK_ITEMS_2016 if active is None else active.voci_rottura
    has_break = item in break_items
    pct, reason = variation(
        current.delitti if current else None,
        past.delitti if past else None,
        break_2016=has_break,
    )
    return IstatRow(
        luogo_codice=place.codice,
        luogo_nome=place.nome,
        luogo_breve=place.nome_breve,
        luogo_tipo=place.tipo,
        voce=item,
        voce_label=file.voci.get(item, item),
        anno=file.anno,
        anno_confronto=file.anno_confronto,
        delitti=current.delitti if current else None,
        delitti_confronto=past.delitti if past else None,
        tasso=current.tasso if current else None,
        tasso_sotto_soglia=current.tasso_sotto_soglia if current else False,
        tasso_italia=italy.tasso if italy else None,
        tasso_italia_sotto_soglia=italy.tasso_sotto_soglia if italy else False,
        variazione_pct=pct,
        motivo_senza_variazione=reason,
        rottura_2016=has_break,
        collegamenti=links,
    )


def istat_for_poi(
    lat: float, lon: float, hazards: Iterable[str], *, data: IstatData | None = None
) -> IstatPoi | None:
    """Frame and items of the POI's place linked to its hazards; ``None`` if none.

    ``None`` also outside every polygon or without data: the frame alone does not
    enter the prompt (decision of the plan: the total is context for the items, not
    a datum on its own).

    Mixed source (#414): inside ``bind``, an explicit ``data=`` replaces only the
    data; mapping and break items remain those of the active set.
    """
    active = active_istat()
    if data is not None:
        source = data
    elif active is not None:
        source = active.dati
    else:
        source = istat_data_or_none()
    if source is None:
        return None
    place = place_of(lat, lon, data=source)
    if place is None:
        return None
    table = HAZARD_MAPPING if active is None else active.mappatura
    breaks = BREAK_ITEMS_2016 if active is None else active.voci_rottura
    by_item: dict[str, list[Link]] = {}
    for hazard in dict.fromkeys(hazards):
        mapping = table.get(hazard)
        if mapping is None or mapping.voce_istat is None:
            continue
        # Invariant guaranteed by the Task 2 tests: voce_istat None <=>
        # corrispondenza None, so here corrispondenza is always set.
        assert mapping.corrispondenza is not None
        by_item.setdefault(mapping.voce_istat, []).append(
            Link(
                hazard=hazard,
                hazard_label_it=label_it(hazard),
                corrispondenza=mapping.corrispondenza,
            )
        )
    if not by_item:
        return None
    return IstatPoi(
        cornice=istat_row(source, place, TOTAL_ITEM, break_items=breaks),
        righe=tuple(
            istat_row(
                source,
                place,
                item,
                links=tuple(links),
                break_items=breaks,
            )
            for item, links in sorted(by_item.items())
        ),
    )


def _comparable_rate(value: float | None, below_threshold: bool) -> Decimal | None:
    """Exact rate (from ``str``: no floating-point errors at the edges); the
    "less than 0.1" counts as 0, a missing rate is ``None``."""
    if value is not None:
        return Decimal(str(value))
    return Decimal(0) if below_threshold else None


def compare_to_italy(row: IstatRow) -> ItalyComparison | None:
    """Rate of the place relative to the Italian one (#365 D2), ``None`` if it
    cannot be said: a missing rate or the national one at 0. It also applies to the
    total of offences (its row states it, D7).

    The project's only classification: the DATI ISTAT block uses it
    (:func:`format_row`) and the sentence check reuses it to verify the
    comparison words of the narrative.
    """
    rate = _comparable_rate(row.tasso, row.tasso_sotto_soglia)
    italy = _comparable_rate(row.tasso_italia, row.tasso_italia_sotto_soglia)
    if rate is None or italy is None or italy == 0:
        return None
    ratio = rate / italy
    if ratio >= HIGHER_THRESHOLD:
        return "piu_alto"
    if ratio <= LOWER_THRESHOLD:
        return "piu_basso"
    return "simile"


def _comparison(row: IstatRow) -> str:
    kind = compare_to_italy(row)
    if kind is None:
        return "confronto con il tasso italiano non disponibile"
    return COMPARISON_WORDING[kind]


def variation_direction(row: IstatRow) -> str | None:
    """Direction of the variation in words (#365 D7): the sign, never the value.

    ``None`` if the variation is not computed. The only source of this
    classification: the context row and the sentences of #366 use it.
    """
    if row.variazione_pct is None:
        return None
    if row.variazione_pct > 0:
        return "in crescita"
    if row.variazione_pct < 0:
        return "in calo"
    return "stabile"


def _trend(row: IstatRow) -> str:
    """Trend in words (#365 D7): the sign of the variation, never the value."""
    direction = variation_direction(row)
    if direction is None:
        reason = row.motivo_senza_variazione
        return (
            f"tendenza non calcolata: {reason}"
            if reason
            else ("tendenza non calcolata")
        )
    return f"{direction} dal {row.anno_confronto}"


def _links(links: tuple[Link, ...]) -> str:
    groups: list[str] = []
    for match in _MATCH_ORDER:
        labels = sorted({c.hazard_label_it for c in links if c.corrispondenza == match})
        if labels:
            groups.append(f"{', '.join(labels)} ({_MATCH_WORDING[match]})")
    return "; ".join(groups)


def format_row(row: IstatRow) -> str:
    """Row of the DATI ISTAT block, in words (#365 D7).

    Place and year without parentheses, Italian label of the item (never the code),
    comparison with the Italian rate (:func:`compare_to_italy`), trend in words,
    linked risks with the match kind. No counts, rates, percentages: the model
    cannot report figures it does not see; they stay in :class:`IstatRow` for the
    sentence check and for the interface.
    """
    head = f"- {row.luogo_nome}, {row.anno}: "
    if row.voce == TOTAL_ITEM:
        return (
            f"{head}totale dei delitti denunciati: {_comparison(row)}; contesto "
            "generale, non legato a un rischio."
        )
    text = f"{head}{row.voce_label}: {_comparison(row)}; {_trend(row)}."
    if row.collegamenti:
        text += f" Collegata a: {_links(row.collegamenti)}."
    return text
