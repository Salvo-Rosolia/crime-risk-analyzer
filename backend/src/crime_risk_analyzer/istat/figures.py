"""Check of the narrative's sentences with the ISTAT data in the prompt (#345, #365).

NEW mechanism of #345: for the first time a generated sentence can be removed after
generation. It only runs when the prompt contained the DATI ISTAT block. Since #365
the model uses the ISTAT data in words inside the [ONTOLOGIA] block and does not
write figures (the interface shows them): no block is any longer the place of the
ISTAT figures, and the check verifies what the sentence says about the datum.

1. Split into sentences that does not break numbers ("3.016", "1.162,7"): it splits
   after ``.!?`` followed by a space and at every newline; the ``;`` does NOT end
   the sentence; list markers at the start of a line ("1.", "-", "*") are not part
   of the sentence. (The M1 splitter, :func:`split_sentences_m1`, splits at every
   period and must not be reused for the filter; it is only needed for point 8.)
   The prose written on the same line as the label, after the token (``Dati
   statistici ISTAT [ISTAT]: nel Comune ...``), belongs to the block that the
   label opens: only the check moves it, the block parser (which feeds M1) stays
   as it is. Common abbreviations (``d.lgs.``, ``art.``, ``n.``, ``es.``,
   ``ecc.``, ``cfr.``) do not end the sentence: the DATI ISTAT rows themselves
   write "(d.lgs. 7/2016)" (R4, review 2).
2. Numbers normalised the Italian way: ``.`` followed by groups of three digits is
   the thousands separator (like the NBSP and the narrow NNBSP), otherwise it is
   decimal; ``,`` is decimal; ``−`` and ``–`` (en dash) count as ``-``; a ``-`` (or
   ``–``) between two digits is a range ("2014-2024" are two years, not a sign);
   "per cento"/"percento" after a number counts as ``%``. The normal space counts
   as a thousands separator only if the joined number is allowed or if its parts
   are not all allowed: "134 169" stays 134.169, but "negli ultimi 10 340 furti"
   are 10 and 340 (R8, review 2). An ``N/YYYY`` reference ("d.lgs. 7/2016") is not a
   number to check.
3. Allowed: all the numbers of the user_content (DATI ISTAT block included) EXCEPT
   those of the user's question (untrusted input: it must never put a figure on the
   list, R2 review 2), plus the fixed list (100.000, ``Y``, ``Y-10``, 0,1), the
   width of the period ``Y - Y_comparison`` ("negli ultimi 10 anni"), which without
   ``%`` is any number and never an ISTAT figure, and the ISTAT figures of the
   rows: the block in words (#365 D7) no longer carries them, but an ISTAT figure
   written by the model must be recognised as such and not as an invented number.
   ISTAT figures: counts, rates, national rate of the rows (the
   :class:`~crime_risk_analyzer.istat.rows.IstatRow`, not the text of the block),
   plus the variations but ONLY when written with ``%`` (a number without ``%`` may
   coincide by chance with the absolute value of a variation -- e.g. "10" in
   "negli ultimi 10 anni" -- and must not be mistaken for an ISTAT figure); in any
   case except those that also appear in the context outside the block, in the
   block itself or in the fixed list: the block in words only writes years, the
   threshold of 20 offences and "del 2016", which are never ISTAT figures even if
   they coincide with a rate or a count (#385); for the context it cannot be said
   what they refer to.
4. A sentence "talks about the ISTAT datum" if it names "ISTAT" or the "delitti
   denunciati", or contains an ISTAT figure. It also talks about it if it names an
   item of the rows (or a linked risk, as in C1) together with a marker: "tasso",
   "voce", "dal <comparison year>", the average, the Italian or national datum or
   rate, "quello italiano", "rispetto all'Italia", "che in Italia", "resto
   d'Italia", also in the plural (#386: "tassi", "dati", "quelli italiani", "valori"
   and "livelli" Italian or national; "a livello nazionale" in the singular no, B1):
   "I furti hanno un tasso piu' alto e sono in calo dal 2014". Without an item or
   risk the Italian datum is not enough (#385): "Il quartiere ha un'eta' media
   superiore alla media nazionale" stays. "tasso"/"tassi" only counts followed
   shortly by a comparison or as "tasso di/dei <item>", "voce" only as "la/questa
   voce", "voce piu' ampia/stretta", "voce ... coincide/corrisponde"
   (fix 4: "Area ad alto tasso di criminalita'" is a vulnerability of the ontology,
   not an ISTAT datum). Markdown (``**``, ``_``) is stripped before looking for
   labels and places.
   The labels of items and linked risks are recognised up to inflection (#392): in
   every word of at least 4 letters the last vowel (with the "i" of -io/-ia/-ie and
   the "h" of -chi/-che) does not count, so "i danneggiamenti seguiti da incendio"
   names the item "danneggiamento seguito da incendio" and "il furto" the item
   "furti". The longest label (on a tie the item before the risk) consumes its piece
   of text: there a shorter label contained in it is no longer searched
   ("danneggiamenti", "incendi"), which stays named only if the sentence also writes
   it elsewhere; "il furto in gioielleria" names the risk, not the item "furti".
   Limits: irregular forms ("uomo/uomini") and accented endings are not
   recognised; two labels with the same stems are confused (in the real catalog only
   "rapina in banca" and "rapine in banca", risk and item BANKROB).
   The place name alone is not enough (R1, review 2): "A Roma la folla aumenta le
   occasioni di furti" talks about the risk, not the statistic, and stays. A
   sentence inside a residual ``[ISTAT]`` always talks about it (C3); its label line
   never does (it names ISTAT but says nothing about the datum). A trend or
   comparison word with an item (or a linked risk) is not enough, even with the
   inherited place (#385): "I furti sono favoriti dalla crescita del turismo" or "Il
   furto di beni resta stabile come vulnerabilita'" after an ISTAT sentence stay.
   Only exception (C-2): in the list introduced by an ISTAT sentence ending in
   ":", the short line "<item or risk>: <trend or comparison>" (at most 6 words per
   part) talks about the datum: "- furti: in crescita;" after "I dati ISTAT del
   Comune di Roma (2024) indicano:". The list stays such as long as the place is
   inherited and no ISTAT sentence with a new explicit place closes it.
5. Rules, in order (the first that fires is the reason):

   - ``numero_non_ammesso``: a number outside the allowed ones;
   - ``cifra_istat_fuori_blocco``: an ISTAT figure, in ANY block (#365: also inside
     an ``[ISTAT]`` written by mistake; the name of the reason is that of #345);
   - ``luogo_mancante`` (#365): a sentence that talks about the ISTAT datum does not
     name a place of the rows (in full, "Comune di Roma", or by short name) and does
     not inherit one. It inherits the place of the previous ISTAT sentence, kept,
     of the same paragraph (list included): "I dati ISTAT del Comune di Roma ...:"
     followed by the items. A new place replaces the inherited one; it is not
     inherited across a blank line, at a block change or from a removed sentence
     (for the ISTAT sentences of M1 it is instead, point 8);
     an introduction ending in ":" however passes the place to the list that follows
     it even across blank lines, as long as the list continues (fix 6).
     The ``luogo`` field only says whether the place is explicit, ``luogo_ereditato``
     whether it is inherited;
   - ``direzione_contraria``: in a sentence that talks about the ISTAT datum, trend
     words ("in aumento", "in calo", "scesi", "si sono ridotti", "stabile",
     "in ripresa" and "raddoppiati" (= growing, #386)...)
     contrary to the sign of the variation of any of the named items (C-1);
     "stabile" is right only with variation 0, as the block writes it (C-3). Causal
     or adjectival forms ("aumenta le occasioni", "ridotta", "riduzione", the "sale"
     giochi) do not count. If there is no item or an item has no computed trend
     (broken series, missing year, below threshold) the direction cannot be verified
     and the sentence is removed all the same, with this reason;
   - ``confronto_contrario`` (#365): in a sentence that talks about the ISTAT datum,
     a comparison word with the Italian datum ("sopra/sotto la media", "al di
     sopra/sotto", "piu' alto/basso/elevato/contenuto/frequente/diffuso/numeroso",
     "piu' raro/ridotto" and "meno alto/elevato/frequente/diffuso/numeroso", "meno
     che" (= piu' basso), "meno basso/raro", "piu' che" (= piu' alto),
     "superiore/inferiore", "maggiore/minore", "supera", "simile", "in linea",
     "pari a") that does not agree, for any of the named items (C-1), with the
     classification of the row
     (:func:`~crime_risk_analyzer.istat.rows.compare_to_italy`, the same one that
     writes the comparison in the DATI ISTAT block). The word only counts if
     followed shortly, in the same clause, by the term of comparison (B2, C-4): the
     average, (dato|tasso|valore|livello|quello) italiano or nazionale, also in the
     plural (#386), l'Italia ("che in Italia", "del resto d'Italia");
     not the adjective alone ("una minore presenza di turisti italiani"),
     or if shortly before there is "tasso" or "tassi" ("un tasso piu' alto": the
     implicit term is Italy): "reati simili", "piano superiore", "in linea con
     l'ontologia" are not comparisons. A sentence is removed with the same reason
     if it has no item, if the item has no classification (a missing rate, the
     national one at 0) or if it has comparisons of different classes.

   Negation (#386): "non", "ne'", "mai", "nessun(o/a)" at most 3 words before the
   trend or comparison word, in the same clause, inverts its value ("non solo" does
   not; a "non" after the word, pleonastic as in "di quanto non sia", does not
   count). "Non e' piu' alto di quello italiano" is consistent with the classes
   "simile" and "piu' basso", not with "piu' alto"; "non sono (piu') in calo" is
   consistent if the real trend is not a decline. A negated trend or comparison on
   an item without trend or classification stays unverifiable and is removed; the
   same word negated and not negated in the same sentence is not verified on the
   trend and is a mixed comparison. The ``direzione_negata`` and
   ``confronto_negato`` fields of the outcome report it. Limit: a nearby negation
   that does not govern the word ("i furti non denunciati sono in calo") inverts it
   all the same and the sentence is removed.

   The item is the one named by the label (or the code); if the sentence has a
   trend or a comparison but no label, the Italian name of the risks linked to the
   items is searched (C1: "il furto di beni ha un tasso piu' alto..."); if still
   none, "delitti denunciati" counts as the total of offences.
   Direction and comparison must hold for ALL the named items (C-1, also those
   resolved by a risk linked to several items) and use the values of the named
   place: if the sentence names a place in full the values of THAT place for the
   item apply, and if it names more than one in full ("nel Comune di Bari e nella
   Provincia di Bari i furti sono in crescita") it must hold for ALL (#386), also in
   the sentences that inherit those places. The short name ("Roma") applies to all
   the places of the rows with that name (comune and provincia) and for an item it
   is enough that one agrees (R6, review 2). Declared limit: "a Bari i furti sono in
   crescita" also passes when in the comune they are declining, if they are growing
   in the provincia. A sentence with words of different trends is not verified on
   that axis.
6. Numbers in words ("il doppio") and the item codes written by the model ("THEFT")
   are counted for the evaluation, not removed.
7. Filtered text (C5): if all the sentences of a residual ``[ISTAT]`` are removed
   its label line is removed too, which would remain orphaned; no blank lines at the
   start nor gaps of several blank lines left by the cuts.
8. ISTAT sentences for M1 (#369): the measured block is split into the M1 sentences
   (:func:`split_sentences_m1`, not those of point 1) and the ones that talk about the
   datum are marked (point 4). The place is inherited as in point 5 but also from a
   sentence that the filter removes: so the outcome does not depend on the filter.
   The prose written on the label line also passes it, which M1 does not measure;
   the number of a "1." marker, which M1 detaches from the item, does not count as a
   sentence and follows the item: it is an ISTAT sentence if the item is. M1
   (``eval.metrics``) excludes from the denominator those that name neither a POI
   nor a risk; the others it measures as always. The M1 sentences split numbers
   ("3.016") and abbreviations ("d.lgs."): a piece without the words of point 4 does
   not talk about the datum and stays measured, as in every arm.

The raw text remains available: the outcome carries the filtered text (what the
operator sees) and the offsets in the raw text of the ISTAT sentences for M1.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict

from crime_risk_analyzer.istat.block import IstatBlock
from crime_risk_analyzer.istat.data import TOTAL_ITEM
from crime_risk_analyzer.istat.rows import IstatRow, ItalyComparison, compare_to_italy

__all__ = [
    "Block",
    "BlockSpan",
    "CheckOutcome",
    "CheckedSentence",
    "Comparison",
    "Number",
    "Reason",
    "apply_check",
    "check_figures",
    "comparison_of",
    "direction_of",
    "extract_numbers",
    "measured_block",
    "named_items",
    "names_item_of_rows",
    "split_sentences",
    "split_sentences_m1",
    "values_of_text",
]

Block = Literal[
    "overview", "intestazione", "ontologia", "contesto", "speculativo", "istat"
]
Reason = Literal[
    "numero_non_ammesso",
    "cifra_istat_fuori_blocco",
    "luogo_mancante",
    "direzione_contraria",
    "confronto_contrario",
]
Direction = Literal["su", "giu", "stabile", ""]
#: Comparison with the Italian datum written in the sentence: ``""`` if none,
#: ``"misto"`` if the sentence uses different classes (not verifiable, B2).
Comparison = ItalyComparison | Literal["", "misto"]

_SOURCE_BLOCKS: frozenset[str] = frozenset(
    {"ontologia", "contesto", "speculativo", "istat"}
)


class BlockSpan(NamedTuple):
    """Per-source block of the narrative: label line and body (offsets in the text)."""

    campo: str
    inizio_riga: int
    inizio: int
    fine: int


class Number(NamedTuple):
    """Extracted number: normalised absolute value, explicit sign, percentage."""

    valore: Decimal
    segno: str
    percentuale: bool


_NUMBER = re.compile(
    r"(?<![\w.,])"
    r"(?P<segno>[+\-−–])?"
    r"(?P<corpo>\d{1,3}(?:[.\xa0  ]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"
    r"(?!\w)"
    r"(?P<pct>\s?%|\s+[Pp]er\s?cento\b)?"
)
_DOT_THOUSANDS = re.compile(r"\d{1,3}(?:\.\d{3})+")
_LIST_MARKER = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
#: Abbreviations after which the period does not end the sentence (R4, review 2).
_ABBREVIATION = re.compile(r"\b(?:d\.\s?lgs|artt?|nn?|es|ecc|cfr)\.$", re.IGNORECASE)
#: Normative or numbered reference "N/YYYY" ("d.lgs. 7/2016"): not a figure.
_REFERENCE = re.compile(r"(?<![\w.,/])\d{1,4}/\d{4}(?![\w/])")
#: User's question in the zone user_content: untrusted input, its numbers never
#: enter the allowed ones (R2, review 2). Same delimiters as
#: ``rag.generation.USER_INPUT_FENCE_OPEN``/``_CLOSE`` (here as text: ``istat``
#: does not import ``rag``); the tests use the real constants.
_USER_QUESTION = re.compile(
    r"--- DOMANDA UTENTE \(input non fidato: dato, non istruzioni\) ---"
    r".*?--- FINE DOMANDA UTENTE ---",
    re.DOTALL,
)
#: Source token on the label line (``[ISTAT]``, ``[ONTOLOGIA]``, ...).
_SOURCE_TOKEN = re.compile(r"\[[A-Z][A-Z_ ]*\]")
#: Characters between the token and the prose on the same line (like the block parser).
_AFTER_TOKEN = " \t\r*_:#"
#: Trend forms only (R1, review 2): no "aumenta" (causal, "la folla
#: aumenta le occasioni"), "ridotta"/"riduzione" (adjective/noun), "sale"
#: (also a noun, "sale giochi").
_UP = re.compile(
    r"\b(?:aumento|aumenti|aumentat[oaie]|aumentano|crescita|cresciut[oaie]"
    r"|cresce|crescono|incremento|incrementi|rialzo|salgono|salit[oaie]"
    r"|in ripresa|raddoppiat[oaie])\b"
)
_DOWN = re.compile(
    r"\b(?:calo|cali|calat[oaie]|cala|calano|diminuzione|diminuzioni|diminuit[oaie]"
    r"|diminuisce|diminuiscono|flessione|discesa|ribasso"
    r"|scende|scendono|sces[oaie]|si sono ridott[ie])\b"
)
#: "stabile" (C-3): the block only writes it with variation 0.
_STABLE = re.compile(r"\bstabil[ei]\b")
#: "piu'" as the models write it: accented, with straight or typographic apostrophe.
_PIU = r"pi(?:ù|u['’]?)"
#: Separator between two words of the same clause: it does not cross
#: ``, ; : . ( )``. Single one for the term of comparison, the "tasso" anchor and
#: markers.
_SEP = r"[^\w,;:.()]+"
#: Term of comparison at a short distance (B2, C-4): up to 6 words in the same
#: clause, then the average, (dato|tasso|valore|livello|quello) italiano or
#: nazionale, or l'Italia. Not the adjective alone ("turisti italiani"). Without a
#: term, "reati simili", "piano superiore" or "in linea con l'ontologia" would be
#: comparisons.
_COMPARATOR = (
    rf"(?:{_SEP}\w+){{0,6}}?{_SEP}"
    r"(?:media\b|(?:dat[oi]|tass[oi]|valor[ei]|livell[oi]|quell[oaie])\s+"
    r"(?:italian[oaie]|nazional[ei])\b|italia\b)"
)
#: Anchor of the implicit comparison: "un tasso piu' alto" without saying of what
#: means with respect to Italy (the only comparison of the rows). "tasso" must be
#: shortly before (at most 3 words) in the same clause. The same piece acts as
#: ISTAT marker (fix 4, :func:`_markers`).
_RATE_BEFORE = rf"\btass[oi](?:{_SEP}\w+){{0,3}}?{_SEP}"
_COMPARISON_WORDS: dict[ItalyComparison, str] = {
    "piu_alto": (
        rf"al di sopra|sopra|{_PIU}\s+(?:alt|elevat|frequent|diffus|numeros)[oaie]"
        rf"|{_PIU}\s+che|meno\s+(?:bass|rar)[oaie]"
        r"|superior[ei]|maggior[ei]|supera|superano"
    ),
    "piu_basso": (
        rf"al di sotto|sotto|{_PIU}\s+(?:bass|contenut|rar|ridott)[oaie]"
        r"|meno\s+(?:alt|elevat|frequent|diffus|numeros)[oaie]|meno\s+che"
        r"|inferior[ei]|minor[ei]"
    ),
    "simile": r"simil[ei]|in linea|pari a",
}
_ALL_COMPARISONS = "|".join(f"(?:{p})" for p in _COMPARISON_WORDS.values())
#: Comparison words with the Italian datum (#365 D3): the three classes of the row.
#: They count followed by the term of comparison (B2) or preceded by "tasso".
_COMPARISONS: dict[ItalyComparison, re.Pattern[str]] = {
    kind: re.compile(rf"\b(?:{words})\b{_COMPARATOR}|{_RATE_BEFORE}(?:{words})\b")
    for kind, words in _COMPARISON_WORDS.items()
}
#: The comparison word alone, to find it inside a comparison with "tasso" in front.
_COMPARISON_WORD: dict[ItalyComparison, re.Pattern[str]] = {
    kind: re.compile(rf"\b(?:{words})\b") for kind, words in _COMPARISON_WORDS.items()
}
#: Negation in front of the trend or comparison word (#386): in the same
#: clause and at most 3 words before ("non e' piu' alto", "non sono piu' in
#: calo", "nessun calo"). "non solo" does not negate; a "non" after the word
#: (pleonastic, "di quanto non sia") does not count.
_NEGATION = re.compile(
    rf"\b(?:non(?!{_SEP}solo\b)|né|ne'|mai|nessun[oa]?)(?:{_SEP}\w+){{0,3}}{_SEP}$"
)
_REPORTED_OFFENCES = r"\bdelitti denunciati\b"
#: The total named as "delitti denunciati" (without another item).
_IMPLICIT_TOTAL = re.compile(_REPORTED_OFFENCES)
#: When a sentence talks about the ISTAT datum on its own (#365 D3; R1: the place
#: alone is not enough).
_TALKS_ABOUT_ISTAT = re.compile(rf"\bistat\b|{_REPORTED_OFFENCES}")
#: The Italian datum as a term of comparison: it is a marker, valid only with an
#: item or a linked risk (#385: "un'eta' media superiore alla media
#: nazionale" does not talk about the datum). B1: "livello"/"valore" nazionale no
#: ("di interesse a livello nazionale").
_ITALIAN_FIGURE = (
    r"\b(?:media|dat[oi]|tass[oi]|valori|livelli)\s+(?:italian[oaie]|nazional[ei])\b"
    r"|\bquell[oaie]\s+italian[oaie]\b"
    r"|\brispetto all'\s?italia\b|\bche in italia\b|\bresto d'\s?italia\b"
)
_IN_WORDS = re.compile(
    r"\b(?:mille|duemila|tremila|quattromila|cinquemila|diecimila|centomila"
    r"|milion[ei]|miliard[oi]|doppio|triplo|met[aà]|raddoppiat\w*|triplicat\w*"
    r"|dimezzat\w*)\b"
)
#: How the model names the frame: "totale dei delitti" (reported or not).
_TOTAL_LABEL = "totale dei delitti"


class CheckedSentence(BaseModel):
    """A sentence of the narrative and the verdict of the check."""

    model_config = ConfigDict(frozen=True)

    testo: str
    blocco: Block
    inizio: int
    fine: int
    #: ``None`` = kept; otherwise the reason why it is removed.
    motivo: Reason | None = None
    #: Numbers outside the fixed list.
    cifre: int = 0
    #: ISTAT figures written by the model (#365: always removed, expected 0).
    cifre_istat: int = 0
    voci: tuple[str, ...] = ()
    #: The sentence talks about the ISTAT datum (point 4 of the module).
    parla_di_istat: bool = False
    #: The sentence EXPLICITLY names at least one place of the rows.
    luogo: bool = False
    #: The sentence talks about the datum without naming a place and uses the one
    #: said before in the same paragraph (fix 3).
    luogo_ereditato: bool = False
    #: Codes of the places the sentence was verified with (explicit or
    #: inherited); empty if none.
    luoghi: tuple[str, ...] = ()
    direzione: Direction = ""
    #: The trend is negated ("non sono in calo", #386).
    direzione_negata: bool = False
    #: ``None`` if the sentence does not use direction words on an item with a
    #: variation.
    direzione_coerente: bool | None = None
    confronto: Comparison = ""
    #: The comparison is negated ("non e' piu' alto di quello italiano", #386).
    confronto_negato: bool = False
    #: ``None`` if the sentence does not compare a classified item with the Italian
    #: datum.
    confronto_coerente: bool | None = None


class CheckOutcome(BaseModel):
    """Outcome of the check on a narrative."""

    model_config = ConfigDict(frozen=True)

    frasi: tuple[CheckedSentence, ...]
    testo_filtrato: str
    #: Offsets in the raw text of the sentences of the block measured by M1 that talk
    #: about the ISTAT datum (#369, point 8 of the module). They are M1 sentences
    #: (:func:`split_sentences_m1`), not the filter's; M1 excludes those that name
    #: neither a POI nor a risk.
    frasi_istat_m1: tuple[tuple[int, int], ...]
    numeri_in_lettere: int
    righe: tuple[IstatRow, ...]
    #: Codes of the items of the rows written by the model (uppercase, whole
    #: word): they are counted for the evaluation, they do not remove the sentence.
    codici_voce: int = 0

    @property
    def frasi_scartate(self) -> int:
        """How many sentences the filter removed."""
        return sum(1 for f in self.frasi if f.motivo is not None)


def _value(body: str) -> Decimal:
    cleaned = body.replace("\xa0", "").replace("\u202f", "").replace(" ", "")
    if "," in cleaned:
        integer, decimals = cleaned.split(",", 1)
        return Decimal(f"{integer.replace('.', '')}.{decimals}")
    if _DOT_THOUSANDS.fullmatch(cleaned):
        return Decimal(cleaned.replace(".", ""))
    return Decimal(cleaned)


def _space_parts(body: str, allowed: set[Decimal] | None) -> list[Decimal] | None:
    """The parts of ``body`` separated by normal spaces, if they are to be read as
    distinct numbers: the joined number is not allowed and each part is (R8,
    review 2)."""
    if allowed is None or " " not in body or _value(body) in allowed:
        return None
    parts = [_value(p) for p in body.split(" ")]
    return parts if all(p in allowed for p in parts) else None


def extract_numbers(text: str, allowed: set[Decimal] | None = None) -> list[Number]:
    """Numbers of a sentence or a line (the initial list marker does not count).

    With ``allowed``, a number with the normal space as thousands separator that is
    not allowed but whose parts all are is read as distinct numbers
    ("negli ultimi 10 340 furti" -> 10 and 340). ``N/YYYY`` references do not count.
    """
    text = _LIST_MARKER.sub("", text, count=1)
    text = _REFERENCE.sub(" ", text)
    numbers: list[Number] = []
    for m in _NUMBER.finditer(text):
        sign = (m.group("segno") or "").replace("−", "-").replace("–", "-")
        pct = m.group("pct") is not None
        parts = _space_parts(m.group("corpo"), allowed)
        if parts is None:
            numbers.append(Number(_value(m.group("corpo")), sign, pct))
            continue
        last = len(parts) - 1
        numbers.extend(
            Number(v, sign if i == 0 else "", pct and i == last)
            for i, v in enumerate(parts)
        )
    return numbers


def values_of_text(text: str) -> set[Decimal]:
    """Values of all the numbers of a text, line by line."""
    return {n.valore for line in text.split("\n") for n in extract_numbers(line)}


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Offsets ``(start, end)`` of the sentences; never across a newline."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for line in text.split("\n"):
        marker = _LIST_MARKER.match(line)
        start = marker.end() if marker else 0
        for m in _SENTENCE_END.finditer(line, start):
            if _ABBREVIATION.search(line, start, m.start()):
                continue
            if line[start : m.start()].strip():
                spans.append((pos + start, pos + m.start()))
            start = m.end()
        if line[start:].strip():
            spans.append((pos + start, pos + len(line)))
        pos += len(line) + 1
    return spans


#: M1 sentence boundary (#229): every period and every newline.
_M1_BOUNDARY = re.compile(r"[.\n]")


def _trimmed(text: str, a: int, b: int) -> tuple[int, int]:
    """``(a, b)`` without the whitespace at the edges, like ``str.strip()``."""
    while a < b and text[a].isspace():
        a += 1
    while b > a and text[b - 1].isspace():
        b -= 1
    return a, b


def split_sentences_m1(
    text: str, start: int = 0, end: int | None = None
) -> list[tuple[int, int]]:
    """Offsets ``(start, end)`` of the sentences as M1 splits them (#229, #369).

    It is the splitter of the M1 metric (``eval.metrics``): it lives here because the
    check also splits the measured block into the same sentences (point 8 of the
    module). It splits at every period and every newline; the sentences have no
    whitespace at the edges and empty ones do not count. It also splits "3.016",
    "d.lgs." and the "1." markers: it is M1's ruler in every arm and changing it
    would change ``METRICS_VERSION``. The filter uses :func:`split_sentences`.
    """
    end = len(text) if end is None else end
    spans: list[tuple[int, int]] = []
    pos = start
    for m in _M1_BOUNDARY.finditer(text, start, end):
        spans.append(_trimmed(text, pos, m.start()))
        pos = m.end()
    spans.append(_trimmed(text, pos, end))
    return [(a, b) for a, b in spans if a < b]


def measured_block(blocks: Sequence[BlockSpan]) -> BlockSpan | None:
    """The block that M1 measures, or ``None`` if the narrative does not have it.

    It is the ``ontologia`` field: the slot of the first block, with the label of the
    arm (``[ONTOLOGIA]``, or ``[SINTESI-LLM]`` in the ablated arm, #236).
    """
    return next((b for b in blocks if b.campo == "ontologia"), None)


def _block_of(pos: int, blocks: Sequence[BlockSpan]) -> Block:
    for b in blocks:
        if b.inizio_riga <= pos < b.inizio:
            return "intestazione"
        if b.inizio <= pos < b.fine and b.campo in _SOURCE_BLOCKS:
            return b.campo  # pyright: ignore[reportReturnType]
    return "overview"


#: A trend or a comparison belongs to an item IN a place (R6, review 2).
_Key = tuple[str, str]
#: Places named by a sentence: one group per full name, one per short name
#: (all the places with that name). The sentence holds for each group (#386).
_Groups = tuple[frozenset[str], ...]


def _istat_figures(rows: Sequence[IstatRow], excluded: set[Decimal]) -> set[Decimal]:
    """Counts and rates of the rows: always ISTAT figures, with or without ``%``."""
    return {
        d
        for r in rows
        for v in (r.delitti, r.delitti_confronto, r.tasso, r.tasso_italia)
        if v is not None
        for d in (Decimal(str(v)),)
        if d not in excluded
    }


def _variations(rows: Sequence[IstatRow], excluded: set[Decimal]) -> set[Decimal]:
    """Absolute value of the variations: an ISTAT figure only if written with ``%``
    (otherwise a number like "10" in "negli ultimi 10 anni" is not an ISTAT figure
    just because it coincides with the absolute value of a variation)."""
    return {
        d
        for r in rows
        if r.variazione_pct is not None
        for d in (Decimal(str(abs(r.variazione_pct))),)
        if d not in excluded
    }


def _trends(rows: Sequence[IstatRow]) -> dict[_Key, set[int]]:
    trends: dict[_Key, set[int]] = {}
    for r in rows:
        if r.variazione_pct is not None:
            trends.setdefault((r.luogo_codice, r.voce), set()).add(r.variazione_pct)
    return trends


def _classes(rows: Sequence[IstatRow]) -> dict[_Key, ItalyComparison | None]:
    """Comparison with the Italian rate of each (place, item), as in the block."""
    return {(r.luogo_codice, r.voce): compare_to_italy(r) for r in rows}


def _places(rows: Sequence[IstatRow]) -> list[tuple[str, str, str]]:
    """``(code, name, short name)`` in lowercase of the places of the rows."""
    return sorted(
        {(r.luogo_codice, r.luogo_nome.lower(), r.luogo_breve.lower()) for r in rows}
    )


def _labels(rows: Sequence[IstatRow]) -> list[tuple[str, str]]:
    pairs = {
        (r.voce, _TOTAL_LABEL if r.voce == TOTAL_ITEM else r.voce_label.lower())
        for r in rows
    }
    # Longest first: "furti con strappo" must be recognised before "furti".
    return sorted(pairs, key=lambda c: (-len(c[1]), c[0]))


def _risks(rows: Sequence[IstatRow]) -> list[tuple[str, str]]:
    """``(item, Italian label of the linked risk)`` to resolve the item of a
    sentence that names the risk instead of the item (C1)."""
    pairs = {
        (r.voce, _normalize(c.hazard_label_it)) for r in rows for c in r.collegamenti
    }
    return sorted(pairs, key=lambda c: (-len(c[1]), c[0]))


def _normalize(text: str) -> str:
    """Lowercase, typographic apostrophe like the straight one, without the markdown
    (``**furti**``, ``_furti_``) that would separate the words from the labels."""
    return re.sub(r"[*_]", "", text.lower().replace("’", "'"))


#: Ending of a word (#392): the last vowel, with the "i" of -io/-ia/-ie and the "h"
#: of -chi/-che/-ghi/-ghe ("furto/furti", "lesione/lesioni", "incendio/incendi",
#: "pubblica/pubbliche").
_ENDING = r"(?:(?<=[cg])h)?i?[aeio]"
_INFLECTION = re.compile(rf"{_ENDING}$")
#: Only words of at least 4 letters inflect: "da", "di", "via" stay.
_INFLECTED_LETTERS = 4
_PIECE = re.compile(r"(?P<parola>\w+)|\W+")


@functools.cache
def _label_pattern(label: str) -> str:
    """Regex of a label that ignores singular/plural and masculine/feminine
    (#392), to be searched in the :func:`_normalize`-d text: every word of at least
    4 letters ending in a vowel matches with any :data:`_ENDING`
    ("danneggiamenti seguiti da incendio" names "danneggiamento seguito da
    incendio"), the rest as it is. Single point for all the comparisons with the
    labels of items and linked risks."""

    def piece(m: re.Match[str]) -> str:
        text = m.group()
        if m["parola"] is None or len(text) < _INFLECTED_LETTERS:
            return re.escape(text)
        stem = _INFLECTION.sub("", text)
        if stem == text:
            return re.escape(text)
        return f"{re.escape(stem)}{_ENDING}"

    body = "".join(piece(m) for m in _PIECE.finditer(_normalize(label)))
    return rf"\b{body}\b"


def _named(
    text: str,
    labels: Sequence[tuple[str, str]],
    risks: Sequence[tuple[str, str]] = (),
) -> tuple[set[str], set[str]]:
    """Items named in ``text`` by item label (or ISTAT code) and by linked risk label
    (C1), up to inflection (#392).

    A recognised label is removed from the text, starting from the longest (on a tie
    the item before the risk, BANKROB "rapine/rapina in banca"): "furti con
    strappo" does not also name "furti", "danneggiamenti seguiti da incendio" does
    not also name "danneggiamenti", "il furto in gioielleria" (risk) does not also
    name the item "furti". The same label however holds for all the items that carry
    it (a risk linked to several items, C1)."""
    candidates = sorted(
        [(0, item, e) for item, e in labels] + [(1, item, e) for item, e in risks],
        key=lambda c: (-len(_normalize(c[2])), c[0]),
    )
    found: tuple[set[str], set[str]] = (set(), set())
    rest = _normalize(text)
    recognised: set[tuple[int, str]] = set()
    for kind, item, label in candidates:
        pattern = _label_pattern(label)
        if (kind, pattern) in recognised or re.search(pattern, rest):
            found[kind].add(item)
            recognised.add((kind, pattern))
            rest = re.sub(pattern, " ", rest)
    found[0].update(
        item for item, _ in labels if re.search(rf"\b{re.escape(item)}\b", text)
    )
    return found


def named_items(text: str, labels: Sequence[tuple[str, str]]) -> set[str]:
    """Items named in ``text`` by label (up to inflection, #392) or by ISTAT code;
    the longest label consumes its piece of text (:func:`_named`)."""
    return _named(text, labels)[0]


def names_item_of_rows(text: str, rows: Sequence[IstatRow]) -> bool:
    """``True`` if ``text`` names an item of the ``rows``: by label or code, or by
    label of a linked risk (C1). Items and risks as in the check
    (:func:`_named`): no synonyms ("borseggi" does not name "furti con
    destrezza") and, for the tolerance on the stems, "furti" also names "furti di
    identita' digitale", so an invented variant that shares the stem counts as "with
    item".

    The phrase "delitti denunciati" does not count: the TOT row (the frame) is always
    among the rows and the phrase is in the prompt, so it would distinguish nothing
    and would make a sentence with an invented risk disappear from the candidates
    ("i delitti denunciati per sequestro di persona sono in aumento"). Better one
    more candidate, to be discarded on reading, than a lost one. The exact label of
    the TOT row ("totale dei delitti") remains valid instead, as it names an item
    like the others: "il totale dei delitti per sequestro di persona" does not end up
    among the candidates."""
    items, risks = _named(text, _labels(rows), _risks(rows))
    return bool(items or risks)


def _named_places(text: str, places: Sequence[tuple[str, str, str]]) -> _Groups | None:
    """Places of the rows named in the sentence, by groups; ``None`` if none.

    First the full names ("comune di roma"), one group per name, then the short names
    in the remaining text: "Roma" alone is a group with all the places of the rows
    with that name (comune and provincia), so it does not restrict anything between
    the two. The sentence must hold for each group, and in a group one place is
    enough (#386)."""
    rest = _normalize(text)
    groups: list[frozenset[str]] = []
    for code, name, _ in places:
        pattern = re.compile(rf"\b{re.escape(name)}\b")
        if pattern.search(rest):
            groups.append(frozenset({code}))
            rest = pattern.sub(" ", rest)
    short: dict[str, set[str]] = {}
    for code, _, short_name in places:
        if re.search(rf"\b{re.escape(short_name)}\b", rest):
            short.setdefault(short_name, set()).add(code)
    groups += [frozenset(codes) for codes in short.values()]
    return tuple(groups) or None


def _negated(lowercase: str, word: int) -> bool:
    """There is a negation shortly before the position ``word`` (#386)."""
    return _NEGATION.search(lowercase, 0, word) is not None


def _direction(text: str) -> tuple[Direction, bool]:
    """Trend of the sentence and whether it is negated ("non sono in calo", #386):
    ``""`` if the sentence has words of different trends, or the same one negated
    and not negated."""
    lowercase = _normalize(text)
    trends: tuple[tuple[Direction, re.Pattern[str]], ...] = (
        ("su", _UP),
        ("giu", _DOWN),
        ("stabile", _STABLE),
    )
    found: dict[Direction, set[bool]] = {}
    for d, pattern in trends:
        for m in pattern.finditer(lowercase):
            found.setdefault(d, set()).add(_negated(lowercase, m.start()))
    if len(found) != 1:
        return "", False
    ((direction, negations),) = found.items()
    if len(negations) != 1:
        return "", False
    return direction, negations.pop()


def direction_of(text: str) -> Direction:
    """``su``/``giu``/``stabile`` if the sentence has words of a single trend,
    otherwise ``""`` (the negation does not change the written trend)."""
    return _direction(text)[0]


def _comparison(text: str) -> tuple[Comparison, bool]:
    """Comparison class of the sentence and whether it is negated ("non e' piu'
    alto", #386): ``"misto"`` (never negated) if the sentence uses different
    classes, or the same one negated and not negated."""
    lowercase = _normalize(text)
    found: dict[ItalyComparison, set[bool]] = {}
    for kind, pattern in _COMPARISONS.items():
        for m in pattern.finditer(lowercase):
            # With "tasso" in front the comparison starts from "tasso": the
            # negation is searched before the comparison word.
            word = _COMPARISON_WORD[kind].search(lowercase, m.start(), m.end())
            start = word.start() if word else m.start()
            found.setdefault(kind, set()).add(_negated(lowercase, start))
    if not found:
        return "", False
    if len(found) > 1:
        return "misto", False
    ((kind, negations),) = found.items()
    if len(negations) != 1:
        return "misto", False
    return kind, negations.pop()


def comparison_of(text: str) -> Comparison:
    """Comparison class with the Italian datum written in the sentence (#365): a
    comparison word only counts if followed shortly by the term of comparison (B2);
    ``"misto"`` if the sentence uses different classes (the negation does not change
    the written class)."""
    return _comparison(text)[0]


def _consistent(direction: Direction, trend: int) -> bool:
    if direction == "stabile":
        return trend == 0
    return trend > 0 if direction == "su" else trend < 0


def _in_place(key: _Key, items: set[str], places: frozenset[str] | None) -> bool:
    """The (place, item) is of a named item in a named place (all if
    ``None``)."""
    place, item = key
    return item in items and (places is None or place in places)


class _Rules(NamedTuple):
    fixed: set[Decimal]
    #: Width of the period (``Y - Y_comparison``): allowed, never an ISTAT figure
    #: without ``%``.
    intervals: set[Decimal]
    #: ``(code, name, short name)`` of the places of the rows, in lowercase.
    places: list[tuple[str, str, str]]
    #: Context (without the user's question), DATI ISTAT block, fixed list, period.
    allowed: set[Decimal]
    #: Counts and rates of the rows.
    figures: set[Decimal]
    #: Absolute values of the variations (ISTAT figures only with ``%``).
    variations: set[Decimal]
    trends: dict[_Key, set[int]]
    classes: dict[_Key, ItalyComparison | None]
    labels: list[tuple[str, str]]
    #: ``(item, label of the linked risk)``, for C1.
    risks: list[tuple[str, str]]
    #: "tasso", "voce", "dal <comparison year>", the Italian datum: with a named
    #: item they make a sentence without other markers talk about the ISTAT datum.
    markers: re.Pattern[str]


def _is_istat_figure(n: Number, rules: _Rules) -> bool:
    """``True`` if ``n`` is an ISTAT figure: count/rate always, variation only if
    written with ``%`` (minor ruling b). The width of the period without ``%`` does
    not get here: :func:`_evaluate` excludes it first (F2 of the final review)."""
    if n.valore in rules.figures:
        return True
    return n.percentuale and n.valore in rules.variations


def _markers(rows: Sequence[IstatRow]) -> re.Pattern[str]:
    years = "|".join(sorted({str(r.anno_confronto) for r in rows})) or r"\d{4}"
    # "tasso" in the ISTAT sense (fix 4): followed shortly by a comparison ("un tasso
    # piu' alto") or "tasso di/dei <item>". "Area ad alto tasso di criminalita'"
    # (a vulnerability of the ontology) is not.
    rate = rf"{_RATE_BEFORE}(?:{_ALL_COMPARISONS})\b"
    labels = sorted(
        {_normalize(r.voce_label) for r in rows if r.voce != TOTAL_ITEM},
        key=lambda e: (-len(e), e),
    )
    if labels:
        items = "|".join(_label_pattern(e) for e in labels)
        rate += rf"|\btass[oi] (?:di|del|dei|delle|degli) (?:{items})\b"
    # "voce" in the ISTAT sense: "la/questa voce", "voce piu' ampia/stretta", "voce ...
    # coincide/corrisponde"; not "dare voce al disagio". ("voce ISTAT" is already
    # covered by the word ISTAT.)
    item = (
        r"\b(?:la|questa|quella) voce\b"
        rf"|\bvoce(?:{_SEP}\w+){{0,2}}?{_SEP}(?:ampi[ao]|strett[ao])\b"
        rf"|\bvoce(?:{_SEP}\w+){{0,4}}?{_SEP}(?:corrispond|coincid)\w*"
    )
    return re.compile(rf"{rate}|{item}|\bdal (?:{years})\b|{_ITALIAN_FIGURE}")


#: List line "<item or risk>: <trend or comparison>" (C-2, #385).
_LIST_LINE = re.compile(r"(?P<testa>[^:]+):(?P<resto>[^:]*)")
#: Maximum words per part: "- furti: in crescita;" yes, "- Furto di beni: la
#: crescita dei flussi turistici aumenta i borseggi." no.
_LIST_LINE_WORDS = 6


def _is_list_line(text: str, rules: _Rules) -> bool:
    """``text`` is a short list line "<item or risk>: <trend or
    comparison>", like "- furti: in crescita;" or "- furti: piu' alti della media;"
    (C-2, #385)."""
    m = _LIST_LINE.fullmatch(_LIST_MARKER.sub("", text, count=1).strip())
    if m is None:
        return False
    head, rest = m["testa"], m["resto"]
    return (
        len(head.split()) <= _LIST_LINE_WORDS
        and len(rest.split()) <= _LIST_LINE_WORDS
        and bool(named_items(head, rules.labels) or named_items(head, rules.risks))
        and bool(direction_of(rest) or comparison_of(rest))
    )


def _talks_about_istat(
    text: str, block: Block, istat_figures: bool, item_and_marker: bool
) -> bool:
    """``True`` if the sentence refers to the ISTAT data (point 4).

    The label line ("Dati statistici ISTAT [ISTAT]") names ISTAT but says nothing
    about the datum. A sentence inside a residual ``[ISTAT]`` instead always talks
    about it (C3): the block only exists for that. A sentence that names an item
    of the rows (or a linked risk) together with a marker also talks about it
    ("tasso", "voce", "dal 2014", the Italian datum, the C-2 list line): "i furti
    hanno un tasso piu' alto e sono in calo dal 2014"."""
    if block == "intestazione":
        return False
    if block == "istat" or istat_figures or item_and_marker:
        return True
    return bool(_TALKS_ABOUT_ISTAT.search(_normalize(text)))


def _verify_direction(
    direction: Direction,
    negated: bool,
    items: set[str],
    places: _Groups | None,
    rules: _Rules,
) -> bool | None:
    """Consistency of the written trend for ALL the named items (C-1) and for each
    group of places (#386); in a group one agreeing place is enough (R6). Negated,
    it is consistent where the real trend is not the written one. ``None`` if an
    item has no computed trend in a group: the sentence is not verifiable."""
    outcomes: list[bool] = []
    for item in items:
        for group in places or (None,):
            signs = [
                t
                for key, values in rules.trends.items()
                if _in_place(key, {item}, group)
                for t in values
            ]
            if not signs:
                return None
            outcomes.append(any(_consistent(direction, t) != negated for t in signs))
    return all(outcomes) if outcomes else None


def _verify_comparison(
    comparison: Comparison,
    negated: bool,
    items: set[str],
    places: _Groups | None,
    rules: _Rules,
) -> bool | None:
    """Consistency of the written comparison for ALL the named items (C-1) and for
    each group of places (#386); in a group one agreeing place is enough (R6).
    Negated, it is consistent with the other classes. ``None`` if an item has no
    classification in a group: the sentence is not verifiable."""
    outcomes: list[bool] = []
    for item in items:
        for group in places or (None,):
            classes = {
                c
                for key, c in rules.classes.items()
                if c is not None and _in_place(key, {item}, group)
            }
            if not classes:
                return None
            outcomes.append(any((c == comparison) != negated for c in classes))
    return all(outcomes) if outcomes else None


def _evaluate(
    text: str,
    block: Block,
    start: int,
    end: int,
    rules: _Rules,
    inherited_places: _Groups | None = None,
    istat_list: bool = False,
) -> CheckedSentence:
    numbers = extract_numbers(text, rules.allowed)
    not_fixed = [
        n
        for n in numbers
        if n.valore not in rules.fixed
        and (n.percentuale or n.valore not in rules.intervals)
    ]
    istat = [n for n in not_fixed if _is_istat_figure(n, rules)]
    items, risk_items = _named(text, rules.labels, rules.risks)
    # C1: "il furto di beni ha un tasso piu' basso di quello italiano" names the
    # risk, not the item: the item is resolved from the linked risks.
    if items:
        risk_items = set[str]()
    explicit_places = _named_places(text, rules.places)
    marker = bool(rules.markers.search(_normalize(text)))
    direction, negated_direction = _direction(text)
    comparison, negated_comparison = _comparison(text)
    # C-2: in the list introduced by an ISTAT sentence with ":", the short line
    # "- furti: in crescita;" talks about the datum. Elsewhere an item with a trend or
    # a comparison is not enough, even with the inherited place (#385).
    if inherited_places is not None and istat_list and _is_list_line(text, rules):
        marker = True
    talks = _talks_about_istat(
        text, block, bool(istat), bool(items or risk_items) and marker
    )
    # The place said before in the same paragraph applies here too (fix 3): "I dati
    # ISTAT del Comune di Roma ...:" followed by a list of items.
    inherited = talks and explicit_places is None and inherited_places is not None
    places = inherited_places if inherited else explicit_places
    if talks and (direction or comparison) and not items:
        items = risk_items
        if not items and _IMPLICIT_TOTAL.search(_normalize(text)):
            # "i delitti denunciati hanno un tasso piu' alto": without another item
            # it is the total.
            items = {TOTAL_ITEM}
    # Trend and comparison are only verified in sentences that talk about the ISTAT
    # datum (R1): "a Roma la folla aumenta le occasioni di furti" talks about the risk.
    direction_consistent = (
        _verify_direction(direction, negated_direction, items, places, rules)
        if direction and items and talks
        else None
    )
    # "misto" is never a class of the row nor is it negated: it is not
    # consistent (B2).
    comparison_consistent = (
        _verify_comparison(comparison, negated_comparison, items, places, rules)
        if comparison and items and talks
        else None
    )
    reason: Reason | None = None
    if any(n.valore not in rules.allowed for n in numbers):
        reason = "numero_non_ammesso"
    elif istat:
        reason = "cifra_istat_fuori_blocco"
    elif talks and places is None:
        reason = "luogo_mancante"
    elif direction and talks and not direction_consistent:
        # ``None`` (no item, or an item without a computed trend) is not
        # verifiable: it is removed all the same, with the same reason (minor
        # ruling a).
        reason = "direzione_contraria"
    elif comparison and talks and not comparison_consistent:
        # Same for a comparison without an item, on an item without classification
        # or with different classes in the same sentence (#365 D3, B2, C1).
        reason = "confronto_contrario"
    return CheckedSentence(
        testo=text,
        blocco=block,
        inizio=start,
        fine=end,
        motivo=reason,
        cifre=len(not_fixed),
        cifre_istat=len(istat),
        voci=tuple(sorted(items)),
        parla_di_istat=talks,
        luogo=explicit_places is not None,
        luogo_ereditato=inherited,
        luoghi=tuple(sorted(frozenset[str]().union(*places))) if places else (),
        direzione=direction,
        direzione_negata=negated_direction,
        direzione_coerente=direction_consistent,
        confronto=comparison,
        confronto_negato=negated_comparison,
        confronto_coerente=comparison_consistent,
    )


#: End of paragraph: a blank line between two sentences (also with CRLF newlines,
#: #369).
_BLANK_LINE = re.compile(r"\n[ \t\r]*\n")


def _evaluate_paragraphs(
    narrative: str,
    spans: Sequence[tuple[int, int]],
    blocks: Sequence[BlockSpan],
    rules: _Rules,
    *,
    inherit_from_removed: bool = False,
) -> tuple[CheckedSentence, ...]:
    """:func:`_evaluate` sentence by sentence, with the inherited place (fix 3).

    The place of a sentence that talks about the ISTAT datum and that the check KEEPS
    applies to the following sentences of the same paragraph (list included); a new
    place replaces it. No inheritance across a blank line, at a block change (the
    synthesis does not pass the place to a block) nor from a removed sentence.
    ``inherit_from_removed`` (#369) makes the place pass also from removed
    sentences: needed by the ISTAT sentences of M1, which must not depend on the
    filter.

    Exception (fix 6): a sentence that passes the place and ends with ":" introduces
    a list. The place reaches the first item even across the blank lines that
    separate it from the introduction, and applies to all the following items (lines
    starting with -, *, • or "N."), even if separated by blank lines. The list ends
    at the first line that is not an item: there the inheritance stops.

    Only with a place coming from an introduction with ":" do the short lines
    "<item>: <trend or comparison>" talk about the datum (C-2, #385).
    """
    sentences: list[CheckedSentence] = []
    inherited: _Groups | None = None
    awaiting_list = False
    in_list = False
    #: The inherited place comes from an ISTAT introduction with ":" (C-2, #385); it
    #: only counts as long as ``inherited`` is not ``None``.
    istat_list = False
    previous_block: Block | None = None
    previous_end = 0
    for a, b in spans:
        block = _block_of(a, blocks)
        prefix = narrative[narrative.rfind("\n", 0, a) + 1 : a]
        list_item = bool(_LIST_MARKER.fullmatch(prefix))
        at_line_start = list_item or not prefix.strip()
        in_list_now = (awaiting_list or in_list) and list_item
        if (
            block != previous_block
            or (in_list and at_line_start and not list_item)
            or (_BLANK_LINE.search(narrative, previous_end, a) and not in_list_now)
        ):
            inherited, in_list = None, False
        elif in_list_now:
            in_list = True
        awaiting_list = False
        sentence = _evaluate(narrative[a:b], block, a, b, rules, inherited, istat_list)
        kept = sentence.motivo is None or inherit_from_removed
        if kept and sentence.parla_di_istat and sentence.luoghi:
            # The groups of places are inherited (#386), not just the codes: after
            # "nel Comune di Bari e nella Provincia di Bari" the sentence must hold
            # for both also in the sentences that follow.
            if sentence.luogo:
                inherited = _named_places(sentence.testo, rules.places)
            introduces = sentence.testo.rstrip().endswith(":")
            if introduces:
                awaiting_list, in_list = True, False
            # A list line inherits the place and does not close it; a new explicit
            # place without ":" does (C-2, #385).
            istat_list = introduces or (istat_list and not sentence.luogo)
        sentences.append(sentence)
        previous_block, previous_end = block, b
    return tuple(sentences)


def _opens_line(text: str, a: int) -> bool:
    """``a`` is at the start of its line, up to indentation."""
    return not text[text.rfind("\n", 0, a) + 1 : a].strip()


def _after_marker(text: str, a: int, b: int) -> int:
    """Start of the sentence ``(a, b)`` after the list marker, if it opens a
    line: M1 keeps it in the sentence, but it is what makes the list recognised
    (fix 6)."""
    if not _opens_line(text, a):
        return a
    marker = _LIST_MARKER.match(text[a:b])
    return a + marker.end() if marker else a


def _list_number(text: str, a: int, b: int) -> bool:
    """The sentence ``(a, b)`` is just the number of a "1." marker that M1
    detached from its item: it is not a sentence of the paragraph (#369, B1)."""
    if not _opens_line(text, a):
        return False
    line_end = text.find("\n", a)
    marker = _LIST_MARKER.match(text[a : len(text) if line_end == -1 else line_end])
    return marker is not None and a + marker.end() >= b


def _istat_sentences_m1(
    narrative: str,
    blocks: Sequence[BlockSpan],
    adapted: Sequence[BlockSpan],
    rules: _Rules,
) -> tuple[tuple[int, int], ...]:
    """M1 sentences of the measured block that talk about the ISTAT datum (point 8).

    ``blocks`` are those M1 reads (the measured block starts from the line after the
    label), ``adapted`` those of the filter, with the prose written on the label
    line inside the block: M1 does not measure it, but it can pass the place to the
    sentences that follow it ("... [ONTOLOGIA] I dati ISTAT del Comune di Roma
    indicano:" and then the list). The number of a "1." marker, which M1 detaches
    from the item, is not evaluated: it is part of the item, not a sentence that
    interrupts the list. For the same reason it follows the item (B-1): if the item
    is an ISTAT sentence so is its number, which otherwise M1 would count as an
    unanchored assertion only in the numbered list.
    """
    measured = measured_block(blocks)
    adapted_block = measured_block(adapted)
    if measured is None or adapted_block is None:
        return ()
    everything = split_sentences_m1(narrative, measured.inizio, measured.fine)
    sentences = [(a, b) for a, b in everything if not _list_number(narrative, a, b)]
    prose = split_sentences_m1(narrative, adapted_block.inizio, measured.inizio)
    evaluated = _evaluate_paragraphs(
        narrative,
        [(_after_marker(narrative, a, b), b) for a, b in prose + sentences],
        adapted,
        rules,
        inherit_from_removed=True,
    )
    istat = {
        s
        for s, v in zip(sentences, evaluated[len(prose) :], strict=True)
        if v.parla_di_istat
    }
    return tuple(
        s
        for i, s in enumerate(everything)
        if s in istat
        or (
            i + 1 < len(everything)
            and everything[i + 1] in istat
            and _item_number(narrative, s, everything[i + 1])
        )
    )


#: An M1 sentence made only of the number of an item, with or without a marker in
#: front ("1", "10", "- 1"): the rest of the item is the sentence after the period.
_ONLY_ITEM_NUMBER = re.compile(r"(?:[-*•]\s+)?\d{1,2}")


def _item_number(text: str, sentence: tuple[int, int], after: tuple[int, int]) -> bool:
    """``sentence`` is the number of the item that continues in ``after``: it opens
    the line, is only a number (with the marker, if any), is followed by ". " and
    ``after`` is on the same line (#369, B-1). "2024 e' stato un anno ..." is not."""
    a, b = sentence
    return (
        _opens_line(text, a)
        and _ONLY_ITEM_NUMBER.fullmatch(text[a:b]) is not None
        and text[b : b + 1] == "."
        and text[b + 1 : b + 2].isspace()
        and "\n" not in text[b : after[0]]
    )


def _without(text: str, cuts: Sequence[tuple[int, int]]) -> str:
    """``text`` without the indicated sentences; empties the lines left with only a
    marker."""
    if not cuts:
        return text
    lines: list[str] = []
    pos = 0
    for line in text.split("\n"):
        line_end = pos + len(line)
        local = sorted((a - pos, b - pos) for a, b in cuts if pos <= a <= line_end)
        if not local:
            lines.append(line)
        else:
            pieces: list[str] = []
            cursor = 0
            for a, b in local:
                pieces.append(line[cursor:a])
                cursor = b
            pieces.append(line[cursor:])
            new = re.sub(r"[ \t]{2,}", " ", "".join(pieces)).strip()
            # Leftovers of pure decoration (":" between a removed label and its
            # removed prose) or of the list marker alone are not text.
            if new.strip(_AFTER_TOKEN) and not _LIST_MARKER.fullmatch(new + " "):
                lines.append(new)
        pos = line_end + 1
    return "\n".join(lines)


def _tidy(text: str) -> str:
    """No blank lines at the start, at most one blank line between paragraphs and
    only the final newline at the end (C5): the cuts can leave gaps."""
    clean = re.sub(r"\n{3,}", "\n\n", text).lstrip("\n")
    return clean.rstrip("\n") + "\n" if clean.endswith("\n") else clean


def _orphan_labels(
    sentences: Sequence[CheckedSentence], blocks: Sequence[BlockSpan]
) -> list[tuple[int, int]]:
    """Label lines of the residual ``[ISTAT]`` blocks whose sentences are all
    removed (C5): left alone, they would announce an empty block."""
    cuts: list[tuple[int, int]] = []
    for b in blocks:
        if b.campo != "istat":
            continue
        body = [
            s
            for s in sentences
            if s.blocco == "istat" and b.inizio <= s.inizio < b.fine
        ]
        if body and all(s.motivo for s in body):
            cuts += [
                (s.inizio, s.fine)
                for s in sentences
                if s.blocco == "intestazione" and b.inizio_riga <= s.inizio < b.inizio
            ]
    return cuts


def _prose_in_header(
    narrative: str, blocks: Sequence[BlockSpan]
) -> tuple[list[BlockSpan], dict[int, int]]:
    """Blocks with the prose of the label line inside the block (F7).

    If after the token of the label line there is text, for the figures check the
    block starts from there (not from the next line). It also returns
    ``{end of the token: start of the prose}`` to split the sentence that
    :func:`split_sentences` would make across label and prose.
    """
    adapted: list[BlockSpan] = []
    cuts: dict[int, int] = {}
    for b in blocks:
        line = narrative[b.inizio_riga : b.inizio].rstrip("\n")
        token = _SOURCE_TOKEN.search(line)
        rest = line[token.end() :] if token else ""
        if token is None or not rest.strip(_AFTER_TOKEN):
            adapted.append(b)
            continue
        token_end = b.inizio_riga + token.end()
        prose = token_end + len(rest) - len(rest.lstrip(_AFTER_TOKEN))
        cuts[token_end] = prose
        adapted.append(b._replace(inizio=prose))
    return adapted, cuts


def _sentences(narrative: str, cuts: dict[int, int]) -> list[tuple[int, int]]:
    """:func:`split_sentences`, with the label separated from the prose that follows
    it."""
    spans: list[tuple[int, int]] = []
    for a, b in split_sentences(narrative):
        cut = next((t for t in cuts if a < t and cuts[t] < b), None)
        if cut is None:
            spans.append((a, b))
        else:
            spans += [(a, cut), (cuts[cut], b)]
    return spans


def check_figures(
    narrative: str,
    *,
    blocks: Sequence[BlockSpan],
    istat_block: str,
    context_without_istat: str,
    rows: Sequence[IstatRow],
) -> CheckOutcome:
    """Verify the figures of ``narrative`` against the context sent to the model."""
    fixed = {Decimal(100000), Decimal("0.1")}
    fixed |= {Decimal(r.anno) for r in rows} | {Decimal(r.anno_confronto) for r in rows}
    intervals = {Decimal(r.anno - r.anno_confronto) for r in rows}
    # The user's question is untrusted input: its numbers are neither
    # allowed nor excluded from the ISTAT figures (R2, review 2).
    in_context = values_of_text(_USER_QUESTION.sub(" ", context_without_istat))
    in_block = values_of_text(istat_block)
    # The numbers of the block (years, threshold, "del 2016") are never ISTAT figures,
    # even if they coincide with a rate or a count (#385): the block in words
    # (D7) does not write figures.
    excluded = fixed | in_context | in_block
    figures = _istat_figures(rows, excluded)
    variations = _variations(rows, excluded)
    rules = _Rules(
        fixed=fixed,
        intervals=intervals,
        places=_places(rows),
        # The block in words (D7) no longer carries the figures: those of the rows
        # are allowed as numbers, so an ISTAT figure written by the model is removed
        # as such and not as an invented number.
        allowed=fixed | intervals | in_context | in_block | figures | variations,
        figures=figures,
        variations=variations,
        trends=_trends(rows),
        classes=_classes(rows),
        labels=_labels(rows),
        risks=_risks(rows),
        markers=_markers(rows),
    )
    adapted, cuts = _prose_in_header(narrative, blocks)
    sentences = _evaluate_paragraphs(
        narrative, _sentences(narrative, cuts), adapted, rules
    )
    removed = [(s.inizio, s.fine) for s in sentences if s.motivo]
    filtered = (
        _tidy(_without(narrative, removed + _orphan_labels(sentences, adapted)))
        if removed
        else narrative
    )
    return CheckOutcome(
        frasi=sentences,
        testo_filtrato=filtered,
        frasi_istat_m1=_istat_sentences_m1(narrative, blocks, adapted, rules),
        numeri_in_lettere=len(_IN_WORDS.findall(narrative.lower())),
        righe=tuple(rows),
        codici_voce=sum(
            len(re.findall(rf"\b{re.escape(code)}\b", narrative))
            for code in {r.voce for r in rows}
        ),
    )


def apply_check(
    text: str,
    *,
    block: IstatBlock | None,
    spans: Sequence[BlockSpan],
    context: str,
) -> tuple[str, CheckOutcome | None]:
    """Apply the figures check to ``text`` if the prompt carried ISTAT (#345).

    Helper SHARED between the zone narrative (``rag.generation.generate_analysis``)
    and the per-POI one (``rag.poi_generation``, same schema): it encapsulates the
    decision "did the prompt have the DATI ISTAT block?" together with the call to
    :func:`check_figures`, so the two generation layers do not duplicate the same
    logic (controller ruling P4: no inline if-ISTAT in ``generate_analysis``).

    ``block`` is the one that ACTUALLY ended up in the prompt: it may be ``None``
    (the caller did not even try to turn ISTAT on) or have empty ``testo`` (ISTAT
    rows requested but none for the included POIs, #345 D-no-righe). In both cases
    the prompt did not carry the block and the check does not apply: ``text`` comes
    back unchanged and the outcome is ``None`` -- the same branch as "ISTAT off".
    Otherwise it calls :func:`check_figures` and returns the filtered text (what the
    operator sees) together with the full :class:`CheckOutcome`, which the caller
    keeps in memory for the evaluation harness.
    """
    if block is None or not block.testo:
        return text, None
    outcome = check_figures(
        text,
        blocks=spans,
        istat_block=block.testo,
        context_without_istat=context,
        rows=block.righe,
    )
    return outcome.testo_filtrato, outcome
