"""Selection of the ISTAT data by the model, sentences composed by the app (#366)."""

from __future__ import annotations

from typing import Literal

import pytest

from crime_risk_analyzer.istat.rows import format_row, variation_direction
from crime_risk_analyzer.istat.selection import (
    SELECTION_HEADER,
    IstatSelection,
    RawSelection,
    SelectionDiscards,
    compose_sentence,
    compose_sentences,
    extract_selection,
    insert_sentences,
    resolve_selection,
)
from crime_risk_analyzer.rag.generation import source_block_spans
from tests.istat._factories import make_frame, make_link, make_row

Weight = Literal["alto", "medio", "basso"]

_THEFTS = make_row(
    "THEFT",
    label="furti",
    links=(make_link("Property_theft", "Furto di beni", "piu_larga"),),
)
_ROBBERIES = make_row(
    "ROBBER",
    label="rapine",
    rate=10.0,
    italy=10.0,
    variation=20,
    links=(make_link("Robbery", "Rapina", "esatta"),),
)


def _sentence(selection: IstatSelection) -> str:
    sentence = compose_sentence(selection)
    assert sentence is not None
    return sentence


def _text(*lines: str) -> str:
    return "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nProsa.\n\n" + "\n".join(
        [SELECTION_HEADER, *lines]
    )


def _rows_read(raw: list[RawSelection]) -> list[tuple[str, str, str]]:
    return [(g.rischio, g.voce, g.peso) for g in raw]


def test_extract_removes_the_block_and_reads_the_lines() -> None:
    text, raw, malformed = extract_selection(
        _text("- Furto di beni | furti | alto", "Rapina | rapine | basso")
    )
    assert text == "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nProsa."
    assert _rows_read(raw) == [
        ("Furto di beni", "furti", "alto"),
        ("Rapina", "rapine", "basso"),
    ]
    assert malformed == 0


def test_extract_without_block_does_not_touch_the_text() -> None:
    assert extract_selection("Sintesi.\n") == ("Sintesi.\n", [], 0)


def test_extract_decorated_header_and_malformed_lines_counted() -> None:
    text, raw, malformed = extract_selection(
        "Prosa.\n\n**Scelta dati ISTAT:**\nRapina | rapine\n"
        "Rapina | rapine | enorme\nRapina | rapine | Medio\n"
    )
    assert text == "Prosa."
    assert _rows_read(raw) == [
        ("Rapina", "rapine", "enorme"),
        ("Rapina", "rapine", "Medio"),
    ]
    assert malformed == 1


def test_extract_accepts_the_first_line_after_the_colon() -> None:
    text, raw, _ = extract_selection(
        "Prosa.\n\nSCELTA DATI ISTAT: Rapina | rapine | alto\n- Furto | furti | basso\n"
    )
    assert text == "Prosa."
    assert _rows_read(raw) == [
        ("Rapina", "rapine", "alto"),
        ("Furto", "furti", "basso"),
    ]


def test_extract_mid_response_keeps_the_following_blocks() -> None:
    text, raw, _ = extract_selection(
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nProsa.\n\n"
        "SCELTA DATI ISTAT:\n- Rapina | rapine | alto\n\n"
        "Rischi dal contesto [CONTESTO]\nZona di transito.\n"
    )
    assert text == (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nProsa.\n\n"
        "Rischi dal contesto [CONTESTO]\nZona di transito.\n"
    )
    assert _rows_read(raw) == [("Rapina", "rapine", "alto")]


def test_resolve_anchors_to_the_rows_and_discards_the_rest() -> None:
    _, raw, _ = extract_selection(
        _text(
            "Furto di beni | furti | alto",
            "Rapina | furti | alto",  # risk not linked to the item
            "Furto di beni | voce inventata | alto",
            "FURTO DI BENI | Furti | medio",  # duplicate (case): only once
        )
    )
    selections, discards = resolve_selection(raw, [make_frame(), _THEFTS, _ROBBERIES])
    assert [(s.riga.voce, s.hazard, s.peso) for s in selections] == [
        ("THEFT", "Property_theft", "alto")
    ]
    assert discards == SelectionDiscards(
        rischio_non_collegato=1, voce_non_nel_blocco=1, doppione=1
    )


def test_resolve_does_not_choose_the_total_frame() -> None:
    _, raw, _ = extract_selection(_text("Furto di beni | totale | alto"))
    selections, discards = resolve_selection(raw, [make_frame(), _THEFTS])
    assert selections == []
    assert discards.voce_non_nel_blocco == 1


def test_resolve_counts_out_of_vocabulary_weight_and_malformed() -> None:
    _, raw, malformed = extract_selection(
        _text("Rapina | rapine | enorme", "Rapina | rapine", "Rapina | rapine | ALTO.")
    )
    selections, discards = resolve_selection(raw, [_ROBBERIES], malformed=malformed)
    assert [s.peso for s in selections] == ["alto"]
    assert discards == SelectionDiscards(peso_non_valido=1, malformate=1)


def test_resolve_normalises_typographic_apostrophe_and_accents() -> None:
    row_apos = make_row(
        "CARTHEFT",
        label="furti d'auto più gravi",
        links=(make_link("Car_theft", "Furto d'auto", "esatta"),),
    )
    _, raw, _ = extract_selection(
        _text("Furto d’auto | Furti d’auto piu gravi | medio")
    )
    selections, discards = resolve_selection(raw, [row_apos])
    assert [s.hazard for s in selections] == ["Car_theft"]
    assert discards == SelectionDiscards()


def test_sentence_composed_by_the_app_without_internal_pieces() -> None:
    selection = IstatSelection(
        riga=_ROBBERIES.model_copy(update={"variazione_pct": 20}),
        hazard="Robbery",
        rischio="Rapina",
        peso="alto",
    )
    sentence = _sentence(selection)
    assert sentence == (
        "Secondo i dati ISTAT del Comune di Roma (2024), la voce «rapine» (rischio: "
        "Rapina) ha un tasso simile a quello italiano e un andamento in crescita "
        "dal 2014."
    )
    for interior in ("corrispondenza esatta", "non calcolata", "più ampia"):
        assert interior not in sentence


def test_sentence_does_not_report_the_match_kind() -> None:
    """The wider or narrower item of the risk is not a piece to show."""
    wide = IstatSelection(
        riga=_THEFTS, hazard="Property_theft", rischio="Furto di beni", peso="alto"
    )
    assert _sentence(wide).endswith("in calo dal 2014.")
    narrow_row = _THEFTS.model_copy(
        update={
            "collegamenti": (
                make_link("Property_theft", "Furto di beni", "piu_stretta"),
            )
        }
    )
    narrow = IstatSelection(
        riga=narrow_row, hazard="Property_theft", rischio="Furto di beni", peso="alto"
    )
    assert _sentence(narrow) == _sentence(wide)
    for sentence in (_sentence(wide), _sentence(narrow)):
        assert "comprende" not in sentence and "copre solo" not in sentence


@pytest.mark.parametrize(
    ("variation", "direction_word"),
    [(20, "in crescita"), (-5, "in calo"), (0, "stabile")],
)
def test_the_sentence_direction_is_that_of_the_context_row(
    variation: float, direction_word: str
) -> None:
    """Direction: a single classification, shared with the indicator row."""
    r = _ROBBERIES.model_copy(update={"variazione_pct": variation})
    assert variation_direction(r) == direction_word
    selection = IstatSelection(riga=r, hazard="Robbery", rischio="Rapina", peso="alto")
    assert f"un andamento {direction_word} dal {r.anno_confronto}" in _sentence(
        selection
    )
    assert f"{direction_word} dal {r.anno_confronto}" in format_row(r)


def test_sentence_omits_uncomputed_trend() -> None:
    without = _THEFTS.model_copy(
        update={"variazione_pct": None, "motivo_senza_variazione": "x"}
    )
    sentence = _sentence(
        IstatSelection(
            riga=without, hazard="Property_theft", rischio="Furto di beni", peso="alto"
        )
    )
    assert "andamento" not in sentence
    assert "crescita" not in sentence and "calo" not in sentence
    assert "tasso più alto di quello italiano" in sentence


def test_without_comparison_or_trend_no_sentence() -> None:
    empty = _THEFTS.model_copy(
        update={"variazione_pct": None, "tasso": None, "tasso_italia": None}
    )
    selection = IstatSelection(
        riga=empty, hazard="Property_theft", rischio="Furto di beni", peso="alto"
    )
    assert compose_sentence(selection) is None
    assert compose_sentences([selection]) == []


def test_sentence_order_depends_neither_on_the_weight_nor_on_the_model_order() -> None:
    """D9: an order decided by the model would read like a ranking."""
    orders: set[tuple[str, ...]] = set()
    combinations: list[tuple[Weight, Weight]] = [
        ("basso", "alto"),
        ("alto", "basso"),
        ("medio", "medio"),
    ]
    for weights in combinations:
        thefts = IstatSelection(
            riga=_THEFTS, hazard="h", rischio="Furto di beni", peso=weights[0]
        )
        robberies = IstatSelection(
            riga=_ROBBERIES, hazard="r", rischio="Rapina", peso=weights[1]
        )
        for selections in ([thefts, robberies], [robberies, thefts]):
            orders.add(tuple(compose_sentences(selections)))
    assert len(orders) == 1
    sentences = next(iter(orders))
    assert "rapine" in sentences[0]
    assert "furti" in sentences[1]


def test_insert_at_the_bottom_of_the_ontology_block() -> None:
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nProsa.\n\n"
        "Rischi dal contesto [CONTESTO]\nZona.\n"
    )
    out = insert_sentences(text, source_block_spans(text), ["Frase A.", "Frase B."])
    assert out == (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nProsa.\nFrase A. Frase B.\n\n"
        "Rischi dal contesto [CONTESTO]\nZona.\n"
    )


def test_insert_without_ontology_block_opens_one() -> None:
    out = insert_sentences("Sintesi.", [], ["Frase A."])
    assert out == "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nFrase A."


def test_insert_without_sentences_does_not_change() -> None:
    assert insert_sentences("Sintesi.", [], []) == "Sintesi."
