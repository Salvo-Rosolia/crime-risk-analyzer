# ruff: noqa: E501
"""Figures check (#345, spec 4.7): table of keep/remove cases."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from crime_risk_analyzer.istat.block import (
    IstatBlock,
    istat_block_for_poi,
    istat_block_for_zone,
)
from crime_risk_analyzer.istat.figures import (
    BlockSpan,
    CheckOutcome,
    Number,
    Reason,
    apply_check,
    check_figures,
    comparison_of,
    direction_of,
    extract_numbers,
    split_sentences,
    split_sentences_m1,
)
from crime_risk_analyzer.istat.rows import (
    REASON_BELOW_THRESHOLD,
    REASON_BREAK_2016,
    IstatPoi,
    IstatRow,
)
from crime_risk_analyzer.rag.generation import (
    USER_INPUT_FENCE_CLOSE,
    USER_INPUT_FENCE_OPEN,
)
from tests.istat._factories import istat_poi, make_frame, make_link, make_row

_THEFTS = make_row()
_DAMAGES = make_row(
    "DAMAGE",
    label="danneggiamenti",
    offences=19843,
    comparison=16417,
    rate=721.2,
    italy=471.5,
    variation=None,
    reason=REASON_BREAK_2016,
)
_ROBBERIES = make_row(
    "SHOPROB",
    label="rapine in esercizi commerciali",
    offences=812,
    comparison=701,
    rate=29.5,
    italy=13.1,
    variation=16,
)
_ISTAT = istat_poi(_THEFTS, _DAMAGES, _ROBBERIES)
_BLOCK = istat_block_for_poi(_ISTAT)
_CONTEXT = (
    "ZONA: Colosseo\n\nPOI RILEVANTI:\n  POI: Bar 2000 (Bank)\n"
    "NB: per limiti di lunghezza sono analizzati i 12 POI piu' rilevanti su 20; "
    "gli altri sono comunque in mappa e nella lista."
)
_HEADERS = {
    "ontologia": "Rischi da ontologia [ONTOLOGIA]",
    "contesto": "Rischi dal contesto [CONTESTO]",
    "speculativo": "Ipotesi speculative [SPECULATIVO]",
    "istat": "Dati statistici ISTAT [ISTAT]",
}
_TOKEN = {
    "ontologia": "[ONTOLOGIA]",
    "contesto": "[CONTESTO]",
    "speculativo": "[SPECULATIVO]",
    "istat": "[ISTAT]",
}


def _spans(text: str) -> list[BlockSpan]:
    """Headers as the parser finds them (Task 10), here without importing it."""
    found_items: list[tuple[str, int, int]] = []
    for field, token in _TOKEN.items():
        i = text.find(token)
        if i < 0:
            continue
        nl = text.find("\n", i)
        found_items.append(
            (field, text.rfind("\n", 0, i) + 1, len(text) if nl < 0 else nl + 1)
        )
    found_items.sort(key=lambda t: t[1])
    return [
        BlockSpan(
            c, a, b, found_items[k + 1][1] if k + 1 < len(found_items) else len(text)
        )
        for k, (c, a, b) in enumerate(found_items)
    ]


def _check(text: str) -> CheckOutcome:
    return check_figures(
        text,
        blocks=_spans(text),
        istat_block=_BLOCK.testo,
        context_without_istat=_CONTEXT,
        rows=_BLOCK.righe,
    )


_FIGURE: Reason = "cifra_istat_fuori_blocco"

_CASES: list[tuple[str, str, Reason | None]] = [
    # #365 D3: no block is any longer the place of the ISTAT figures. An ISTAT figure
    # removes the sentence everywhere, even inside an [ISTAT] written by mistake.
    (
        "istat",
        "Nel Comune di Roma i furti denunciati nel 2024 sono 134.169 (fonte ISTAT, Comune di Roma, 2024).",
        _FIGURE,
    ),
    (
        "istat",
        "I furti sono 4.876,4 ogni 100.000 abitanti contro 1.788,7 in Italia (fonte ISTAT, Comune di Roma, 2024).",
        _FIGURE,
    ),
    (
        "istat",
        "Le rapine in esercizi commerciali sono in aumento del +16% tra il 2014 e il 2024 (fonte ISTAT, Comune di Roma, 2024).",
        _FIGURE,
    ),
    ("istat", "Il totale dei delitti denunciati e' 217.536 nel 2024.", _FIGURE),
    ("istat", "Nel 2024 si contano 19.843 casi.", _FIGURE),
    ("ontologia", "Il Colosseo concentra 134.169 furti.", _FIGURE),
    ("contesto", "La zona ha 4.876,4 visitatori.", _FIGURE),
    (
        "speculativo",
        "Forse i furti potrebbero essere collegati ai 134.169 casi denunciati.",
        _FIGURE,
    ),
    (
        "ontologia",
        "Secondo i dati ISTAT del Comune di Roma i furti sono 134.169.",
        _FIGURE,
    ),
    # equivalent formats: always the same ISTAT figure
    ("ontologia", "I furti sono 134169 nel 2024.", _FIGURE),
    ("ontologia", "I furti sono 134 169 nel 2024.", _FIGURE),
    ("ontologia", "I furti sono 134\xa0169 nel 2024.", _FIGURE),
    ("ontologia", "I furti sono 134 169 nel 2024.", _FIGURE),
    ("ontologia", "I furti sono 4876.4 ogni 100.000 abitanti.", _FIGURE),
    ("ontologia", "Le rapine in esercizi commerciali calano del -16%.", _FIGURE),
    ("ontologia", "Le rapine in esercizi commerciali variano del –16%.", _FIGURE),
    # roundings and invented numbers: the reason stays the first one
    (
        "ontologia",
        "I furti sono circa 134.000 (fonte ISTAT, Comune di Roma, 2024).",
        "numero_non_ammesso",
    ),
    ("ontologia", "I furti sono 4.876 ogni 100.000 abitanti.", "numero_non_ammesso"),
    ("ontologia", "Nel 2023 i furti erano 134.169.", "numero_non_ammesso"),
    ("ontologia", "Tre banche su 9 sono esposte.", "numero_non_ammesso"),
    # years, period and numbers of the context remain allowed
    ("ontologia", "I dati coprono il periodo 2014-2024.", None),
    ("ontologia", "I dati coprono il periodo 2014\u20132024.", None),
    # C3: a sentence in a residual [ISTAT] always talks about the datum, so it needs the place
    ("istat", "I dati coprono il periodo 2014-2024.", "luogo_mancante"),
    ("istat", "Nel Comune di Roma i dati coprono il periodo 2014-2024.", None),
    # B1: national "livello"/"valore" do not make a sentence talk about ISTAT
    (
        "ontologia",
        "Il Colosseo e' un luogo di interesse a livello nazionale esposto a furti.",
        None,
    ),
    ("contesto", "La zona attira flussi di livello nazionale.", None),
    # B2: comparison words only count near the term of comparison
    ("ontologia", "Secondo l'ISTAT a Roma i furti e reati simili sono in calo.", None),
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma i furti al piano superiore sono in calo.",
        None,
    ),
    (
        "ontologia",
        "In linea con l'ontologia, secondo l'ISTAT nel Comune di Roma i furti hanno un tasso più basso di quello italiano.",
        "confronto_contrario",
    ),
    (
        "ontologia",
        "In linea con l'ontologia, secondo l'ISTAT nel Comune di Roma i furti hanno un tasso più alto di quello italiano.",
        None,
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma i furti sono al di sopra della media italiana.",
        None,
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma i furti hanno un tasso maggiore di quello italiano.",
        None,
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma i furti hanno un tasso più contenuto di quello italiano.",
        "confronto_contrario",
    ),
    # two classes in the same sentence: not verifiable, removed
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma i furti sono sopra la media italiana e i danneggiamenti sotto la media italiana.",
        "confronto_contrario",
    ),
    # C1: the item is resolved from the name of the linked risk
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma il furto di beni ha un tasso più basso di quello italiano.",
        "confronto_contrario",
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma il furto di beni ha un tasso più alto di quello italiano.",
        None,
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma il furto di beni e' in calo.",
        # C-1: the furto di beni is linked to furti (declining), danneggiamenti (without
        # trend) and robberies in shops (growing): it must hold for all
        "direzione_contraria",
    ),
    # no item even from the risks: comparison or trend not verifiable
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma il fenomeno ha un tasso più alto di quello italiano.",
        "confronto_contrario",
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma il fenomeno e' in calo.",
        "direzione_contraria",
    ),
    ("ontologia", "Tra i 12 POI analizzati, Bar 2000 e' esposto a rapina.", None),
    ("ontologia", "1. Rischio di rapina per Bar 2000.", None),
    # a variation is an ISTAT figure only with '%': "10 anni" is the period
    (
        "ontologia",
        "Nel Comune di Roma il totale dei delitti denunciati e' cambiato negli ultimi 10 anni.",
        None,
    ),
    # #365 D3 (a): a sentence that talks about the ISTAT datum names a place of the rows
    (
        "ontologia",
        "Secondo i dati ISTAT i furti hanno un tasso piu' alto di quello italiano.",
        "luogo_mancante",
    ),
    (
        "ontologia",
        "Secondo i dati ISTAT del Comune di Roma, i furti hanno un tasso più alto di quello italiano e sono in calo dal 2014 (voce più ampia del rischio).",
        None,
    ),
    ("ontologia", "Per l'ISTAT a Roma i furti sono sopra la media italiana.", None),
    ("ontologia", "I furti sono sotto la media nazionale.", "luogo_mancante"),
    ("ontologia", "Rispetto all'Italia i furti sono in calo.", "luogo_mancante"),
    ("ontologia", "Rispetto all’Italia i furti sono in calo.", "luogo_mancante"),
    ("ontologia", "I delitti denunciati per furti sono in calo.", "luogo_mancante"),
    ("ontologia", "Secondo l'ISTAT i furti sono in aumento.", "luogo_mancante"),
    (
        "speculativo",
        "Forse i delitti denunciati di furti sono in aumento.",
        "luogo_mancante",
    ),
    (
        "ontologia",
        "Il totale dei delitti denunciati e' stabile negli ultimi 10 anni.",
        "luogo_mancante",
    ),
    # R1 (review 2): the place name alone does not make a sentence talk about ISTAT,
    # not even with comparison or direction words
    (
        "ontologia",
        "Nel Comune di Roma i furti sono piu' alti nelle zone turistiche.",
        None,
    ),
    ("contesto", "Nel Comune di Roma i furti sono in aumento.", None),
    (
        "ontologia",
        "Il furto di beni domina la zona e i furti sono in aumento per la folla.",
        None,
    ),
    ("ontologia", "A Roma la folla aumenta le occasioni di furti nelle scuole.", None),
    ("ontologia", "La visibilita' ridotta favorisce i danneggiamenti a Roma.", None),
    ("contesto", "Le sale giochi di Roma attirano furti.", None),
    ("contesto", "Bar 2000 e' esposto a furti di notte.", None),
    # #365 D3 (b): the comparison agrees with the classification of the row
    # (thefts, damage and robberies of the fixture: all "piu' alto")
    (
        "ontologia",
        "Secondo i dati ISTAT del Comune di Roma, i furti hanno un tasso più basso di quello italiano.",
        "confronto_contrario",
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, a Roma i furti sono inferiori alla media nazionale.",
        "confronto_contrario",
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, a Roma i danneggiamenti sono in linea con il dato nazionale.",
        "confronto_contrario",
    ),
    (
        "contesto",
        "Secondo l'ISTAT, a Roma i danneggiamenti sono superiori alla media italiana.",
        None,
    ),
    ("overview", "Nel Comune di Roma i furti sono sopra la media italiana.", None),
    # D7: the total has its comparison too (higher in the fixture)
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma il totale dei delitti e' piu' alto della media italiana.",
        None,
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma il totale dei delitti e' piu' basso della media italiana.",
        "confronto_contrario",
    ),
    # direction contrary to the sign (or without a computed trend)
    (
        "ontologia",
        "Secondo i dati ISTAT del Comune di Roma, le rapine in esercizi commerciali mostrano un calo.",
        "direzione_contraria",
    ),
    (
        "ontologia",
        "Secondo l'ISTAT nel Comune di Roma le rapine in esercizi commerciali sono scese.",
        "direzione_contraria",
    ),
    (
        "ontologia",
        "Secondo l'ISTAT nel Comune di Roma i danneggiamenti sono in aumento.",
        "direzione_contraria",
    ),
    (
        "contesto",
        "Nel Comune di Roma i delitti denunciati per furti sono in aumento.",
        "direzione_contraria",
    ),
    (
        "istat",
        "I furti sono in crescita (fonte ISTAT, Comune di Roma, 2024).",
        "direzione_contraria",
    ),
]


@pytest.mark.parametrize(("block", "sentence", "expected"), _CASES)
def test_table_of_cases(block: str, sentence: str, expected: Reason | None) -> None:
    text = (
        f"{sentence}\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n"
        if block == "overview"
        else f"Sintesi.\n\n{_HEADERS[block]}\n{sentence}\n"
    )
    sentences = [f for f in _check(text).frasi if f.blocco == block]
    assert len(sentences) == 1
    assert sentences[0].motivo == expected


def test_missing_istat_header_removes_the_figures_in_the_synthesis() -> None:
    text = (
        "Sintesi. Nel Comune di Roma i furti sono 134.169 (fonte ISTAT, Comune di Roma, 2024).\n\n"
        "Rischi da ontologia [ONTOLOGIA]\nRischio rapina.\n"
    )
    outcome = _check(text)
    assert [(f.blocco, f.motivo) for f in outcome.frasi] == [
        ("overview", None),
        ("overview", "cifra_istat_fuori_blocco"),
        ("intestazione", None),
        ("ontologia", None),
    ]
    assert (
        outcome.testo_filtrato
        == "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRischio rapina.\n"
    )
    assert outcome.frasi_scartate == 1


def test_contrary_direction_outside_the_istat_block() -> None:
    """Fix round 1 - important 2, refined by F5 (final review): outside
    ``[ISTAT]`` the direction is checked when the sentence talks about the ISTAT data."""
    text = (
        "Sintesi: secondo l'ISTAT i furti sono in forte aumento.\n\n"
        "Rischi da ontologia [ONTOLOGIA]\nSecondo i dati ISTAT nel Comune di Roma i furti sono in forte aumento.\n"
    )
    outcome = _check(text)
    # #365: the synthesis talks about ISTAT without a place, it is removed for that first.
    assert [(f.blocco, f.motivo) for f in outcome.frasi] == [
        ("overview", "luogo_mancante"),
        ("intestazione", None),
        ("ontologia", "direzione_contraria"),
    ]


def test_filter_removes_lines_left_with_only_the_marker() -> None:
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        "1. Il Colosseo concentra 134.169 furti.\n2. Rischio rapina per Bar 2000.\n"
    )
    assert _check(text).testo_filtrato == (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n2. Rischio rapina per Bar 2000.\n"
    )


@pytest.mark.parametrize(
    "text",
    [
        "  Bar 2000: rapina, scippi ecc. Secondo l'ISTAT!\r\n- furti.** In calo.)\n\n",
        "Nessun punto",
        "",
        " . \n.\t\n",
        "1. Prima voce.\n2. Seconda (d.lgs. 7/2016) e 3.016 furti.",
    ],
)
def test_split_sentences_m1_is_the_m1_splitter(text: str) -> None:
    """#369: the M1 sentences (#229) with offsets: split at every period and every
    newline, without edge whitespace and without empty sentences, as M1 did."""
    expected_values = [s.strip() for s in re.split(r"[.\n]", text) if s.strip()]
    assert [text[a:b] for a, b in split_sentences_m1(text)] == expected_values


def test_split_sentences_m1_inside_a_range() -> None:
    text = "Sintesi. Altro.\nBar 2000: rapina. Scippi.\nCoda."
    start = text.index("Bar")
    end = text.index("Coda")
    assert [text[a:b] for a, b in split_sentences_m1(text, start, end)] == [
        "Bar 2000: rapina",
        "Scippi",
    ]


def _istat_sentences_m1(text: str, outcome: CheckOutcome) -> list[str]:
    return [text[a:b] for a, b in outcome.frasi_istat_m1]


def test_istat_sentences_m1_are_m1_sentences_of_the_measured_block() -> None:
    """#369: the ISTAT sentences for M1 are split as M1 splits them, not as the
    filter does: "ecc." does not end the sentence for the filter but does for M1. Only the
    measured block counts (not the synthesis, not [CONTESTO], not the label lines)."""
    text = (
        "Secondo l'ISTAT a Roma i furti sono in calo.\n\n"
        "Rischi da ontologia [ONTOLOGIA]\n"
        "Bar 2000 e' esposto a rapina, scippi ecc. Secondo l'ISTAT a Roma i furti "
        "sono in calo.\n\nRischi dal contesto [CONTESTO]\n"
        "Secondo l'ISTAT a Roma i furti sono in calo.\n"
    )
    outcome = _check(text)
    ontology = [f for f in outcome.frasi if f.blocco == "ontologia"]
    assert len(ontology) == 1 and ontology[0].parla_di_istat
    assert _istat_sentences_m1(text, outcome) == [
        "Secondo l'ISTAT a Roma i furti sono in calo"
    ]


def test_istat_sentences_m1_without_measured_block_are_none() -> None:
    text = "Secondo l'ISTAT a Roma i furti sono in calo.\n"
    assert _check(text).frasi_istat_m1 == ()


def test_istat_sentences_m1_even_if_the_measured_block_is_not_the_first() -> None:
    text = (
        "Sintesi.\n\nRischi dal contesto [CONTESTO]\n"
        "Secondo l'ISTAT a Roma i furti sono in calo.\n\n"
        "Rischi da ontologia [ONTOLOGIA]\n"
        "Bar 2000 e' esposto a rapina. Per l'ISTAT a Roma i furti sono in calo.\n"
    )
    assert _istat_sentences_m1(text, _check(text)) == [
        "Per l'ISTAT a Roma i furti sono in calo"
    ]


def test_istat_sentences_m1_recognise_the_list_after_blank_lines() -> None:
    """Fix 6 also on the M1 sentences, which keep the list marker: after
    an introduction with ":" the item inherits the place across the blank line."""
    introduction = "I dati ISTAT del Comune di Roma (2024) indicano:"
    text = _ontology(
        f"{introduction}\n\n- furti: in calo;\n\n* danneggiamenti: stabili"
    )
    assert _istat_sentences_m1(text, _check(text)) == [
        introduction,
        "- furti: in calo;",
        "* danneggiamenti: stabili",
    ]


def test_istat_sentences_m1_inherit_the_place_even_from_a_removed_sentence() -> None:
    """#369: for M1 the place also passes from the sentences the filter removes, so the
    measure does not depend on the filter. Here the introduction is removed (thefts are
    declining): for the filter the list line does not inherit the place and does not
    talk about the datum, for M1 it does. With the right introduction the ISTAT
    sentences for M1 are the same."""
    item = "- furti: in calo;"
    right = "I dati ISTAT del Comune di Roma (2024) indicano:"
    wrong = "I dati ISTAT del Comune di Roma (2024) indicano furti in aumento:"
    text = _ontology(f"{wrong}\n{item}")
    outcome = _check(text)
    assert [(f.motivo, f.parla_di_istat) for f in outcome.frasi[-2:]] == [
        ("direzione_contraria", True),
        (None, False),
    ]
    assert _istat_sentences_m1(text, outcome) == [wrong, item]
    right_text = _ontology(f"{right}\n{item}")
    assert _istat_sentences_m1(right_text, _check(right_text)) == [right, item]


def test_istat_sentences_m1_marker_only_at_line_start() -> None:
    """A hyphen after the number of an item ("1. - furti") is not a second
    marker: the sentence stays the numbered item, which inherits the place across the
    blank line (fix 6). Removing the hyphen too, the item would not be recognised."""
    introduction = "I dati ISTAT del Comune di Roma (2024) indicano:"
    text = _ontology(f"{introduction}\n\n1. - furti: in calo;")
    assert _istat_sentences_m1(text, _check(text)) == [
        introduction,
        "1",
        "- furti: in calo;",
    ]


@pytest.mark.parametrize(
    ("item", "expected_values"),
    [
        ("1. furti: in calo;", ["1", "furti: in calo;"]),
        ("10. furti: in calo;", ["10", "furti: in calo;"]),
        # M1 does not split "1)": the item is a single sentence
        ("1) furti: in calo;", ["1) furti: in calo;"]),
        ("- 1. furti: in calo;", ["- 1", "furti: in calo;"]),
        ("   1. furti: in calo;", ["1", "furti: in calo;"]),
        # item that does not talk about the datum: its number stays out
        ("1. Bar 2000 e' esposto a rapina;", []),
        # a year at line start is not the number of an item ("dal 2014": outside
        # the "furti: in calo" form a trend is not enough, #385)
        (
            "2024 e' stato un anno di furti in calo dal 2014;",
            ["2024 e' stato un anno di furti in calo dal 2014;"],
        ),
        ("2024. I furti sono in calo dal 2014;", ["I furti sono in calo dal 2014;"]),
        # the period of "3.016" is not that of a marker
        ("3.016 furti in calo dal 2014;", ["016 furti in calo dal 2014;"]),
    ],
)
def test_istat_sentences_m1_the_number_follows_the_item(
    item: str, expected_values: list[str]
) -> None:
    """#369, B-1: the number that M1 detaches from a numbered ISTAT item is an ISTAT
    sentence like the item, so M1 does not count it as an unanchored assertion. Also
    with CRLF newlines."""
    introduction = "I dati ISTAT del Comune di Roma (2024) indicano:"
    text = _ontology(f"{introduction}\n{item}")
    crlf = text.replace("\n", "\r\n")
    for t in (text, crlf):
        assert _istat_sentences_m1(t, _check(t)) == [introduction, *expected_values]


def test_istat_sentences_m1_number_at_line_end_does_not_follow_the_next_line() -> None:
    """A number followed by the period and the newline is not the start of the item of
    the next line."""
    introduction = "I dati ISTAT del Comune di Roma (2024) indicano:"
    text = _ontology(f"{introduction}\n1.\nfurti: in calo;")
    assert _istat_sentences_m1(text, _check(text)) == [
        introduction,
        "furti: in calo;",
    ]


def test_filter_with_crlf_newlines_stops_inheritance_at_the_blank_line() -> None:
    """#369: with CRLF the blank line interrupts the inherited place in the
    filter too, as with LF. Before, the sentence after the blank line inherited the place and
    stayed; now it is removed for missing place."""
    lf = _ontology(
        "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo.\n\n"
        "Le rapine in pubblica via hanno un tasso più alto dal 2014."
    )
    crlf = lf.replace("\n", "\r\n")
    outcome = _check_with(crlf, _REAL_ZONE)
    assert _reasons(outcome) == _reasons(_check_with(lf, _REAL_ZONE))
    assert _reasons(outcome) == [None, "luogo_mancante"]
    assert "Le rapine" not in outcome.testo_filtrato
    assert "i furti sono in calo" in outcome.testo_filtrato


def test_istat_sentences_m1_equal_with_crlf_newlines() -> None:
    """#369: with CRLF the blank line interrupts the inheritance as with LF."""
    lf = _ontology(
        "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo.\n\n- furti: in calo;"
    )
    crlf = lf.replace("\n", "\r\n")
    assert (
        _istat_sentences_m1(crlf, _check(crlf))
        == _istat_sentences_m1(lf, _check(lf))
        == ["Secondo l'ISTAT, nel Comune di Roma i furti sono in calo"]
    )


def test_the_istat_label_line_is_not_removed() -> None:
    """#365: "Dati statistici ISTAT [ISTAT]" names ISTAT but does not talk about the datum;
    removing it would attach the prose of the block to the previous one (as long as the
    block has kept sentences, C5). The sentences of the block talk about the datum (C3)."""
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n\n"
        "Dati statistici ISTAT [ISTAT]\nNel Comune di Roma i furti sono in calo.\n"
    )
    outcome = _check(text)
    assert [(f.blocco, f.parla_di_istat, f.motivo) for f in outcome.frasi][-2:] == [
        ("intestazione", False, None),
        ("istat", True, None),
    ]
    assert outcome.testo_filtrato == text


def test_residual_istat_block_fully_removed_loses_its_label_too() -> None:
    """C5: without kept sentences the label line would remain orphaned."""
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n\n"
        "Dati statistici ISTAT [ISTAT]\nI furti sono 134.169.\n"
        "Secondo l'ISTAT i furti sono in calo.\n"
    )
    outcome = _check(text)
    assert outcome.testo_filtrato == (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n"
    )
    # the label is not a removed sentence: it does not count among the discarded
    assert outcome.frasi_scartate == 2


def test_label_with_prose_on_the_same_line_fully_removed() -> None:
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n\n"
        "Dati statistici ISTAT [ISTAT]: i furti sono 134.169.\n"
    )
    assert _check(text).testo_filtrato == (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n"
    )


def test_no_leading_blank_lines_in_the_filtered_text() -> None:
    text = (
        "Secondo l'ISTAT i furti sono in calo.\n\n"
        "Rischi da ontologia [ONTOLOGIA]\nRapina.\n"
    )
    assert _check(text).testo_filtrato == ("Rischi da ontologia [ONTOLOGIA]\nRapina.\n")


def test_numbers_in_words_counted_not_removed() -> None:
    text = "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nI furti sono quasi il doppio della media.\n"
    outcome = _check(text)
    assert outcome.numeri_in_lettere == 1
    assert outcome.frasi_scartate == 0


def test_per_sentence_metrics() -> None:
    text = (
        "Sintesi.\n\nDati statistici ISTAT [ISTAT]\nI furti scendono da 148.910 a "
        "134.169, un calo del -10% (fonte ISTAT, Comune di Roma, 2024).\n"
    )
    sentence = [f for f in _check(text).frasi if f.blocco == "istat"][0]
    assert sentence.motivo == "cifra_istat_fuori_blocco"
    assert (sentence.cifre, sentence.cifre_istat) == (3, 3)
    assert sentence.voci == ("THEFT",)
    assert (sentence.parla_di_istat, sentence.luogo) == (True, True)
    assert (sentence.direzione, sentence.direzione_coerente) == ("giu", True)
    assert (sentence.confronto, sentence.confronto_coerente) == ("", None)


def test_per_sentence_comparison_metrics() -> None:
    """#365: comparison and consistency stay on the sentence for the metrics."""
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nSecondo l'ISTAT a Roma i "
        "furti sono sopra la media italiana. Secondo l'ISTAT a Roma i furti sono "
        "sotto la media italiana. Il furto di beni domina.\n"
    )
    sentences = [f for f in _check(text).frasi if f.blocco == "ontologia"]
    assert [
        (f.parla_di_istat, f.confronto, f.confronto_coerente, f.motivo)
        for f in sentences
    ] == [
        (True, "piu_alto", True, None),
        (True, "piu_basso", False, "confronto_contrario"),
        (False, "", None, None),
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("i furti sono sopra la media italiana", "piu_alto"),
        ("un tasso più alto di quello italiano", "piu_alto"),
        ("un tasso piu' alto di quello nazionale", "piu_alto"),
        ("un tasso più elevato della media", "piu_alto"),
        ("valori superiori al dato nazionale", "piu_alto"),
        ("al di sopra della media italiana", "piu_alto"),
        ("un tasso maggiore di quello italiano", "piu_alto"),
        ("sotto la media nazionale", "piu_basso"),
        ("al di sotto della media", "piu_basso"),
        ("un tasso più basso di quello italiano", "piu_basso"),
        ("un tasso più contenuto di quello italiano", "piu_basso"),
        ("un tasso minore del dato nazionale", "piu_basso"),
        ("valori inferiori alla media italiana", "piu_basso"),
        ("un tasso simile a quello italiano", "simile"),
        ("in linea con il dato nazionale", "simile"),
        (
            "più alto della media per i furti e più basso di quello italiano per altri",
            "misto",
        ),
        # without a nearby term of comparison it is not a comparison
        ("un tasso piu' alto", "piu_alto"),
        ("valori inferiori", ""),
        ("reati simili sono in calo", ""),
        ("il piano superiore del palazzo", ""),
        ("in linea con l'ontologia, i furti", ""),
        ("più alti per alcune voci e più bassi per altre", ""),
        ("i furti sono in calo", ""),
    ],
)
def test_comparison_words(text: str, expected: str) -> None:
    assert comparison_of(text) == expected


def test_comparison_per_place_and_item_without_classification() -> None:
    """#365 D3 (b): the classification of the item IN the named place applies; an item
    without classification (missing national) does not support a comparison."""
    province = make_row(
        place="ITE43",
        name="Provincia di Roma",
        kind="provincia",
        rate=1000.0,
        variation=5,
    )
    without_italy = make_row("SNATCH", label="scippi", italy=None)
    block = istat_block_for_zone(
        [
            {"poi_id": "a", "istat": istat_poi(_MUNICIPALITY, without_italy)},
            {
                "poi_id": "b",
                "istat": IstatPoi(
                    cornice=make_frame(
                        place="ITE43", name="Provincia di Roma", kind="provincia"
                    ),
                    righe=(province,),
                ),
            },
        ],
        estimate_tokens=len,
        token_limit=None,
    )
    cases = {
        "Secondo l'ISTAT, nella Provincia di Roma i furti sono sotto la media italiana.": None,
        "Secondo l'ISTAT, nel Comune di Roma i furti sono sotto la media italiana.": "confronto_contrario",
        # "Roma" holds for municipality and province: it is enough that one of the two agrees
        "Secondo l'ISTAT, a Roma i furti sono sotto la media italiana.": None,
        "Secondo l'ISTAT, nel Comune di Roma gli scippi sono sopra la media italiana.": "confronto_contrario",
        "Secondo l'ISTAT, nel Comune di Roma gli scippi sono in calo.": None,
    }
    for sentence, expected in cases.items():
        text = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{sentence}\n"
        outcome = _check_with(text, block)
        assert [f.motivo for f in outcome.frasi if f.blocco == "ontologia"] == [
            expected
        ], sentence


def test_number_extraction() -> None:
    assert extract_numbers("da 1.162,7 a 0,6 e +15% poi −3 % nel 2014-2024") == [
        Number(Decimal("1162.7"), "", False),
        Number(Decimal("0.6"), "", False),
        Number(Decimal("15"), "+", True),
        Number(Decimal("3"), "-", True),
        Number(Decimal("2014"), "", False),
        Number(Decimal("2024"), "", False),
    ]
    assert extract_numbers("voce ITE43 e 73_67") == []
    assert extract_numbers("1. Rischio") == []


def test_sentence_splitting_does_not_break_numbers() -> None:
    text = "Sono 1.162,7 ogni 100.000 abitanti. Poi altro!\nNuova riga"
    assert [text[a:b] for a, b in split_sentences(text)] == [
        "Sono 1.162,7 ogni 100.000 abitanti.",
        "Poi altro!",
        "Nuova riga",
    ]


def test_apply_check_without_block_leaves_the_text_unchanged() -> None:
    """``block=None``: the prompt had no ISTAT, no check (#345 P4)."""
    text = "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n"
    assert apply_check(text, block=None, spans=[], context="") == (
        text,
        None,
    )


def test_apply_check_with_empty_block_leaves_the_text_unchanged() -> None:
    """Default ``IstatBlock()`` (``testo=""``): same branch as ISTAT off."""
    text = "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n"
    assert apply_check(text, block=IstatBlock(), spans=[], context="") == (
        text,
        None,
    )


def test_apply_check_with_active_block_filters_and_returns_outcome() -> None:
    """With a non-empty block it delegates to ``check_figures`` and the filtered text comes back."""
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nIl Colosseo concentra "
        "134.169 furti. Bar 2000 e' esposto a rapina.\n\n"
        "Dati statistici ISTAT [ISTAT]\nI furti sono 134.169 nel 2024.\n"
    )
    narrative, outcome = apply_check(
        text, block=_BLOCK, spans=_spans(text), context=_CONTEXT
    )
    assert outcome is not None
    assert narrative == outcome.testo_filtrato
    assert "134.169 furti" not in narrative
    assert "Bar 2000 e' esposto a rapina." in narrative
    assert outcome == check_figures(
        text,
        blocks=_spans(text),
        istat_block=_BLOCK.testo,
        context_without_istat=_CONTEXT,
        rows=_BLOCK.righe,
    )


def test_year_span_is_an_allowed_number_not_an_istat_figure() -> None:
    """F2 (final review): "10 anni" (Y - Y_comparison) is not an invented number."""
    block = istat_block_for_poi(istat_poi(make_row(variation=-10)))
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nNegli ultimi 10 anni, secondo "
        "l'ISTAT, nel Comune di Roma i furti sono diminuiti.\n"
    )
    outcome = check_figures(
        text,
        blocks=_spans(text),
        istat_block=block.testo,
        context_without_istat=_CONTEXT,
        rows=block.righe,
    )
    sentence = [f for f in outcome.frasi if f.blocco == "ontologia"][0]
    assert sentence.motivo is None
    # 10 coincides with the absolute value of the variation (-10%): without '%' it is the period
    assert sentence.cifre_istat == 0


def test_per_cento_in_words_counts_as_percentage() -> None:
    """F6 (final review): "10 per cento" is an ISTAT variation like "10%"."""
    text = (
        "Nel Comune di Roma i furti sono calati del 10 per cento in dieci anni.\n\n"
        "Rischi da ontologia [ONTOLOGIA]\nRischio rapina.\n"
    )
    outcome = _check(text)
    assert [(f.blocco, f.motivo) for f in outcome.frasi][0] == (
        "overview",
        "cifra_istat_fuori_blocco",
    )
    assert extract_numbers("del 10 per cento e del 3 percento") == [
        Number(Decimal("10"), "", True),
        Number(Decimal("3"), "", True),
    ]


def test_prose_on_the_header_line_belongs_to_the_block() -> None:
    """F7 (final review): the text after the token on the label line belongs to the block."""
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRischio rapina.\n\n"
        "Dati statistici ISTAT [ISTAT]: nel Comune di Roma i delitti denunciati per "
        "furti sono in calo.\n"
    )
    outcome = _check(text)
    istat = [f for f in outcome.frasi if f.blocco == "istat"]
    assert len(istat) == 1
    assert istat[0].motivo is None
    assert istat[0].testo.startswith("nel Comune di Roma")
    assert istat[0].direzione_coerente is True
    assert outcome.frasi_scartate == 0
    assert outcome.testo_filtrato == text


def _check_with(text: str, block: IstatBlock, context: str = _CONTEXT) -> CheckOutcome:
    return check_figures(
        text,
        blocks=_spans(text),
        istat_block=block.testo,
        context_without_istat=context,
        rows=block.righe,
    )


def _istat_sentences(outcome: CheckOutcome) -> list[tuple[str, Reason | None]]:
    return [(f.testo, f.motivo) for f in outcome.frasi if f.blocco == "istat"]


def test_direction_vocabulary_only_for_trends() -> None:
    """R1 (review 2): causal or adjectival forms are not trend statements."""
    assert direction_of("la folla aumenta le occasioni") == ""
    assert direction_of("la visibilita' ridotta") == ""
    assert direction_of("una riduzione delle pattuglie") == ""
    assert direction_of("le sale giochi") == ""
    assert direction_of("i furti sono in aumento") == "su"
    assert direction_of("i furti sono aumentati") == "su"
    assert direction_of("i furti salgono") == "su"
    assert direction_of("i furti sono saliti") == "su"
    assert direction_of("in crescita") == "su"
    assert direction_of("in calo") == "giu"
    assert direction_of("i furti sono diminuiti") == "giu"
    assert direction_of("i furti sono calati") == "giu"
    assert direction_of("i furti scendono") == "giu"
    assert direction_of("i furti sono scesi") == "giu"


_CONTEXT_WITH_QUESTION = (
    f"{_CONTEXT}\n\n{USER_INPUT_FENCE_OPEN}\n"
    "e' vero che ci sono 999.999 furti?\n"
    f"{USER_INPUT_FENCE_CLOSE}"
)


def test_user_question_number_not_allowed_in_istat() -> None:
    """R2 (review 2): untrusted input puts no figure on the list."""
    text = (
        "Sintesi.\n\nDati statistici ISTAT [ISTAT]\nI furti sono 999.999 nel Comune "
        "di Roma (fonte ISTAT, Comune di Roma, 2024).\n"
    )
    outcome = _check_with(text, _BLOCK, _CONTEXT_WITH_QUESTION)
    assert [m for _, m in _istat_sentences(outcome)] == ["numero_non_ammesso"]


def test_user_question_number_not_allowed_in_the_synthesis() -> None:
    """R2 (review 2): outside [ISTAT] the question fence does not allow numbers."""
    text = (
        "Ci sono 999.999 furti in zona.\n\n"
        "Rischi dal contesto [CONTESTO]\nBar 2000 e' esposto a furti di notte.\n"
    )
    outcome = _check_with(text, _BLOCK, _CONTEXT_WITH_QUESTION)
    assert [(f.blocco, f.motivo) for f in outcome.frasi] == [
        ("overview", "numero_non_ammesso"),
        ("intestazione", None),
        ("contesto", None),
    ]


_DAMAGE_AND_SEVEN = istat_block_for_poi(
    istat_poi(
        _DAMAGES,
        # 7 is an ISTAT figure (the rate): the item stays above 20 offences (#365).
        make_row(
            "BANKROB",
            label="rapine in banca",
            offences=27,
            comparison=46,
            rate=7.0,
            italy=0.2,
            variation=None,
            reason="meno di 20 delitti in uno dei due anni",
        ),
    )
)


def test_legal_reference_neither_splits_the_sentence_nor_is_a_figure() -> None:
    """R4 (review 2): "d.lgs. 7/2016" stays in the sentence and 7 is not a figure."""
    sentence = (
        "Secondo l'ISTAT, nel Comune di Roma la serie dei danneggiamenti e' "
        "interrotta dalla depenalizzazione (d.lgs. 7/2016)."
    )
    text = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{sentence}\n"
    outcome = _check_with(text, _DAMAGE_AND_SEVEN)
    assert [r.tasso for r in _DAMAGE_AND_SEVEN.righe if r.voce == "BANKROB"] == [7.0]
    assert [
        (f.testo, f.motivo, f.cifre_istat)
        for f in outcome.frasi
        if f.blocco == "ontologia"
    ] == [(sentence, None, 0)]
    assert outcome.testo_filtrato == text


def test_abbreviations_do_not_end_the_sentence() -> None:
    """R4 (review 2): d.lgs., art., n., es., ecc., cfr. do not end the sentence."""
    text = "Vedi art. 624 e cfr. n. 3, es. furti ecc. ma non solo. Fine."
    assert [text[a:b] for a, b in split_sentences(text)] == [
        "Vedi art. 624 e cfr. n. 3, es. furti ecc. ma non solo.",
        "Fine.",
    ]
    assert extract_numbers("dal d.lgs. 7/2016 in poi") == []


_MUNICIPALITY = make_row()
_PROVINCE = make_row(
    place="ITE43",
    name="Provincia di Roma",
    short="Roma",
    kind="provincia",
    offences=200000,
    comparison=190000,
    rate=4700.1,
    italy=1788.7,
    variation=5,
)
_TWO_PLACES = istat_block_for_zone(
    [
        {"poi_id": "a", "istat": istat_poi(_MUNICIPALITY)},
        {
            "poi_id": "b",
            "istat": IstatPoi(
                cornice=make_frame(
                    place="ITE43",
                    name="Provincia di Roma",
                    short="Roma",
                    kind="provincia",
                ),
                righe=(_PROVINCE,),
            ),
        },
    ],
    estimate_tokens=len,
    token_limit=None,
)


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        (
            "Nel Comune di Roma i furti sono in aumento (fonte ISTAT, Comune di Roma, 2024).",
            "direzione_contraria",
        ),
        (
            "Secondo l'ISTAT, nella Provincia di Roma i furti sono in aumento.",
            None,
        ),
        ("Secondo l'ISTAT, nel Comune di Roma i furti sono in calo.", None),
        (
            "Secondo l'ISTAT, nella Provincia di Roma i furti sono in calo.",
            "direzione_contraria",
        ),
        # "Roma" holds for municipality and province: one agreeing trend is enough
        ("Secondo l'ISTAT, a Roma i furti sono in aumento.", None),
        # #365: with ISTAT, figures are always removed (even the right ones)
        (
            "Nella Provincia di Roma i furti sono 200.000, in aumento del +5% (fonte ISTAT, Provincia di Roma, 2024).",
            "cifra_istat_fuori_blocco",
        ),
        # a sentence that does not talk about ISTAT is not checked
        ("I furti sono in aumento.", None),
    ],
)
def test_direction_per_place_and_item(sentence: str, expected: Reason | None) -> None:
    """R6 (review 2): if the sentence names a place of the rows its values apply."""
    text = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{sentence}\n"
    outcome = _check_with(text, _TWO_PLACES)
    assert [(f.testo, f.motivo) for f in outcome.frasi if f.blocco == "ontologia"] == [
        (sentence, expected)
    ]


_SNATCHING: IstatRow = make_row(
    "SNATCH",
    label="furti con strappo",
    offences=340,
    comparison=1150,
    rate=12.4,
    italy=19.9,
    variation=-70,
)
_WITH_SNATCHING = istat_block_for_poi(istat_poi(_MUNICIPALITY, _SNATCHING))


@pytest.mark.parametrize(
    "sentence",
    [
        "Nei 10 anni 340 furti con strappo in meno.",
        "Negli ultimi 10 340 furti con strappo denunciati nel 2024 (fonte ISTAT, Comune di Roma, 2024).",
        "I furti sono 134 169 nel 2024.",
    ],
)
def test_normal_space_between_two_allowed_numbers(sentence: str) -> None:
    """R8 (review 2): "10 340" are two allowed numbers, not 10.340 (which would be a
    ``numero_non_ammesso``): the sentence is removed only because it carries an ISTAT
    figure (#365)."""
    text = f"Sintesi.\n\nDati statistici ISTAT [ISTAT]\n{sentence}\n"
    assert _istat_sentences(_check_with(text, _WITH_SNATCHING)) == [
        (sentence, "cifra_istat_fuori_blocco")
    ]


def test_the_variation_of_the_total_is_no_longer_an_allowed_figure() -> None:
    """#353: the frame no longer computes the variation (2016 break), so the
    old percentage of the total is not in the block and a sentence that quotes it must be
    removed. Real data of the Comune di Milano (total 162.177 -> 140.974)."""
    from crime_risk_analyzer.istat.rows import istat_for_poi

    istat = istat_for_poi(45.4642, 9.19, ["Property_theft"])
    assert istat is not None
    block = istat_block_for_poi(istat)
    assert "-13%" not in block.testo
    text = (
        "Sintesi.\n\nDati statistici ISTAT [ISTAT]\n"
        "Nel Comune di Milano il totale dei delitti denunciati e' in calo del -13% "
        "(fonte ISTAT, Comune di Milano, 2024).\n"
    )
    outcome = check_figures(
        text,
        blocks=_spans(text),
        istat_block=block.testo,
        context_without_istat=_CONTEXT,
        rows=block.righe,
    )
    assert "-13%" not in outcome.testo_filtrato
    citing = [f for f in outcome.frasi if "-13%" in text[f.inizio : f.fine]]
    assert len(citing) == 1
    assert citing[0].motivo is not None


def test_item_from_the_risk_with_typographic_apostrophe() -> None:
    """C1: the name of the risk is recognised with a straight or typographic apostrophe."""
    auto = make_row(
        "VEHTHEFT",
        label="furti di autoveicoli",
        rate=100.0,
        italy=200.0,
        variation=5,
        links=(make_link("Car_theft", "Furto d'auto", "esatta"),),
    )
    block = istat_block_for_poi(istat_poi(auto))
    base = "Secondo l'ISTAT, nel Comune di Roma il furto {} ha un tasso più {} di quello italiano."
    cases = {
        base.format("d\u2019auto", "basso"): None,
        base.format("d'auto", "basso"): None,
        base.format("d\u2019auto", "alto"): "confronto_contrario",
    }
    for sentence, expected in cases.items():
        text = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{sentence}\n"
        outcome = _check_with(text, block)
        assert [f.motivo for f in outcome.frasi if f.blocco == "ontologia"] == [
            expected
        ], sentence


def test_the_prompt_example_sentence_passes_the_check() -> None:
    """D7: the sentence that the prompt carries as an example must not be removed."""
    from crime_risk_analyzer.rag.istat_rules import ESEMPIO_ISTAT

    sentence = ESEMPIO_ISTAT.strip('"')
    text = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{sentence}\n"
    outcome = _check(text)
    assert [
        (f.motivo, f.confronto_coerente, f.direzione_coerente)
        for f in outcome.frasi
        if f.blocco == "ontologia"
    ] == [(None, True, True)]


# --- #365, second real trial: ISTAT sentences without explicit markers ---

_COMPUTER = make_row(
    "CYBERCRIME",
    label="delitti informatici",
    rate=120.0,
    italy=80.0,
    variation=12,
    links=(make_link("Cyber_attack", "Attacco informatico", "piu_larga"),),
)
_STREET = make_row(
    "STREETROB",
    label="rapine in pubblica via",
    rate=90.0,
    italy=40.0,
    variation=32,
    links=(make_link("Mugging", "Aggressione a scopo di furto", "esatta"),),
)
_REAL_ZONE = istat_block_for_zone(
    [{"poi_id": "a", "istat": istat_poi(_MUNICIPALITY, _COMPUTER, _STREET)}],
    estimate_tokens=len,
    token_limit=None,
)


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        # the three sentences of the real trial: they talk about the datum without saying the place
        (
            "I **delitti informatici** mostrano un tasso più alto e una crescita "
            "dal 2014, con la voce più ampia del rischio.",
            "luogo_mancante",
        ),
        (
            "Le **rapine in pubblica via** hanno un tasso più alto e una crescita "
            "dal 2014, con la voce più ampia del rischio.",
            "luogo_mancante",
        ),
        (
            "I **furti** hanno un tasso più alto ma sono in calo dal 2014, la voce "
            "è più ampia del rischio.",
            "luogo_mancante",
        ),
        # named item + one of the markers: rate, "dal 2014", item
        ("I furti sono in calo dal 2014.", "luogo_mancante"),
        ("Per i furti la voce è più ampia del rischio.", "luogo_mancante"),
        # also with the name of the linked risk (as in C1)
        ("L'aggressione a scopo di furto ha un tasso più alto.", "luogo_mancante"),
        # with the place: the implicit comparison ("tasso più alto") is verified
        ("Nel Comune di Roma i furti hanno un tasso più alto.", None),
        ("Nel Comune di Roma i furti hanno un tasso più basso.", "confronto_contrario"),
        (
            "Nel Comune di Roma i **delitti informatici** hanno un tasso più alto e "
            "sono in crescita dal 2014.",
            None,
        ),
        # false positives: no ISTAT item, or item without rate/year/item
        ("Il tasso di affollamento della stazione è più alto la sera.", None),
        ("Ci sono furti nella stazione.", None),
        ("I furti nella stazione sono favoriti dalla folla.", None),
    ],
)
def test_sentence_naming_an_item_and_a_marker_talks_about_istat(
    sentence: str, expected: Reason | None
) -> None:
    text = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{sentence}\n"
    outcome = _check_with(text, _REAL_ZONE)
    assert [f.motivo for f in outcome.frasi if f.blocco == "ontologia"] == [expected]


def test_the_crowding_rate_does_not_talk_about_istat() -> None:
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        "Il tasso di affollamento della stazione è più alto la sera.\n"
    )
    sentence = [f for f in _check_with(text, _REAL_ZONE).frasi][-1]
    assert (sentence.parla_di_istat, sentence.voci) == (False, ())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("i furti hanno un tasso più alto", "piu_alto"),
        ("un tasso decisamente più basso", "piu_basso"),
        ("un tasso simile", "simile"),
        ("hanno un tasso più alto ma sono in calo", "piu_alto"),
        # "tasso" far away or in another clause does not anchor the comparison
        ("il tasso di affollamento, nelle ore di punta, e' piu' alto", ""),
    ],
)
def test_rate_as_anchor_of_the_implicit_comparison(text: str, expected: str) -> None:
    assert comparison_of(text) == expected


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        (
            "Secondo i dati ISTAT del **Comune di Roma (2024)**, i **delitti "
            "denunciati** hanno un tasso più alto di quello italiano (voce di "
            "contesto generale).",
            None,
        ),
        (
            "Secondo i dati ISTAT del Comune di Roma, i delitti denunciati hanno un "
            "tasso più basso di quello italiano.",
            "confronto_contrario",
        ),
        # if another item is named that one applies, not the total
        (
            "Secondo l'ISTAT, nel Comune di Roma i delitti denunciati per furti "
            "hanno un tasso più alto di quello italiano.",
            None,
        ),
    ],
)
def test_reported_offences_resolves_to_the_total(
    sentence: str, expected: Reason | None
) -> None:
    text = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{sentence}\n"
    outcome = _check_with(text, _REAL_ZONE)
    sentences = [f for f in outcome.frasi if f.blocco == "ontologia"]
    assert [f.motivo for f in sentences] == [expected]
    if "per furti" in sentence:
        assert sentences[0].voci == ("THEFT",)


@pytest.mark.parametrize(
    "sentence",
    [
        # "_" is a word character: without removing it "_furti_" does not name the thefts
        "I _furti_ hanno un tasso più alto ma sono in calo dal 2014.",
        # bold inside a multi-word label
        "Le **rapine** in pubblica via hanno un tasso più alto dal 2014.",
    ],
)
def test_markdown_does_not_hide_the_item(sentence: str) -> None:
    text = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{sentence}\n"
    outcome = _check_with(text, _REAL_ZONE)
    assert [f.motivo for f in outcome.frasi if f.blocco == "ontologia"] == [
        "luogo_mancante"
    ]


# --- #365, third real trial: the place holds for the rest of the paragraph ---


def _ontology(body: str) -> str:
    return f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{body}\n"


def _reasons(outcome: CheckOutcome, block: str = "ontologia") -> list[Reason | None]:
    return [f.motivo for f in outcome.frasi if f.blocco == block]


def test_list_after_the_place_inherits_it() -> None:
    """Termini case: the place in the introduction holds for the items of the list."""
    body = (
        "I dati ISTAT del **Comune di Roma** (2024) forniscono indicazioni utili "
        "per alcuni di questi rischi:  \n"
        "- Per il **Rischio informatico**, la voce “delitti informatici” "
        "presenta un tasso più alto rispetto alla media italiana e una tendenza in "
        "crescita dal 2014; la voce è più ampia del rischio specifico.\n"
        "- Per il **Furto di rame**, la voce “furti” registra un tasso più "
        "alto rispetto alla media nazionale ma una tendenza in calo dal 2014; la "
        "voce è più ampia del rischio."
    )
    text = _ontology(body)
    outcome = _check_with(text, _REAL_ZONE)
    sentences = [f for f in outcome.frasi if f.blocco == "ontologia"]
    assert [(f.motivo, f.luogo, f.luogo_ereditato) for f in sentences] == [
        (None, True, False),
        (None, False, True),
        (None, False, True),
    ]
    assert [(f.confronto_coerente, f.direzione_coerente) for f in sentences[1:]] == [
        (True, True),
        (True, True),
    ]
    assert outcome.testo_filtrato == text


def test_next_sentence_of_the_zone_inherits_the_place() -> None:
    text = _ontology(
        "Questo aggregato è corroborato dai dati ISTAT del Comune di Roma (2024), "
        "che indicano per i furti un tasso più alto di quello italiano. Inoltre, le "
        "rapine in pubblica via mostrano un tasso più alto dell'italiano e una "
        "crescita dal 2014."
    )
    assert _reasons(_check_with(text, _REAL_ZONE)) == [None, None]


def test_the_blank_line_stops_inheritance() -> None:
    text = _ontology(
        "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo.\n\n"
        "Le rapine in pubblica via hanno un tasso più alto dal 2014."
    )
    assert _reasons(_check_with(text, _REAL_ZONE)) == [None, "luogo_mancante"]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        # inherits the Comune (thefts declining): "in crescita" is contrary
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo. I furti sono "
            "in crescita dal 2014.",
            [None, "direzione_contraria"],
        ),
        # inherits the Provincia (thefts rising)
        (
            "Secondo l'ISTAT, nella Provincia di Roma i furti sono in aumento. I "
            "furti sono in crescita dal 2014.",
            [None, None],
        ),
        # a new place replaces the inherited one
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo. Secondo "
            "l'ISTAT nella Provincia di Roma i furti sono in aumento. I furti sono "
            "in crescita dal 2014.",
            [None, None, None],
        ),
    ],
)
def test_the_inherited_place_decides_the_verification(
    body: str, expected: list[Reason | None]
) -> None:
    assert _reasons(_check_with(_ontology(body), _TWO_PLACES)) == expected


def test_a_removed_sentence_does_not_pass_the_place() -> None:
    text = _ontology(
        "Secondo l'ISTAT, nel Comune di Roma i furti sono in aumento. Le rapine in "
        "pubblica via hanno un tasso più alto dal 2014."
    )
    assert _reasons(_check_with(text, _REAL_ZONE)) == [
        "direzione_contraria",
        "luogo_mancante",
    ]


def test_a_sentence_not_about_istat_does_not_pass_the_place() -> None:
    text = _ontology(
        "Nel Comune di Roma la folla è intensa. Le rapine in pubblica via hanno un "
        "tasso più alto dal 2014."
    )
    assert _reasons(_check_with(text, _REAL_ZONE)) == [None, "luogo_mancante"]


def test_no_inheritance_across_blocks() -> None:
    """From the synthesis to a block and between two blocks, even without a blank line."""
    text = (
        "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo.\n"
        "Rischi da ontologia [ONTOLOGIA]\n"
        "Le rapine in pubblica via hanno un tasso più alto dal 2014.\n"
        "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo.\n"
        "Rischi dal contesto [CONTESTO]\n"
        "I furti hanno un tasso più alto dal 2014.\n"
    )
    outcome = _check_with(text, _REAL_ZONE)
    assert _reasons(outcome, "overview") == [None]
    assert _reasons(outcome) == ["luogo_mancante", None]
    assert _reasons(outcome, "contesto") == ["luogo_mancante"]


# --- #365, fix 4: "tasso" and "voce" as markers only in the ISTAT sense ---

_THEFTS_WITH_RISKS = istat_block_for_poi(
    istat_poi(
        make_row(
            links=(
                make_link("Vehicle_Theft", "Furto di veicolo", "piu_stretta"),
                make_link("Copper_theft", "Furto di rame", "piu_larga"),
                make_link("Goods_theft", "Furto di merci", "piu_larga"),
            )
        ),
        _DAMAGES,
    )
)


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        # false positive of the real trial: "tasso" inside a vulnerability
        (
            "Questa tendenza è rafforzata dalla presenza di *Furto di veicolo*, "
            "*Furto di rame* e *Furto di merci*, tutti collegati a una "
            "vulnerabilità di *Area ad alto tasso di criminalità* e a una "
            "*Carenza di personale* sia nella polizia che nei servizi di controllo.",
            None,
        ),
        ("I furti colpiscono un'Area ad alto tasso di criminalità.", None),
        ("I furti nella zona danno voce al disagio dei residenti.", None),
        # real sentences of the previous rounds: still recognised (without place)
        (
            "I **furti** hanno un tasso più alto ma sono in calo dal 2014, la voce "
            "è più ampia del rischio.",
            "luogo_mancante",
        ),
        ("I furti hanno un tasso più alto.", "luogo_mancante"),
        (
            "La stazione registra un tasso di **danneggiamenti** più alto.",
            "luogo_mancante",
        ),
        ("Il tasso dei furti preoccupa.", "luogo_mancante"),
        # "voce" in the ISTAT sense
        ("Per i furti la voce è più ampia del rischio.", "luogo_mancante"),
        ("I furti, voce ISTAT collegata, preoccupano.", "luogo_mancante"),
        ("Per i furti questa voce non coincide con il rischio.", "luogo_mancante"),
        # only "voce ... coincide" marks this sentence
        ("I furti come voce non coincidono col furto di rame.", "luogo_mancante"),
        ("I furti sono una voce più ampia del furto di rame.", "luogo_mancante"),
    ],
)
def test_rate_and_item_mark_only_in_the_istat_sense(
    sentence: str, expected: Reason | None
) -> None:
    text = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{sentence}\n"
    outcome = _check_with(text, _THEFTS_WITH_RISKS)
    assert [f.motivo for f in outcome.frasi if f.blocco == "ontologia"] == [expected]


# --- #365, fix 5 (final review) ---

_SIMILAR_SNATCHINGS = make_row(
    "SNATCH", label="scippi", rate=100.0, italy=100.0, variation=5
)
_THEFTS_AND_SNATCHINGS = istat_block_for_poi(
    istat_poi(_MUNICIPALITY, _SIMILAR_SNATCHINGS)
)


@pytest.mark.parametrize(
    ("sentence", "block", "expected"),
    [
        # C-1: all the named items must agree (thefts declining, robberies in
        # shops rising: "in crescita" holds for only one)
        (
            "Nel Comune di Roma, secondo l'ISTAT, i furti e le rapine in esercizi "
            "commerciali sono in crescita dal 2014.",
            _BLOCK,
            "direzione_contraria",
        ),
        (
            "Nel Comune di Roma, secondo l'ISTAT, i furti e le rapine in pubblica "
            "via hanno un tasso simile a quello italiano.",
            _REAL_ZONE,
            "confronto_contrario",
        ),
        # "simile" is right for snatchings but not for thefts
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti e gli scippi hanno un "
            "tasso simile a quello italiano.",
            _THEFTS_AND_SNATCHINGS,
            "confronto_contrario",
        ),
        (
            "Secondo l'ISTAT, nel Comune di Roma gli scippi hanno un tasso simile a "
            "quello italiano.",
            _THEFTS_AND_SNATCHINGS,
            None,
        ),
        # two items both consistent: it stays
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti e le rapine in pubblica via "
            "hanno un tasso più alto di quello italiano.",
            _REAL_ZONE,
            None,
        ),
    ],
)
def test_all_the_named_items_must_agree(
    sentence: str, block: IstatBlock, expected: Reason | None
) -> None:
    text = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{sentence}\n"
    assert _reasons(_check_with(text, block)) == [expected]


def test_list_with_inherited_place_counts_items_with_trend_or_comparison() -> None:
    """C-2: after "I dati ISTAT del Comune di Roma (2024) indicano:" a list
    line with an item and a trend or comparison talks about the datum."""
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        "I dati ISTAT del Comune di Roma (2024) indicano:\n"
        "- furti: in crescita;\n"
        "- furti: più alti della media;\n"
        "- danneggiamenti: in crescita.\n"
    )
    sentences = [f for f in _check(text).frasi if f.blocco == "ontologia"]
    assert [(f.motivo, f.parla_di_istat) for f in sentences] == [
        (None, True),
        ("direzione_contraria", True),
        (None, True),
        ("direzione_contraria", True),
    ]
    assert sentences[2].confronto_coerente is True


def test_without_inherited_place_the_list_line_stays_out() -> None:
    """C-2 only holds inside the paragraph with a place: without it, R1 stays."""
    text = "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n- furti: in crescita;\n"
    sentences = [f for f in _check(text).frasi if f.blocco == "ontologia"]
    assert [(f.motivo, f.parla_di_istat) for f in sentences] == [(None, False)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("un tasso meno elevato della media", "piu_basso"),
        ("un tasso meno alto di quello italiano", "piu_basso"),
        ("un tasso meno basso di quello italiano", "piu_alto"),
        ("sono meno frequenti della media", "piu_basso"),
        ("sono meno diffusi rispetto al dato nazionale", "piu_basso"),
        ("sono più frequenti della media", "piu_alto"),
        ("sono più diffusi rispetto al dato nazionale", "piu_alto"),
        ("sono più elevati di quelli italiani", "piu_alto"),
        ("superano la media italiana", "piu_alto"),
        ("il tasso supera quello italiano", "piu_alto"),
        ("un tasso pari a quello italiano", "simile"),
        # C-4: the term of comparison is not the adjective "italiani" alone
        ("anche per una minore presenza di turisti italiani", ""),
        ("valori inferiori al livello nazionale", "piu_basso"),
        ("valori superiori al valore nazionale", "piu_alto"),
        ("valori superiori all'Italia", "piu_alto"),
    ],
)
def test_review_comparison_words(text: str, expected: str) -> None:
    assert comparison_of(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("i furti sono stabili", "stabile"),
        ("i furti si sono ridotti", "giu"),
        ("le rapine si sono ridotte", "giu"),
        ("i furti sono diminuiti", "giu"),
        ("le rapine sono diminuite", "giu"),
        ("i furti sono cresciuti", "su"),
        ("le rapine sono cresciute", "su"),
        # R1 stays: the adjective "ridotta" is not a trend
        ("la visibilita' ridotta", ""),
        ("stabile ma in calo", ""),
    ],
)
def test_review_trend_words(text: str, expected: str) -> None:
    assert direction_of(text) == expected


@pytest.mark.parametrize(
    ("variation", "expected"),
    [(0, None), (-10, "direzione_contraria"), (5, "direzione_contraria")],
)
def test_stable_is_verified_only_with_zero_variation(
    variation: int, expected: Reason | None
) -> None:
    """C-3: the block writes "stabile dal 2014" only with variation 0."""
    block = istat_block_for_poi(istat_poi(make_row(variation=variation)))
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        "Secondo l'ISTAT, nel Comune di Roma i furti sono stabili dal 2014.\n"
    )
    assert _reasons(_check_with(text, block)) == [expected]


def test_adjective_italiani_is_not_a_comparison() -> None:
    """C-4: "minore presenza di turisti italiani" does not compare with the datum."""
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo dal 2014, anche "
        "per una minore presenza di turisti italiani.\n"
    )
    sentences = [f for f in _check(text).frasi if f.blocco == "ontologia"]
    assert [(f.motivo, f.confronto) for f in sentences] == [(None, "")]


def test_item_codes_counted_in_the_outcome() -> None:
    """Question 2: the row codes written by the model are counted, not
    removed; only uppercase and whole word."""
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        "Secondo l'ISTAT, nel Comune di Roma la voce THEFT e' in calo (THEFT). "
        "Theft e THEFTS non contano; DAMAGE si'.\n"
    )
    outcome = _check(text)
    assert outcome.codici_voce == 3
    assert outcome.frasi_scartate == 0


@pytest.mark.parametrize(
    ("sentence", "block", "expected"),
    [
        # damage has no computed trend: the sentence is not verifiable
        # even if "in calo" is right for thefts
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti e i danneggiamenti sono in "
            "calo.",
            _BLOCK,
            "direzione_contraria",
        ),
        # snatchings have no comparison (missing national)
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti e gli scippi hanno un tasso "
            "più alto di quello italiano.",
            istat_block_for_poi(
                istat_poi(_MUNICIPALITY, make_row("SNATCH", label="scippi", italy=None))
            ),
            "confronto_contrario",
        ),
    ],
)
def test_an_unverifiable_item_makes_the_sentence_unverifiable(
    sentence: str, block: IstatBlock, expected: Reason | None
) -> None:
    """C-1: with several items it is enough that one is not verifiable to remove."""
    text = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{sentence}\n"
    assert _reasons(_check_with(text, block)) == [expected]


# --- #365, fix 6: introduction with ":" and list after a blank line ---

_INTRO_TERMINI = (
    "I dati ISTAT del **Comune di Roma** (2024) forniscono indicazioni "
    "quantitative per alcuni di questi temi:  "
)
_COMPUTER_ITEM = (
    "Per i **delitti informatici** (collegati al rischio informatico), il tasso è "
    "più alto di quello italiano e in crescita dal 2014; la voce è più ampia del "
    "rischio."
)
_THEFTS_ITEM = (
    "Per i **furti** (collegati al furto di rame), il tasso è più alto di quello "
    "italiano ma in calo dal 2014; la voce è più ampia del rischio."
)
_SENTENCE_WITHOUT_PLACE = "Le rapine in pubblica via hanno un tasso più alto dal 2014."


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        # the real case: introduction with ":", blank line, list
        (
            f"{_INTRO_TERMINI}\n\n- {_COMPUTER_ITEM}\n- {_THEFTS_ITEM}",
            [None, None, None],
        ),
        # also with several blank lines before the first item and other markers
        (
            f"{_INTRO_TERMINI}\n\n\n* {_COMPUTER_ITEM}\n* {_THEFTS_ITEM}",
            [None, None, None],
        ),
        (
            f"{_INTRO_TERMINI}\n\n1. {_COMPUTER_ITEM}\n2. {_THEFTS_ITEM}",
            [None, None, None],
        ),
        # "wide" list: blank lines also between the items, the list continues
        (
            f"{_INTRO_TERMINI}\n\n- {_COMPUTER_ITEM}\n\n- {_THEFTS_ITEM}",
            [None, None, None],
        ),
        # introduction without ":": the blank line interrupts as before
        (
            "I dati ISTAT del **Comune di Roma** (2024) danno indicazioni per alcuni "
            f"temi.\n\n- {_COMPUTER_ITEM}\n- {_THEFTS_ITEM}",
            [None, "luogo_mancante", "luogo_mancante"],
        ),
        # list interrupted by a normal paragraph: the inheritance stops
        (
            f"{_INTRO_TERMINI}\n\n- {_COMPUTER_ITEM}\n\n{_SENTENCE_WITHOUT_PLACE}\n"
            f"- {_THEFTS_ITEM}",
            [None, None, "luogo_mancante", "luogo_mancante"],
        ),
        # ... even without a blank line between the list and the paragraph
        (
            f"{_INTRO_TERMINI}\n- {_COMPUTER_ITEM}\n{_SENTENCE_WITHOUT_PLACE}",
            [None, None, "luogo_mancante"],
        ),
        # a removed introduction does not pass the place even to the list
        (
            "I dati ISTAT del Comune di Roma (2024) indicano furti in aumento:\n\n"
            f"- {_COMPUTER_ITEM}",
            ["direzione_contraria", "luogo_mancante"],
        ),
    ],
)
def test_introduction_with_colon_passes_the_place_to_the_list(
    body: str, expected: list[Reason | None]
) -> None:
    text = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{body}\n"
    assert _reasons(_check_with(text, _REAL_ZONE)) == expected


def test_the_list_does_not_inherit_across_blocks() -> None:
    text = (
        f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{_INTRO_TERMINI}\n\n"
        f"Rischi dal contesto [CONTESTO]\n- {_THEFTS_ITEM}\n"
    )
    outcome = _check_with(text, _REAL_ZONE)
    assert _reasons(outcome, "contesto") == ["luogo_mancante"]


def test_the_list_must_follow_the_introduction_immediately() -> None:
    """Fix 6: if between the introduction with ":" and the list there is another sentence,
    the blank lines before the list interrupt the inheritance as always."""
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        f"{_INTRO_TERMINI}\nSecondo l'ISTAT i furti sono in calo.\n\n"
        f"- {_THEFTS_ITEM}\n"
    )
    assert _reasons(_check_with(text, _REAL_ZONE)) == [
        None,
        None,
        "luogo_mancante",
    ]


# --- #385: the check only removes the sentences that really talk about the datum ---

_INTRO_ROMA = (
    "I dati ISTAT del Comune di Roma (2024) indicano per i furti un tasso più alto "
    "di quello italiano, in calo dal 2014."
)


@pytest.mark.parametrize(
    "sentence",
    [
        "I furti sono favoriti dalla crescita del turismo nell'area.",
        "Il furto di beni resta stabile come vulnerabilità tutto l'anno.",
        "Le rapine in esercizi commerciali sono in calo nelle ore notturne...",
        "I furti sono meno frequenti della media nelle ore notturne.",
    ],
)
def test_inherited_place_and_trend_are_not_enough(sentence: str) -> None:
    """#385: with the inherited place a trend or comparison word and the name of
    an item (or a risk) do not make a sentence about the risk talk about the datum."""
    text = _ontology(f"{_INTRO_ROMA} {sentence}")
    outcome = _check(text)
    assert [(f.motivo, f.parla_di_istat) for f in outcome.frasi[-2:]] == [
        (None, True),
        (None, False),
    ]
    assert outcome.testo_filtrato == text


@pytest.mark.parametrize(
    "introduction",
    [
        "Nel Comune di Roma, secondo l'ISTAT, i furti hanno un tasso più alto di "
        "quello italiano. I rischi dell'ontologia sono:",
        # the ISTAT introduction itself opens the list
        "Nel Comune di Roma, secondo l'ISTAT, i furti hanno un tasso più alto di "
        "quello italiano e i rischi dell'ontologia sono:",
    ],
)
def test_risk_list_after_an_istat_sentence_stays(introduction: str) -> None:
    """#385, worst case: the list items about the risks stay (before only
    "sono:" stayed)."""
    text = _ontology(
        f"{introduction}\n"
        "- **Furto di beni**: la crescita dei flussi turistici aumenta i borseggi.\n"
        "- Furto di beni stabile nelle ore di punta per la folla."
    )
    outcome = _check(text)
    assert _reasons(outcome) == [None] * len(_reasons(outcome))
    assert outcome.testo_filtrato == text


@pytest.mark.parametrize(
    ("block", "sentence"),
    [
        (
            "ontologia",
            "Il dato italiano della sicurezza stradale è migliorato negli ultimi anni.",
        ),
        ("ontologia", "Il quartiere ha un'età media superiore alla media nazionale."),
        ("contesto", "Il quartiere ha un'età media superiore alla media nazionale."),
        ("ontologia", "Il tasso nazionale di disoccupazione giovanile è alto."),
        (
            "ontologia",
            "Rispetto all'Italia del Nord, l'area ha più presenze turistiche.",
        ),
        ("contesto", "Quello italiano è un contesto turistico maturo."),
    ],
)
def test_national_sentence_without_item_does_not_talk_about_istat(
    block: str, sentence: str
) -> None:
    """#385: "media/dato/tasso nazionale", "quello italiano", "rispetto
    all'Italia" only count with an item, a linked risk, ISTAT or the
    delitti denunciati."""
    text = f"Sintesi.\n\n{_HEADERS[block]}\n{sentence}\n"
    sentences = [f for f in _check(text).frasi if f.blocco == block]
    assert [(f.motivo, f.parla_di_istat) for f in sentences] == [(None, False)]


@pytest.mark.parametrize(
    "sentence",
    [
        "Il furto di beni è sopra la media nazionale.",
        "Rispetto all'Italia il furto di beni è in calo.",
    ],
)
def test_national_sentence_with_linked_risk_talks_about_istat(sentence: str) -> None:
    """#385: with a linked risk the national formula remains a marker."""
    text = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{sentence}\n"
    assert _reasons(_check(text)) == ["luogo_mancante"]


_SNATCHINGS_BELOW_THRESHOLD = make_row(
    "SNATCH",
    label="scippi",
    offences=25,
    comparison=12,
    rate=20.0,
    italy=30.0,
    variation=None,
    reason=REASON_BELOW_THRESHOLD,
)
_DAMAGE_2016 = make_row(
    "DAMAGE",
    label="danneggiamenti",
    offences=2016,
    comparison=1800,
    rate=721.2,
    italy=471.5,
    variation=None,
    reason=REASON_BREAK_2016,
    rottura_2016=True,
)
_THRESHOLD_AND_2016 = istat_block_for_poi(
    istat_poi(_MUNICIPALITY, _SNATCHINGS_BELOW_THRESHOLD, _DAMAGE_2016)
)


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("Le voci con meno di 20 delitti in un anno non hanno tendenza.", None),
        ("Dopo la depenalizzazione del 2016 alcuni danneggiamenti...", None),
        # an ISTAT figure that the block does not write stays removed
        ("Nel 2024 si contano 25 scippi.", "cifra_istat_fuori_blocco"),
    ],
)
def test_the_numbers_of_the_block_are_not_istat_figures(
    sentence: str, expected: Reason | None
) -> None:
    """#385: the threshold and the decriminalisation year that the block writes do not
    count as ISTAT figures, even if they coincide with a rate or a count."""
    assert "meno di 20 delitti" in _THRESHOLD_AND_2016.testo
    assert "del 2016" in _THRESHOLD_AND_2016.testo
    text = _ontology(sentence)
    # context without numbers: "20" does not coincide by chance (cf. "su 20" of _CONTEXT)
    outcome = _check_with(text, _THRESHOLD_AND_2016, context="ZONA: Colosseo")
    assert _reasons(outcome) == [expected]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        # the linked risk counts as an item at the head of the line: furto di beni is
        # also linked to the rising robberies, "in calo" does not hold for all
        ("- Furto di beni: in calo;", ("direzione_contraria", True)),
        ("- **Furto di beni**: più alto della media;", (None, True)),
        # long line: it is prose about the risk, not a data line
        (
            "- furti: in crescita la sera, quando la folla riempie la piazza;",
            (None, False),
        ),
        (
            "- I furti nelle ore serali di punta della piazza: in crescita;",
            (None, False),
        ),
        # after the colon there is neither a trend nor a comparison
        ("- furti: borseggi sui mezzi;", (None, False)),
        # at the head of the line there is neither an item nor a risk
        ("- Turismo: in crescita;", (None, False)),
        ("- Turismo: furti in crescita;", (None, False)),
    ],
)
def test_short_list_line_after_istat_introduction(
    body: str, expected: tuple[Reason | None, bool]
) -> None:
    text = _ontology(f"I dati ISTAT del Comune di Roma (2024) indicano:\n{body}")
    sentences = [f for f in _check(text).frasi if f.blocco == "ontologia"]
    assert [(f.motivo, f.parla_di_istat) for f in sentences] == [(None, True), expected]


def test_a_new_explicit_place_closes_the_istat_list() -> None:
    """#385: after an ISTAT sentence with an explicit place that does not end with ":"
    the "furti: in crescita" form is no longer enough, even if the place stays."""
    text = _ontology(
        "I dati ISTAT del Comune di Roma (2024) indicano:\n"
        "Secondo l'ISTAT nel Comune di Roma i furti sono in calo.\n"
        "furti: in crescita;"
    )
    sentences = [f for f in _check(text).frasi if f.blocco == "ontologia"]
    assert [(f.motivo, f.parla_di_istat) for f in sentences] == [
        (None, True),
        (None, True),
        (None, False),
    ]


# --- #386: plurals, negations, missing forms, several places in full ---
# Test case: thefts in the Comune di Roma with a rate higher than the Italian one and
# declining since 2014; robberies in shops higher and growing;
# damage without trend (2016 break).


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        # plurals: "tassi", "quelli italiani", "valori nazionali", "livelli italiani"
        ("Nel Comune di Roma i furti hanno tassi più bassi.", "confronto_contrario"),
        ("I tassi dei furti sono inferiori a quelli italiani.", "luogo_mancante"),
        (
            "Nel Comune di Roma i tassi dei furti sono inferiori a quelli italiani.",
            "confronto_contrario",
        ),
        (
            "Nel Comune di Roma i furti hanno tassi inferiori ai valori nazionali.",
            "confronto_contrario",
        ),
        (
            "Nel Comune di Roma i furti sono sotto i livelli italiani.",
            "confronto_contrario",
        ),
        # negations
        (
            "Nel Comune di Roma il tasso dei furti non è più alto di quello italiano.",
            "confronto_contrario",
        ),
        (
            "Nel Comune di Roma i furti non hanno un tasso più alto di quello italiano.",
            "confronto_contrario",
        ),
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti non sono in calo.",
            "direzione_contraria",
        ),
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti non sono più in calo.",
            "direzione_contraria",
        ),
        (
            "Secondo l'ISTAT, nel Comune di Roma non c'è nessun calo dei furti.",
            "direzione_contraria",
        ),
        # negation on an item without a computed trend: not verifiable
        (
            "Secondo l'ISTAT, nel Comune di Roma i danneggiamenti non sono in calo.",
            "direzione_contraria",
        ),
        # missing comparison forms
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti sono meno che nel resto d'Italia.",
            "confronto_contrario",
        ),
        (
            "Nel Comune di Roma i furti sono meno numerosi che in Italia.",
            "confronto_contrario",
        ),
        (
            "Nel Comune di Roma i furti sono più rari che in Italia.",
            "confronto_contrario",
        ),
        (
            "Nel Comune di Roma il tasso dei furti è più ridotto di quello italiano.",
            "confronto_contrario",
        ),
        (
            "Nel Comune di Roma i furti sono meno frequenti che nel resto d'Italia.",
            "confronto_contrario",
        ),
        # missing trend forms
        (
            "Nel Comune di Roma i furti sono in ripresa dal 2014.",
            "direzione_contraria",
        ),
        (
            "Nel Comune di Roma i furti sono raddoppiati dal 2014.",
            "direzione_contraria",
        ),
    ],
)
def test_wrong_sentences_of_check_386_are_removed(
    sentence: str, expected: Reason
) -> None:
    """#386: false sentences that the check used to leave in the text."""
    text = _ontology(sentence)
    outcome = _check(text)
    assert _reasons(outcome) == [expected]
    assert sentence not in outcome.testo_filtrato


@pytest.mark.parametrize(
    "sentence",
    [
        # the negation inverts: right on an item that is rising or higher
        "Secondo l'ISTAT, nel Comune di Roma le rapine in esercizi commerciali non "
        "sono in calo.",
        "Secondo l'ISTAT, nel Comune di Roma i furti non sono in crescita.",
        "Nel Comune di Roma il tasso dei furti non è più basso di quello italiano.",
        "Nel Comune di Roma il tasso dei furti non è simile a quello italiano.",
        # the negation in another clause does not count
        "Secondo l'ISTAT, nel Comune di Roma i furti, che non mancano, sono in calo.",
        # pleonastic "non" after the comparison, "non solo": they do not negate
        "Nel Comune di Roma il tasso dei furti è più alto di quanto non sia quello "
        "italiano.",
        "Secondo l'ISTAT, nel Comune di Roma i furti non solo sono in calo dal 2014.",
        # new plurals and forms, right
        "Nel Comune di Roma i furti hanno tassi più alti dell'italiano.",
        "Nel Comune di Roma i furti hanno tassi più alti.",
        "Nel Comune di Roma i tassi dei furti sono superiori a quelli italiani.",
        "Nel Comune di Roma i furti sono più numerosi che in Italia.",
        "Nel Comune di Roma i furti sono più che nel resto d'Italia.",
        "Secondo l'ISTAT, nel Comune di Roma le rapine in esercizi commerciali sono "
        "in ripresa dal 2014.",
        "Nel Comune di Roma le rapine in esercizi commerciali sono raddoppiate dal "
        "2014.",
    ],
)
def test_right_sentences_of_check_386_stay(sentence: str) -> None:
    text = _ontology(sentence)
    outcome = _check(text)
    assert _reasons(outcome) == [None]
    assert outcome.frasi[-1].parla_di_istat
    assert outcome.testo_filtrato == text


@pytest.mark.parametrize(
    "sentence",
    [
        "Il quartiere non ha un'età media superiore alla media nazionale.",
        "I tassi di affollamento della stazione non sono più alti la sera.",
        "La ripresa delle telecamere non copre i furti nella stazione.",
    ],
)
def test_sentences_without_istat_datum_of_check_386_stay(sentence: str) -> None:
    """#386 does not widen what talks about the datum: no item, no ISTAT (#385)."""
    text = _ontology(sentence)
    outcome = _check(text)
    assert [(f.motivo, f.parla_di_istat) for f in outcome.frasi[-1:]] == [(None, False)]
    assert outcome.testo_filtrato == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("i furti hanno tassi più bassi", "piu_basso"),
        ("sono inferiori a quelli italiani", "piu_basso"),
        ("tassi inferiori ai valori nazionali", "piu_basso"),
        ("sotto i livelli italiani", "piu_basso"),
        ("sotto i dati nazionali", "piu_basso"),
        ("meno che nel resto d'Italia", "piu_basso"),
        ("meno numerosi che in Italia", "piu_basso"),
        ("più rari che in Italia", "piu_basso"),
        ("più ridotto di quello italiano", "piu_basso"),
        ("meno frequenti che nel resto d'Italia", "piu_basso"),
        ("più numerosi che in Italia", "piu_alto"),
        ("meno rari che in Italia", "piu_alto"),
        ("più che nel resto d'Italia", "piu_alto"),
        ("tassi più alti dell'italiano", "piu_alto"),
    ],
)
def test_comparison_words_386(text: str, expected: str) -> None:
    assert comparison_of(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("i furti sono in ripresa", "su"),
        ("i furti sono raddoppiati", "su"),
        ("le rapine sono raddoppiate", "su"),
        # "ripresa" without "in" is not a trend
        ("la ripresa delle telecamere", ""),
    ],
)
def test_trend_words_386(text: str, expected: str) -> None:
    assert direction_of(text) == expected


def test_the_negation_is_in_the_outcome() -> None:
    text = _ontology(
        "Secondo l'ISTAT, nel Comune di Roma i furti non sono in crescita. Nel "
        "Comune di Roma il tasso dei furti non è più basso di quello italiano."
    )
    direction, comparison = _check(text).frasi[-2:]
    assert (direction.direzione, direction.direzione_negata) == ("su", True)
    assert direction.direzione_coerente is True
    assert (comparison.confronto, comparison.confronto_negato) == ("piu_basso", True)
    assert comparison.confronto_coerente is True


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        # (a) several places in full: the sentence must hold for all
        (
            "Secondo l'ISTAT, nel Comune di Roma e nella Provincia di Roma i furti "
            "sono in crescita.",
            ["direzione_contraria"],
        ),
        (
            "Secondo l'ISTAT, nella Provincia di Roma e nel Comune di Roma i furti "
            "sono in calo.",
            ["direzione_contraria"],
        ),
        (
            "Secondo l'ISTAT, nel Comune di Roma e nella Provincia di Roma i furti "
            "hanno un tasso più alto di quello italiano.",
            [None],
        ),
        # the places in full pass to the next sentence, still all of them
        (
            "Secondo l'ISTAT, nel Comune di Roma e nella Provincia di Roma i furti "
            "hanno un tasso più alto di quello italiano. I furti sono in crescita "
            "dal 2014.",
            [None, "direzione_contraria"],
        ),
    ],
)
def test_several_places_in_full_must_all_agree(
    body: str, expected: list[Reason | None]
) -> None:
    assert _reasons(_check_with(_ontology(body), _TWO_PLACES)) == expected


@pytest.mark.parametrize(
    "body",
    [
        "Secondo l'ISTAT, a Roma i furti sono in crescita.",
        "Secondo l'ISTAT, a Roma i furti sono in calo.",
        # the short name passes the place to the next sentence with the same rule
        "Secondo l'ISTAT, a Roma i furti hanno un tasso più alto di quello "
        "italiano. I furti sono in crescita dal 2014.",
    ],
)
def test_limit_the_short_name_only_needs_one_place_to_agree(body: str) -> None:
    """Declared limit (R6, #386 b): "Roma" holds for the municipality and the province and
    the sentence stays if it agrees with at least one. "A Roma i furti sono in crescita"
    passes even if in the municipality they are declining (rising in the province)."""
    outcome = _check_with(_ontology(body), _TWO_PLACES)
    assert _reasons(outcome) == [None] * len(_reasons(outcome))


def test_limit_a_nearby_negation_inverts_even_if_it_does_not_govern_the_word() -> None:
    """Declared limit (#386): "non" less than 4 words from the trend negates it
    even when it governs another word; the right sentence is removed."""
    text = _ontology(
        "Secondo l'ISTAT, nel Comune di Roma i furti non denunciati sono in calo."
    )
    assert _reasons(_check(text)) == ["direzione_contraria"]


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        # only "quelli italiani" makes it talk about the datum
        (
            "Nel Comune di Roma i furti sono inferiori a quelli italiani.",
            "confronto_contrario",
        ),
        # only "tassi dei <item>" makes it talk about the datum
        ("I tassi dei furti preoccupano.", "luogo_mancante"),
        # the negation sits between "tasso" and the comparison word
        (
            "Nel Comune di Roma il tasso non è più alto per i furti.",
            "confronto_contrario",
        ),
        # the same comparison negated and not negated is mixed
        (
            "Nel Comune di Roma il tasso dei furti è più alto di quello italiano, ma "
            "non è più alto della media italiana.",
            "confronto_contrario",
        ),
        # a negation more than 3 words from the trend does not negate it
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti che non vengono denunciati "
            "sono in calo.",
            None,
        ),
    ],
)
def test_markers_and_negations_386(sentence: str, expected: Reason | None) -> None:
    assert _reasons(_check(_ontology(sentence))) == [expected]


def test_negated_and_not_negated_trend_is_not_verified() -> None:
    """As for different trends: the sentence is not verified on that axis."""
    text = _ontology(
        "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo, non in calo."
    )
    sentence = _check(text).frasi[-1]
    assert (sentence.direzione, sentence.direzione_negata, sentence.motivo) == (
        "",
        False,
        None,
    )


_LOW_PROVINCE = make_row(
    place="ITE43",
    name="Provincia di Roma",
    short="Roma",
    kind="provincia",
    rate=1000.0,
    italy=1788.7,
    variation=5,
)
_MUNICIPALITY_AND_LOW_PROVINCE = istat_block_for_zone(
    [
        {"poi_id": "a", "istat": istat_poi(_MUNICIPALITY)},
        {"poi_id": "b", "istat": istat_poi(_LOW_PROVINCE)},
    ],
    estimate_tokens=len,
    token_limit=None,
)


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        # (a) in full: higher in the municipality, lower in the province
        (
            "Secondo l'ISTAT, nel Comune di Roma e nella Provincia di Roma i furti "
            "hanno un tasso più alto di quello italiano.",
            "confronto_contrario",
        ),
        # (b) declared limit: with the short name one place is enough
        (
            "Secondo l'ISTAT, a Roma i furti hanno un tasso più alto di quello "
            "italiano.",
            None,
        ),
    ],
)
def test_comparison_with_several_places(sentence: str, expected: Reason | None) -> None:
    outcome = _check_with(_ontology(sentence), _MUNICIPALITY_AND_LOW_PROVINCE)
    assert _reasons(outcome) == [expected]
