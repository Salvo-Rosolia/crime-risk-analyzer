"""Item labels recognised by inflection (#392).

Trastevere: the model writes "i danneggiamenti seguiti da incendio" for the item
"danneggiamento seguito da incendio"; the check must recognise that item
(not "danneggiamenti", which is another item without a computed trend).
"""

from __future__ import annotations

import re

import pytest

from crime_risk_analyzer.i18n.terminus_labels import label_it
from crime_risk_analyzer.istat.block import istat_block_for_poi
from crime_risk_analyzer.istat.catalog import CATALOG
from crime_risk_analyzer.istat.figures import (
    BlockSpan,
    CheckedSentence,
    check_figures,
    named_items,
)
from crime_risk_analyzer.istat.mapping import HAZARD_MAPPING
from crime_risk_analyzer.istat.rows import REASON_BREAK_2016, IstatRow
from tests.istat._factories import BANK_ROBBERIES, istat_poi, make_link, make_row

_DAMARS = make_row(
    "DAMARS",
    label="danneggiamento seguito da incendio",
    offences=383,
    comparison=286,
    rate=13.9,
    italy=12.6,
    variation=34,
    links=(make_link("Incendiary_attack", "Attacco incendiario"),),
)
_DAMAGE = make_row(
    "DAMAGE",
    label="danneggiamenti",
    offences=19843,
    comparison=16417,
    rate=721.2,
    italy=471.5,
    variation=None,
    reason=REASON_BREAK_2016,
    links=(make_link("Vandalism", "Vandalismo"),),
)
_SNATCHING = make_row(
    "BAGTHEF",
    label="furti con strappo",
    offences=4200,
    comparison=3900,
    rate=152.7,
    italy=24.1,
    variation=8,
    links=(make_link("Purse_snatching", "Scippo", "esatta"),),
)
_JEWELLER = make_row(
    "SHOPTHEF",
    label="furti in esercizi commerciali",
    offences=9000,
    comparison=11000,
    rate=327.1,
    italy=150.2,
    variation=-18,
    links=(make_link("Jewelry_theft", "Furto in gioielleria", "piu_stretta"),),
)
#: THEFT, "furti", variation -10, linked to the risk "Furto di beni".
_THEFTS = make_row()
_HEADER = "Rischi da ontologia [ONTOLOGIA]\n"


def _sentence(sentence: str, *rows: IstatRow) -> CheckedSentence:
    block = istat_block_for_poi(istat_poi(*rows))
    text = _HEADER + sentence
    outcome = check_figures(
        text,
        blocks=[BlockSpan("ontologia", 0, len(_HEADER), len(text))],
        istat_block=block.testo,
        context_without_istat="ZONA: Trastevere",
        rows=block.righe,
    )
    (checked,) = [f for f in outcome.frasi if f.blocco == "ontologia"]
    return checked


_TRASTEVERE = (
    "Sempre per il Comune di Roma (2024), {voce} hanno un tasso più alto rispetto "
    "alla media nazionale e mostrano una crescita dal 2014."
)


@pytest.mark.parametrize(
    "item",
    [
        "i danneggiamenti seguiti da incendio",
        "i **danneggiamenti seguiti da incendio**",
        "il danneggiamento seguito da incendio",
        "i Danneggiamenti Seguiti da Incendio",
    ],
)
def test_trastevere_the_right_sentence_in_the_plural_stays(item: str) -> None:
    sentence = _sentence(_TRASTEVERE.format(voce=item), _DAMAGE, _DAMARS)
    assert sentence.voci == ("DAMARS",)
    assert sentence.direzione_coerente is True
    assert sentence.confronto_coerente is True
    assert sentence.motivo is None


@pytest.mark.parametrize(
    "sentence",
    [
        "Nel Comune di Roma i danneggiamenti seguiti da incendio sono in calo "
        "dal 2014.",
        "Nel Comune di Roma i **danneggiamenti seguiti da incendio** sono in calo "
        "dal 2014.",
        "Nel Comune di Roma il danneggiamento seguito da incendio e' in calo dal 2014.",
    ],
)
def test_the_wrong_trend_in_the_plural_is_removed(sentence: str) -> None:
    checked = _sentence(sentence, _DAMAGE, _DAMARS)
    assert checked.voci == ("DAMARS",)
    assert checked.motivo == "direzione_contraria"


def test_the_two_items_named_separately_both_stay() -> None:
    labels = [("DAMARS", _DAMARS.voce_label), ("DAMAGE", "danneggiamenti")]
    sentence = (
        "Nel Comune di Roma i danneggiamenti hanno un tasso più alto della media "
        "nazionale e i danneggiamenti seguiti da incendio anche."
    )
    assert named_items(sentence, labels) == {"DAMAGE", "DAMARS"}
    # DAMAGE has no trend: a trend written for both is not verifiable.
    checked = _sentence(
        "Nel Comune di Roma i danneggiamenti e i danneggiamenti seguiti da incendio "
        "sono in crescita dal 2014.",
        _DAMAGE,
        _DAMARS,
    )
    assert checked.voci == ("DAMAGE", "DAMARS")
    assert checked.motivo == "direzione_contraria"


@pytest.mark.parametrize(
    ("label_text", "text"),
    [
        ("danneggiamenti", "il danneggiamento"),
        ("danneggiamento seguito da incendio", "i danneggiamenti seguiti da incendio"),
        ("rapine", "la rapina"),
        ("furti", "il furto"),
        ("furti", "il FURTO"),
        ("delitti informatici", "il delitto informatico"),
        ("lesioni dolose", "la lesione dolosa"),
        ("rapine in pubblica via", "la rapina in pubblica via"),
        ("rapine in banca", "la rapina in banche"),
        ("incendi", "l'incendio"),
        ("incendi boschivi", "l’incendio boschivo"),
        ("rapine in uffici postali", "la rapina in ufficio postale"),
        ("furti in esercizi commerciali", "il furto in esercizio commerciale"),
        ("sequestri di persona", "il sequestro di persone"),
        ("truffe e frodi informatiche", "la truffa e frode informatica"),
        ("Furti di opere d’arte", "il furto di opere d'arte"),
        (
            "furti di opere d'arte e materiale archeologico",
            "furto di opere d’arte e materiali archeologici",
        ),
    ],
)
def test_singular_plural_masculine_feminine_do_not_change_the_item(
    label_text: str, text: str
) -> None:
    sentence = f"Nel Comune di Roma {text} e' in calo."
    assert named_items(sentence, [("V", label_text)]) == {"V"}


@pytest.mark.parametrize(
    "text",
    ["i furtivi movimenti", "il furgone", "le rapinatrici", "gli incendiari"],
)
def test_different_words_with_the_same_stem_do_not_name_the_item(text: str) -> None:
    labels = [("THEFT", "furti"), ("ROBBER", "rapine"), ("ARSON", "incendi")]
    assert named_items(text, labels) == set()


def test_words_of_3_letters_do_not_inflect() -> None:
    # "via" does not become the stem "v" (which would match "va", "ve", "vi"...):
    # the rule is cautious and also leaves out "pubbliche vie" (declared limit).
    labels = [("STREETROB", "rapine in pubblica via")]
    assert named_items("le rapine in pubblica vi", labels) == set()
    assert named_items("la rapina in pubblica via", labels) == {"STREETROB"}


def test_on_equal_length_the_item_wins_over_the_risk() -> None:
    # "rapina in banca" (risk) and "rapine in banca" (item) have the same
    # stems: the span goes to the item, which stays named even without a trend.
    checked = _sentence(
        "Nel Comune di Roma la rapina in banca resta un rischio.", BANK_ROBBERIES
    )
    assert checked.voci == ("BANKROB",)


def test_labels_with_the_same_stems_apply_to_all_their_items() -> None:
    # A risk linked to several items (C1), also written with another inflection:
    # the piece of text is consumed by the first, but it holds for the others too.
    labels = [("A", "furti di beni"), ("B", "furto di beni"), ("C", "furto di beni")]
    assert named_items("il furto di beni e' in calo", labels) == {"A", "B", "C"}


def test_the_item_rate_in_the_singular_is_a_marker() -> None:
    # Without "dal 2014" or comparisons the only marker is "tasso del <item>".
    checked = _sentence(
        "Nel Comune di Roma il tasso del furto con strappo e' in calo.", _SNATCHING
    )
    assert checked.parla_di_istat is True
    assert checked.motivo == "direzione_contraria"


def test_the_longer_linked_risk_wins_over_the_generic_item() -> None:
    # "furto" is also the item "furti" (THEFT), but the risk "Furto in
    # gioielleria" (linked to SHOPTHEF) contains it and consumes the span.
    checked = _sentence(
        "Nel Comune di Roma il furto in gioielleria e' in calo dal 2014.",
        _THEFTS,
        _JEWELLER,
    )
    assert checked.voci == ("SHOPTHEF",)
    assert checked.motivo is None


# --- Systematic search on the real catalog (#392 point 3) ---


def _real_labels() -> list[str]:
    """Labels of the 56 catalog items and of the linked risks, in lowercase."""
    items = {v.etichetta.lower() for v in CATALOG.values()}
    risks = {label_it(h).lower() for h, m in HAZARD_MAPPING.items() if m.voce_istat}
    return sorted(items | risks)


#: Endings swapped by :func:`_other_inflection` (the first that matches).
_SWAPS = (
    ("che", "ca"),
    ("ghe", "ga"),
    ("ca", "che"),
    ("ga", "ghe"),
    ("io", "i"),
    ("o", "i"),
    ("a", "e"),
    ("e", "i"),
    ("i", "o"),
)


def _other_inflection(label_text: str) -> str:
    """Every word of at least 4 letters with the opposite number or gender, roughly."""

    def runs(m: re.Match[str]) -> str:
        word = m.group()
        if len(word) >= 4:
            for da, a in _SWAPS:
                if word.endswith(da):
                    return word[: -len(da)] + a
        return word

    return re.sub(r"\w+", runs, label_text)


def _names(text: str, label_text: str) -> bool:
    return bool(named_items(text, [("X", label_text)]))


def _contained_pairs() -> list[tuple[str, str]]:
    """``(short, long)``: the long one also names the short one if taken alone."""
    labels = _real_labels()
    return [
        (short_label, long_label)
        for short_label in labels
        for long_label in labels
        if short_label != long_label
        and _names(long_label, short_label)
        and not _names(short_label, long_label)
    ]


def _collisions() -> set[frozenset[str]]:
    """Different labels that name each other (same stem word by word)."""
    labels = _real_labels()
    return {
        frozenset((a, b))
        for a in labels
        for b in labels
        if a < b and _names(a, b) and _names(b, a)
    }


_PAIRS = _contained_pairs()


def test_the_search_finds_the_known_pairs() -> None:
    assert ("danneggiamenti", "danneggiamento seguito da incendio") in _PAIRS
    assert ("incendi", "danneggiamento seguito da incendio") in _PAIRS
    assert ("furti", "furti con strappo") in _PAIRS
    assert ("incendi", "incendi boschivi") in _PAIRS
    assert ("furti", "furto in gioielleria") in _PAIRS


@pytest.mark.parametrize(
    ("short_label", "long_label"), _PAIRS, ids=[f"{c} < {pl}" for c, pl in _PAIRS]
)
def test_the_longest_label_consumes_the_span(short_label: str, long_label: str) -> None:
    labels = [("CORTA", short_label), ("LUNGA", long_label)]
    for form in (long_label, _other_inflection(long_label)):
        sentence = f"Nel Comune di Roma i dati su {form} sono in calo."
        assert named_items(sentence, labels) == {"LUNGA"}, form
        assert named_items(sentence, labels[::-1]) == {"LUNGA"}, form


#: Collisions in the real catalog: equal stems word by word. They are all between
#: a linked risk and the item it is linked to (same item, no harm).
_COLLISION_NOTES = {
    frozenset(("rapina in banca", "rapine in banca")),
}


def test_the_catalog_collisions_are_only_the_known_ones() -> None:
    assert _collisions() == _COLLISION_NOTES


def test_the_known_collisions_lead_to_the_same_item() -> None:
    assert HAZARD_MAPPING["Bank_robbery"].voce_istat == "BANKROB"
    assert label_it("Bank_robbery").lower() == "rapina in banca"
    assert CATALOG["BANKROB"].etichetta == "rapine in banca"
