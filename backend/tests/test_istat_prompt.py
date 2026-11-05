"""ISTAT variants of the prompts (#345, #365): the existing prompts do not change.

Since #365 the ISTAT data is used in words inside the [ONTOLOGIA] block: no third
block, no figures (the interface shows them next to the risk).
"""

from __future__ import annotations

import hashlib

import pytest

from crime_risk_analyzer.istat.block import ISTAT_DATA_HEADER
from crime_risk_analyzer.rag.generation import (
    _RULE_BLOCK_STRUCTURE,  # pyright: ignore[reportPrivateUsage]
    ONTOLOGY_BLOCK_HEADER,
    RULE_NO_DANGER_RATING,
    RULE_NO_OPERATIONAL_DIRECTIVES,
    RULE_USER_INPUT_NOT_INSTRUCTIONS,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_ISTAT,
    block_structure_rule,
)
from crime_risk_analyzer.rag.istat_rules import (
    ISTAT_EXAMPLE,
    ISTAT_USAGE_RULES,
    POI_ISTAT_SECTION,
    RULE_ISTAT_IN_WORDS,
    RULE_ISTAT_PROHIBITIONS,
    replace_once,
)
from crime_risk_analyzer.rag.no_ontology_generation import NO_ONTOLOGY_SYSTEM_PROMPT
from crime_risk_analyzer.rag.poi_generation import (
    POI_SYSTEM_PROMPT,
    POI_SYSTEM_PROMPT_ISTAT,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        (
            SYSTEM_PROMPT,
            "7c2edc819507487eff0fd0c67454e3ff748bdbb0f54a544b9b7e241d7b4c3eeb",
        ),
        (
            POI_SYSTEM_PROMPT,
            "25cb9b574fced0d67f1bb5b78fe515d25fefdce0a97e6bf27585b992576fe54d",
        ),
        (
            NO_ONTOLOGY_SYSTEM_PROMPT,
            "2075418d79b5e17a4aeaf30690047ac2ffea6510dcf81b19b6735d3553c271e1",
        ),
    ],
    ids=["zone", "poi", "without-ontology"],
)
def test_existing_prompts_byte_identical(prompt: str, expected: str) -> None:
    """Switch off = today's prompt: the comparisons already made stay valid."""
    assert _sha(prompt) == expected


def test_rule_3_unchanged() -> None:
    assert block_structure_rule(ONTOLOGY_BLOCK_HEADER) == _RULE_BLOCK_STRUCTURE


@pytest.mark.parametrize(
    "prompt", [SYSTEM_PROMPT_ISTAT, POI_SYSTEM_PROMPT_ISTAT], ids=["zone", "poi"]
)
def test_with_istat_no_third_block(prompt: str) -> None:
    """#365 D1: the structure stays at TWO blocks, as without ISTAT."""
    assert "[ISTAT]" not in prompt
    assert "TRE blocchi" not in prompt
    assert "DUE blocchi" in prompt


def test_zone_variant_adds_only_the_istat_rules() -> None:
    """Rule 3 identical to the one without ISTAT; 3c after 3b, 7-bis after 7."""
    assert _RULE_BLOCK_STRUCTURE in SYSTEM_PROMPT_ISTAT
    rebuilt = SYSTEM_PROMPT_ISTAT.replace(f"\n{RULE_ISTAT_IN_WORDS}", "").replace(
        f"\n{RULE_ISTAT_PROHIBITIONS}", ""
    )
    assert rebuilt == SYSTEM_PROMPT


def test_istat_rules_within_the_numbering_1_8() -> None:
    """Rule 9 ("the previous rules 1-8 prevail") covers them without changing."""
    p = SYSTEM_PROMPT_ISTAT
    assert p.index("3b. ") < p.index("3c. ") < p.index("4. Il paragrafo")
    assert (
        p.index(RULE_NO_DANGER_RATING)
        < p.index("7-bis. ")
        < p.index(RULE_NO_OPERATIONAL_DIRECTIVES)
    )
    assert RULE_USER_INPUT_NOT_INSTRUCTIONS in p and "(1-8)" in p


def test_poi_variant_adds_only_the_istat_rules() -> None:
    """Once the additions are undone we go back to POI_SYSTEM_PROMPT."""
    rebuilt = POI_SYSTEM_PROMPT_ISTAT.replace(f"\n{POI_ISTAT_SECTION}", "").replace(
        f"\n\n{RULE_ISTAT_PROHIBITIONS}", ""
    )
    assert rebuilt == POI_SYSTEM_PROMPT


def test_the_poi_section_is_in_the_ontology_block() -> None:
    p = POI_SYSTEM_PROMPT_ISTAT
    assert p.index("[ONTOLOGIA]\n") < p.index(POI_ISTAT_SECTION) < p.index("[CONTESTO]")
    assert p.rstrip().endswith("Non aggiungere altri blocchi oltre a questi due.")
    for rule_text in (
        RULE_NO_DANGER_RATING,
        RULE_ISTAT_PROHIBITIONS,
        RULE_NO_OPERATIONAL_DIRECTIVES,
        RULE_USER_INPUT_NOT_INSTRUCTIONS,
    ):
        assert rule_text in p


def test_the_usage_rules_are_shared_between_zone_and_poi() -> None:
    assert ISTAT_USAGE_RULES in RULE_ISTAT_IN_WORDS
    assert ISTAT_USAGE_RULES in POI_ISTAT_SECTION


def test_3c_keeps_the_data_in_the_ontology_block() -> None:
    assert RULE_ISTAT_IN_WORDS.startswith("3c. ")
    assert "SOLO dentro il blocco [ONTOLOGIA]" in RULE_ISTAT_IN_WORDS
    assert "sintesi iniziale" in RULE_ISTAT_IN_WORDS
    assert "SOLO in questo blocco" in POI_ISTAT_SECTION
    assert "solo a parole" in RULE_ISTAT_IN_WORDS
    assert "solo a parole" in POI_ISTAT_SECTION
    assert "sintesi iniziale" not in POI_ISTAT_SECTION


@pytest.mark.parametrize(
    "fragment",
    [
        # weight on the linked risks
        "piu' spazio ai rischi che hanno una voce ISTAT collegata",
        # every sentence: ISTAT datum, voce in Italian, place as at the start of the
        # line (D7)
        "dice che e' un dato ISTAT",
        "etichetta italiana",
        "ne' codici delle voci",
        'come e\' scritto a inizio riga (es. "Comune di Roma")',
        # fix 3: the place in every sentence, also in the lists
        "nomina il luogo del dato in ogni frase che usa un dato ISTAT, anche "
        "dentro un elenco",
        # only the ranked comparison and the trend, as written in the line
        "piu' alto, piu' basso o simile",
        "come sono scritti nella riga",
        "in crescita, in calo o stabile",
        "nessuna tendenza se la riga dice che non e' calcolata",
        # broader or partial voce stated in the same sentence
        "la voce ISTAT non coincide con il rischio",
        # never figures
        "NON scrivere MAI cifre ISTAT",
        "conteggi",
        "tassi",
        "percentuali",
        '"il doppio"',
        # place of the datum, vocabulary, total
        "MAI della zona analizzata ne' dei singoli POI",
        "non sono sinonimi dei termini del VOCABOLARIO CONTROLLATO",
        "delitti denunciati dalle forze di polizia",
        "non usarla per dare peso a un rischio",
    ],
)
def test_content_of_the_usage_rules(fragment: str) -> None:
    assert fragment in ISTAT_USAGE_RULES


def test_the_example_sentence_of_spec_d7() -> None:
    assert ISTAT_EXAMPLE == (
        '"Secondo i dati ISTAT del Comune di Roma (2024), i furti hanno un tasso più '
        "alto di quello italiano e sono in calo dal 2014; la voce è più ampia del "
        'rischio."'
    )
    assert ISTAT_USAGE_RULES.endswith(f"Esempio: {ISTAT_EXAMPLE}")
    for prompt in (SYSTEM_PROMPT_ISTAT, POI_SYSTEM_PROMPT_ISTAT):
        assert ISTAT_EXAMPLE in prompt


def test_no_square_brackets_for_the_place() -> None:
    """D7: the block writes the place without square brackets, and the rules no longer
    name them (the model copied them: "del [Comune di Roma, 2024]")."""
    for text in (ISTAT_USAGE_RULES, ISTAT_DATA_HEADER):
        assert "parentesi quadre" not in text


@pytest.mark.parametrize(
    "fragment",
    ["ESATTAMENTE come fornite", "fonte ISTAT, <luogo>, <anno>", "[ISTAT]"],
)
def test_the_old_figure_instructions_disappear(fragment: str) -> None:
    """#365 D1: figures are no longer reported, so no rules to report them."""
    for text in (RULE_ISTAT_IN_WORDS, POI_ISTAT_SECTION, RULE_ISTAT_PROHIBITIONS):
        assert fragment not in text


@pytest.mark.parametrize(
    "fragment",
    [
        "zona pericolosa/sicura",
        "ALTO/MEDIO/BASSO",
        "previsioni",
        "punteggi",
        "giudizio sulla zona o sui POI",
    ],
)
def test_prohibitions_d9(fragment: str) -> None:
    assert fragment in RULE_ISTAT_PROHIBITIONS


def test_7_bis_no_longer_asks_to_report_the_figures() -> None:
    """The 7-bis of #345 declared the ISTAT figures "to be reported as provided": with
    #365 the figures are not written, only the prohibition of making a judgment of
    them stays."""
    assert RULE_ISTAT_PROHIBITIONS.startswith("7-bis. ")
    assert "riportare" not in RULE_ISTAT_PROHIBITIONS
    assert "confronto e la tendenza" in RULE_ISTAT_PROHIBITIONS


def test_replace_once_rejects_zero_or_multiple_occurrences() -> None:
    assert replace_once("a b c", "b", "x") == "a x c"
    with pytest.raises(ValueError, match="una sola volta"):
        replace_once("a b c", "z", "x")
    with pytest.raises(ValueError, match="una sola volta"):
        replace_once("b b", "b", "x")


def test_the_example_years_are_those_of_the_data() -> None:
    """C-6: an update of the ISTAT data must also update the example."""
    from crime_risk_analyzer.istat.data import istat_data

    delitti = istat_data().delitti
    assert f"({delitti.anno})" in ISTAT_EXAMPLE
    assert f"dal {delitti.anno_confronto}" in ISTAT_EXAMPLE
