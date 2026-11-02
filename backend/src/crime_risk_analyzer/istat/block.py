"""ISTAT DATA block of the user_content (#345, spec 4.4-4.5).

Zone: first the frames (one per place with at least one item), then the items, once
per (place, item), sorted by decreasing number of POIs involved (ties: item code,
then place code). If the block does not fit the limit, items are dropped starting
from those with FEWER POIs involved; the frames go last (they drop with the last
item of their place) and a note says how many items were left out.

POI: frame and items of that point.

The rows are in words (#365 D7, :func:`~crime_risk_analyzer.istat.rows.format_row`):
the number of POIs involved only decides the order and the cut, it does not appear
in the text.

Both blocks only include items with at least :data:`TREND_THRESHOLD` offences in
the latest year (#365 D2, same threshold as the Detail): on 3 bank robberies or a
missing count the narrative has nothing to weigh. If no item remains there is no
block (the frame alone does not enter).

The token estimate comes from the caller (``generation._estimate_tokens``): this
module does not import ``rag`` to avoid creating cycles.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from crime_risk_analyzer.istat.rows import (
    TREND_THRESHOLD,
    IstatPoi,
    IstatRow,
    format_row,
)

__all__ = [
    "ISTAT_DATA_HEADER",
    "IstatBlock",
    "has_istat_rows",
    "istat_block_for_poi",
    "istat_block_for_zone",
    "truncation_note",
]

#: First line of the block: tells the model what the data is and whose it is.
ISTAT_DATA_HEADER = (
    "DATI ISTAT (delitti denunciati dalle forze di polizia all'autorita' "
    "giudiziaria; dati del comune capoluogo o della provincia indicati a inizio "
    "riga, non della zona ne' dei singoli POI):"
)


class IstatBlock(BaseModel):
    """Text of the block and the rows actually rendered (for the figures check)."""

    model_config = ConfigDict(frozen=True)

    testo: str = ""
    righe: tuple[IstatRow, ...] = ()
    voci_tagliate: int = 0


def truncation_note(n: int) -> str:
    """Transparency line when ``n`` items are left out because of the budget."""
    if n == 1:
        return "NB: per limiti di lunghezza 1 voce ISTAT non e' riportata."
    return f"NB: per limiti di lunghezza {n} voci ISTAT non sono riportate."


def _in_block(row: IstatRow) -> bool:
    """The item has enough offences in the latest year to enter the block."""
    return row.delitti is not None and row.delitti >= TREND_THRESHOLD


def _istat(poi: Mapping[str, Any]) -> IstatPoi | None:
    value = poi.get("istat")
    return value if isinstance(value, IstatPoi) and value.righe else None


def has_istat_rows(pois: Sequence[Mapping[str, Any]]) -> bool:
    """True if at least one POI carries ISTAT rows."""
    return any(_istat(poi) is not None for poi in pois)


def _aggregate(
    pois: Sequence[Mapping[str, Any]],
) -> tuple[list[IstatRow], list[tuple[IstatRow, int]]]:
    frames: dict[str, IstatRow] = {}
    items: dict[tuple[str, str], IstatRow] = {}
    involved: dict[tuple[str, str], set[str]] = {}
    for poi in pois:
        istat = _istat(poi)
        if istat is None:
            continue
        frames.setdefault(istat.cornice.luogo_codice, istat.cornice)
        for row in filter(_in_block, istat.righe):
            key = (row.luogo_codice, row.voce)
            existing = items.get(key)
            if existing is None:
                items[key] = row
            else:
                already = {c.hazard for c in existing.collegamenti}
                new = tuple(c for c in row.collegamenti if c.hazard not in already)
                items[key] = existing.model_copy(
                    update={"collegamenti": existing.collegamenti + new}
                )
            involved.setdefault(key, set()).add(str(poi.get("poi_id", "")))
    order = sorted(items, key=lambda k: (-len(involved[k]), k[1], k[0]))
    return list(frames.values()), [(items[k], len(involved[k])) for k in order]


def _render(
    frames: list[IstatRow], items: list[tuple[IstatRow, int]], cut: int
) -> tuple[str, tuple[IstatRow, ...]]:
    places = {row.luogo_codice for row, _ in items}
    rendered_frames = [f for f in frames if f.luogo_codice in places]
    lines = [ISTAT_DATA_HEADER]
    lines.extend(format_row(f) for f in rendered_frames)
    lines.extend(format_row(row) for row, _ in items)
    if cut:
        lines.append(truncation_note(cut))
    return "\n".join(lines), (*rendered_frames, *(row for row, _ in items))


def istat_block_for_zone(
    pois: Sequence[Mapping[str, Any]],
    *,
    estimate_tokens: Callable[[str], int],
    token_limit: int | None,
) -> IstatBlock:
    """Zone block over ``pois`` (already those included in the prompt)."""
    frames, items = _aggregate(pois)
    total = len(items)
    while items:
        text, rows = _render(frames, items, total - len(items))
        if token_limit is None or estimate_tokens(text) <= token_limit:
            return IstatBlock(testo=text, righe=rows, voci_tagliate=total - len(items))
        items = items[:-1]
    return IstatBlock(voci_tagliate=total)


def istat_block_for_poi(istat: IstatPoi | None) -> IstatBlock:
    """Block of a single POI: frame and items, without a POI count."""
    items = tuple(filter(_in_block, istat.righe)) if istat is not None else ()
    if istat is None or not items:
        return IstatBlock()
    rows = (istat.cornice, *items)
    text = "\n".join([ISTAT_DATA_HEADER, *(format_row(r) for r in rows)])
    return IstatBlock(testo=text, righe=rows)
