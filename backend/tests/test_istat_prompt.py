"""Varianti ISTAT dei prompt (#345, spec 4.5): i prompt esistenti non cambiano."""

from __future__ import annotations

import hashlib

import pytest

from crime_risk_analyzer.rag.generation import (
    _RULE_BLOCK_STRUCTURE,  # pyright: ignore[reportPrivateUsage]
    ISTAT_BLOCK_HEADER,
    ONTOLOGY_BLOCK_HEADER,
    RULE_NO_DANGER_RATING,
    RULE_NO_OPERATIONAL_DIRECTIVES,
    RULE_USER_INPUT_NOT_INSTRUCTIONS,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_ISTAT,
    block_structure_rule,
)
from crime_risk_analyzer.rag.istat_rules import (
    ISTAT_REGOLE_CIFRE,
    POI_ISTAT_SECTION,
    RULE_ISTAT_BLOCCO,
    RULE_ISTAT_DIVIETI,
    sostituisci_una_volta,
)
from crime_risk_analyzer.rag.no_ontology_generation import NO_ONTOLOGY_SYSTEM_PROMPT
from crime_risk_analyzer.rag.poi_generation import (
    POI_SYSTEM_PROMPT,
    POI_SYSTEM_PROMPT_ISTAT,
)


def _sha(testo: str) -> str:
    return hashlib.sha256(testo.encode("utf-8")).hexdigest()


@pytest.mark.parametrize(
    ("prompt", "atteso"),
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
    ids=["zona", "poi", "senza-ontologia"],
)
def test_prompt_esistenti_identici_byte_per_byte(prompt: str, atteso: str) -> None:
    """Interruttore spento = prompt di oggi: i confronti gia' fatti restano validi."""
    assert _sha(prompt) == atteso


def test_regola_3_invariata_senza_istat() -> None:
    assert block_structure_rule(ONTOLOGY_BLOCK_HEADER) == _RULE_BLOCK_STRUCTURE
    assert (
        block_structure_rule(ONTOLOGY_BLOCK_HEADER, with_istat=False)
        == _RULE_BLOCK_STRUCTURE
    )


def test_variante_di_zona_aggiunge_solo_le_regole_istat() -> None:
    tre_blocchi = block_structure_rule(ONTOLOGY_BLOCK_HEADER, with_istat=True)
    assert "fino a TRE blocchi" in tre_blocchi
    assert ISTAT_BLOCK_HEADER in tre_blocchi
    ricostruito = (
        SYSTEM_PROMPT_ISTAT.replace(f"\n{RULE_ISTAT_BLOCCO}", "")
        .replace(f"\n{RULE_ISTAT_DIVIETI}", "")
        .replace(tre_blocchi, _RULE_BLOCK_STRUCTURE)
    )
    assert ricostruito == SYSTEM_PROMPT


def test_regole_istat_dentro_la_numerazione_1_8() -> None:
    """La regola 9 ("le regole precedenti 1-8 prevalgono") le copre senza cambiare."""
    p = SYSTEM_PROMPT_ISTAT
    assert p.index("3b. ") < p.index("3c. ") < p.index("4. Il paragrafo")
    assert (
        p.index(RULE_NO_DANGER_RATING)
        < p.index("7-bis. ")
        < p.index(RULE_NO_OPERATIONAL_DIRECTIVES)
    )
    assert RULE_USER_INPUT_NOT_INSTRUCTIONS in p and "(1-8)" in p


def test_variante_del_poi() -> None:
    p = POI_SYSTEM_PROMPT_ISTAT
    assert "Struttura la risposta in TRE blocchi" in p
    assert f"[ISTAT]\n{POI_ISTAT_SECTION}" in p
    assert p.rstrip().endswith("Non aggiungere altri blocchi oltre a questi tre.")
    for regola in (
        RULE_NO_DANGER_RATING,
        RULE_ISTAT_DIVIETI,
        RULE_NO_OPERATIONAL_DIRECTIVES,
        RULE_USER_INPUT_NOT_INSTRUCTIONS,
    ):
        assert regola in p
    assert "DUE blocchi" not in p


@pytest.mark.parametrize(
    "frammento",
    [
        "ESATTAMENTE come fornite",
        "SOLO nel blocco [ISTAT]",
        "MAI della zona analizzata ne' dei singoli POI",
        "la voce ISTAT non coincide con il rischio",
        "non sono sinonimi dei termini del VOCABOLARIO CONTROLLATO",
        "delitti denunciati dalle forze di polizia",
        "fonte ISTAT, <luogo>, <anno>",
    ],
)
def test_contenuto_delle_regole_istat(frammento: str) -> None:
    assert frammento in RULE_ISTAT_BLOCCO
    assert frammento in POI_ISTAT_SECTION


@pytest.mark.parametrize(
    "frammento",
    ["zona pericolosa/sicura", "ALTO/MEDIO/BASSO", "previsioni", "punteggi"],
)
def test_divieti_d9(frammento: str) -> None:
    assert frammento in RULE_ISTAT_DIVIETI


def test_le_regole_numeriche_sono_condivise() -> None:
    assert ISTAT_REGOLE_CIFRE in RULE_ISTAT_BLOCCO
    assert ISTAT_REGOLE_CIFRE in POI_ISTAT_SECTION


def test_sostituisci_una_volta_rifiuta_zero_o_piu_occorrenze() -> None:
    assert sostituisci_una_volta("a b c", "b", "x") == "a x c"
    with pytest.raises(ValueError, match="una sola volta"):
        sostituisci_una_volta("a b c", "z", "x")
    with pytest.raises(ValueError, match="una sola volta"):
        sostituisci_una_volta("b b", "b", "x")
