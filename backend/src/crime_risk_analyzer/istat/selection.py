"""The model chooses which ISTAT data weigh, the app writes the sentences (#366).

In this mode the model does NOT write sentences about ISTAT data: at the end of
the response it lists, for each risk, the ISTAT item that supports it and how much
it weighs::

    SCELTA DATI ISTAT:
    <risk label> | <item label> | alto|medio|basso

The lines are anchored to the rows of the DATI ISTAT block
(:func:`resolve_selection`): an item or a risk that does not appear there, or that
are not linked to each other, are discarded (and counted by reason,
:class:`SelectionDiscards`).
Place, comparison with Italy and trend are composed by the app
(:func:`compose_sentence`) with the same classification as the indicator
(:func:`~crime_risk_analyzer.istat.rows.compare_to_italy`), so no internal piece of
the row (trend not computed, match kind) ends up in the text. The sentences go at
the bottom of the [ONTOLOGIA] block (:func:`insert_sentences`), in a deterministic
order (place, item, risk) that does not depend on the model.

The model's weight is only a measure (declared solidity of the data): it does not
order the sentences, it is not a danger level and it never appears in the text or
in the API responses (D9: no ranking). If the selection is lost (block missing or
rows discarded) the text stays without ISTAT sentences: there is no deterministic
fallback.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Final, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict

from crime_risk_analyzer.istat.data import TOTAL_ITEM
from crime_risk_analyzer.istat.figures import BlockSpan
from crime_risk_analyzer.istat.rows import (
    COMPARISON_WORDING,
    IstatRow,
    compare_to_italy,
    variation_direction,
)

__all__ = [
    "RULE_ISTAT_SELECTION",
    "SELECTION_HEADER",
    "WEIGHTS",
    "IstatSelection",
    "RawSelection",
    "SelectionDiscards",
    "compose_sentence",
    "compose_sentences",
    "extract_selection",
    "insert_sentences",
    "resolve_selection",
]

Weight = Literal["alto", "medio", "basso"]
#: From the most to the least solid: the weight vocabulary (it does not order the
#: sentences).
WEIGHTS: Final[tuple[Weight, ...]] = ("alto", "medio", "basso")
_WEIGHT_OF: Final[dict[str, Weight]] = {w: w for w in WEIGHTS}

#: Line the model writes before the list of selections.
SELECTION_HEADER = "SCELTA DATI ISTAT:"
_SELECTION_HEADER_RE = re.compile(
    r"^[ \t*_#]*scelta dati istat[ \t*_:#]*(?P<resto>[^\n]*)$",
    re.IGNORECASE | re.MULTILINE,
)
_LIST_MARKER = re.compile(r"^[\s\-*•]+")

#: Prompt rule: replaces rule 3c of #365 (sentences written by the model).
RULE_ISTAT_SELECTION = (
    "3c. NON scrivere frasi sui dati ISTAT: le scrive l'applicazione. Per ogni "
    "rischio che ha una voce ISTAT collegata nella sezione DATI ISTAT, indica quale "
    "voce lo sostiene e quanto e' solido il dato (voce di corrispondenza esatta, "
    "tendenza e confronto indicati). Il peso non cambia lo spazio che dai ai rischi "
    "nel testo: descrivi i rischi come sempre. In coda alla risposta, "
    f'dopo i blocchi, scrivi la riga "{SELECTION_HEADER}" e, per ogni scelta, una '
    "riga nella forma: etichetta del rischio | etichetta della voce ISTAT | peso. "
    "Le etichette sono ESATTAMENTE quelle della sezione DATI ISTAT (la voce) e del "
    "VOCABOLARIO CONTROLLATO (il rischio); il peso e' uno fra alto, medio, basso. "
    "Nel testo non nominare i dati ISTAT, non scrivere cifre ISTAT ne' codici delle "
    "voci. Non scegliere la riga del totale dei delitti"
)


class RawSelection(NamedTuple):
    """Selection line read from the response, not yet anchored to the data."""

    rischio: str
    voce: str
    peso: str


class IstatSelection(BaseModel):
    """Anchored selection: the ISTAT row, the linked risk and the weight."""

    model_config = ConfigDict(frozen=True)

    riga: IstatRow
    hazard: str
    rischio: str
    peso: Weight


class SelectionDiscards(BaseModel):
    """Selection lines discarded, by reason (measure #368/#369, in memory only)."""

    model_config = ConfigDict(frozen=True)

    malformate: int = 0
    peso_non_valido: int = 0
    voce_non_nel_blocco: int = 0
    rischio_non_collegato: int = 0
    doppione: int = 0


def _key(text: str) -> str:
    """Comparison key between labels: normalised unicode, typographic apostrophes
    and accents ignored, case and whitespace ignored."""
    base = unicodedata.normalize("NFKD", text)
    base = base.replace("’", "'").replace("‘", "'")
    without_accents = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(without_accents.casefold().split())


def _parts(line: str) -> list[str] | None:
    """Fields of a selection line, ``None`` if it is not a line of the block."""
    cleaned = _LIST_MARKER.sub("", line)
    if "|" not in cleaned:
        return None
    return [p.strip() for p in cleaned.split("|")]


def extract_selection(text: str) -> tuple[str, list[RawSelection], int]:
    """``(text without the selection block, lines read, malformed lines)``.

    The block is the header plus the lines that follow it (format ``a | b | c``,
    also as a bullet list; the first may be on the header line) and it is ALWAYS
    removed, even if the lines are not valid: it must never reach the operator. It
    ends at the first non-empty line that is not a selection line: the following
    blocks of the response remain. The weight stays raw (:func:`resolve_selection`
    validates it).
    """
    found = _SELECTION_HEADER_RE.search(text)
    if found is None:
        return text, [], 0
    lines = [(found.group("resto"), found.end())]
    cursor = found.end() + 1
    for line in text[cursor:].split("\n"):
        cursor += len(line)
        lines.append((line, cursor))
        cursor += 1
    raw: list[RawSelection] = []
    malformed = 0
    end = found.end()
    for line, line_end in lines:
        if not line.strip():
            continue
        parts = _parts(line)
        if parts is None:
            break
        end = line_end
        if len(parts) == 3 and all(parts):
            raw.append(RawSelection(parts[0], parts[1], parts[2]))
        else:
            malformed += 1
    before = text[: found.start()].rstrip()
    after = text[end:].lstrip("\n")
    return (f"{before}\n\n{after}" if after.strip() else before), raw, malformed


def resolve_selection(
    raw: Sequence[RawSelection],
    rows: Sequence[IstatRow],
    *,
    malformed: int = 0,
) -> tuple[list[IstatSelection], SelectionDiscards]:
    """Anchor the selections to the block's ``rows``; discard (counting) those that
    do not hold.

    Only a selection holds if its weight is alto/medio/basso (case and final period
    ignored), its item is a row of the block (never the total) and its risk is one
    of those linked to that item. Each (place, item, risk) counts once, the first.
    Each discarded line counts for a single reason.
    """
    selections: list[IstatSelection] = []
    seen: set[tuple[str, str, str]] = set()
    invalid_weight = item_not_in_block = risk_not_linked = duplicate = 0
    for g in raw:
        weight = _WEIGHT_OF.get(_key(g.peso).strip(" .*_"))
        if weight is None:
            invalid_weight += 1
            continue
        with_item = [
            r
            for r in rows
            if r.voce != TOTAL_ITEM and _key(r.voce_label) == _key(g.voce)
        ]
        if not with_item:
            item_not_in_block += 1
            continue
        linked = [
            (r, c)
            for r in with_item
            for c in r.collegamenti
            if _key(c.hazard_label_it) == _key(g.rischio)
        ]
        if not linked:
            risk_not_linked += 1
            continue
        new = 0
        for row, c in linked:
            key = (row.luogo_codice, row.voce, c.hazard)
            if key in seen:
                continue
            seen.add(key)
            new += 1
            selections.append(
                IstatSelection(
                    riga=row, hazard=c.hazard, rischio=c.hazard_label_it, peso=weight
                )
            )
        if not new:
            duplicate += 1
    discards = SelectionDiscards(
        malformate=malformed,
        peso_non_valido=invalid_weight,
        voce_non_nel_blocco=item_not_in_block,
        rischio_non_collegato=risk_not_linked,
        doppione=duplicate,
    )
    return selections, discards


def compose_sentence(selection: IstatSelection) -> str | None:
    """Sentence of the selection, or ``None`` if there is neither comparison nor
    trend to say.

    No figures (the interface shows them) and no match kind between item and risk:
    the item and the risk can both be read in the sentence. The trend is only said
    if computed.
    """
    row = selection.riga
    kind = compare_to_italy(row)
    parts: list[str] = []
    if kind is not None:
        parts.append(f"un {COMPARISON_WORDING[kind]}")
    direction = variation_direction(row)
    if direction is not None:
        parts.append(f"un andamento {direction} dal {row.anno_confronto}")
    if not parts:
        return None
    return (
        f"Secondo i dati ISTAT del {row.luogo_nome} ({row.anno}), la voce "
        f"«{row.voce_label}» (rischio: {selection.rischio}) ha {' e '.join(parts)}."
    )


def compose_sentences(selections: Sequence[IstatSelection]) -> list[str]:
    """Sentences of the selections in deterministic order (place, item, risk).

    The order does not depend on the weight or on the order of the model's lines: an
    order decided by the model would read like a ranking (D9).
    """
    ordered = sorted(
        selections, key=lambda s: (s.riga.luogo_codice, s.riga.voce, s.hazard)
    )
    sentences = (compose_sentence(s) for s in ordered)
    return [s for s in sentences if s is not None]


def insert_sentences(
    text: str, spans: Sequence[BlockSpan], sentences: Sequence[str]
) -> str:
    """Put ``sentences`` at the bottom of the [ONTOLOGIA] block of ``text`` (``spans``
    are its blocks); if there is none, open one at the end."""
    if not sentences:
        return text
    prose = " ".join(sentences)
    ontology = next((s for s in spans if s.campo == "ontologia"), None)
    if ontology is None:
        return f"{text.rstrip()}\n\nRischi da ontologia [ONTOLOGIA]\n{prose}"
    body = text[ontology.inizio : ontology.fine]
    full = body.rstrip()
    return (
        f"{text[: ontology.inizio]}{full}\n{prose}"
        f"{body[len(full) :]}{text[ontology.fine :]}"
    )
