"""Varianti ISTAT dei prompt (#345, #365): i prompt esistenti non cambiano.

Da #365 i dati ISTAT si usano a parole dentro il blocco [ONTOLOGIA]: niente terzo
blocco, niente cifre (le mostra l'interfaccia accanto al rischio).
"""

from __future__ import annotations

import hashlib

import pytest

from crime_risk_analyzer.istat.blocco import INTESTAZIONE_DATI_ISTAT
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
    ESEMPIO_ISTAT,
    ISTAT_REGOLE_USO,
    POI_ISTAT_SECTION,
    RULE_ISTAT_A_PAROLE,
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


def test_regola_3_invariata() -> None:
    assert block_structure_rule(ONTOLOGY_BLOCK_HEADER) == _RULE_BLOCK_STRUCTURE


@pytest.mark.parametrize(
    "prompt", [SYSTEM_PROMPT_ISTAT, POI_SYSTEM_PROMPT_ISTAT], ids=["zona", "poi"]
)
def test_con_istat_niente_terzo_blocco(prompt: str) -> None:
    """#365 D1: la struttura resta a DUE blocchi, come senza ISTAT."""
    assert "[ISTAT]" not in prompt
    assert "TRE blocchi" not in prompt
    assert "DUE blocchi" in prompt


def test_variante_di_zona_aggiunge_solo_le_regole_istat() -> None:
    """Regola 3 identica a quella senza ISTAT; 3c dopo la 3b, 7-bis dopo la 7."""
    assert _RULE_BLOCK_STRUCTURE in SYSTEM_PROMPT_ISTAT
    ricostruito = SYSTEM_PROMPT_ISTAT.replace(f"\n{RULE_ISTAT_A_PAROLE}", "").replace(
        f"\n{RULE_ISTAT_DIVIETI}", ""
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


def test_variante_del_poi_aggiunge_solo_le_regole_istat() -> None:
    """Disfatte le aggiunte si torna a POI_SYSTEM_PROMPT."""
    ricostruito = POI_SYSTEM_PROMPT_ISTAT.replace(f"\n{POI_ISTAT_SECTION}", "").replace(
        f"\n\n{RULE_ISTAT_DIVIETI}", ""
    )
    assert ricostruito == POI_SYSTEM_PROMPT


def test_la_sezione_del_poi_sta_nel_blocco_ontologia() -> None:
    p = POI_SYSTEM_PROMPT_ISTAT
    assert p.index("[ONTOLOGIA]\n") < p.index(POI_ISTAT_SECTION) < p.index("[CONTESTO]")
    assert p.rstrip().endswith("Non aggiungere altri blocchi oltre a questi due.")
    for regola in (
        RULE_NO_DANGER_RATING,
        RULE_ISTAT_DIVIETI,
        RULE_NO_OPERATIONAL_DIRECTIVES,
        RULE_USER_INPUT_NOT_INSTRUCTIONS,
    ):
        assert regola in p


def test_le_regole_d_uso_sono_condivise_fra_zona_e_poi() -> None:
    assert ISTAT_REGOLE_USO in RULE_ISTAT_A_PAROLE
    assert ISTAT_REGOLE_USO in POI_ISTAT_SECTION


def test_la_3c_tiene_i_dati_nel_blocco_ontologia() -> None:
    assert RULE_ISTAT_A_PAROLE.startswith("3c. ")
    assert "SOLO dentro il blocco [ONTOLOGIA]" in RULE_ISTAT_A_PAROLE
    assert "sintesi iniziale" in RULE_ISTAT_A_PAROLE
    assert "SOLO in questo blocco" in POI_ISTAT_SECTION
    assert "solo a parole" in RULE_ISTAT_A_PAROLE
    assert "solo a parole" in POI_ISTAT_SECTION
    assert "sintesi iniziale" not in POI_ISTAT_SECTION


@pytest.mark.parametrize(
    "frammento",
    [
        # peso sui rischi collegati
        "piu' spazio ai rischi che hanno una voce ISTAT collegata",
        # ogni frase: dato ISTAT, voce in italiano, luogo come a inizio riga (D7)
        "dice che e' un dato ISTAT",
        "etichetta italiana",
        "ne' codici delle voci",
        'come e\' scritto a inizio riga (es. "Comune di Roma")',
        # fix 3: il luogo in ogni frase, anche negli elenchi
        "nomina il luogo del dato in ogni frase che usa un dato ISTAT, anche "
        "dentro un elenco",
        # solo il confronto classificato e la tendenza, come scritti nella riga
        "piu' alto, piu' basso o simile",
        "come sono scritti nella riga",
        "in crescita, in calo o stabile",
        "nessuna tendenza se la riga dice che non e' calcolata",
        # voce piu' ampia o parziale detta nella stessa frase
        "la voce ISTAT non coincide con il rischio",
        # mai cifre
        "NON scrivere MAI cifre ISTAT",
        "conteggi",
        "tassi",
        "percentuali",
        '"il doppio"',
        # luogo del dato, vocabolario, totale
        "MAI della zona analizzata ne' dei singoli POI",
        "non sono sinonimi dei termini del VOCABOLARIO CONTROLLATO",
        "delitti denunciati dalle forze di polizia",
        "non usarla per dare peso a un rischio",
    ],
)
def test_contenuto_delle_regole_d_uso(frammento: str) -> None:
    assert frammento in ISTAT_REGOLE_USO


def test_la_frase_d_esempio_della_spec_d7() -> None:
    assert ESEMPIO_ISTAT == (
        '"Secondo i dati ISTAT del Comune di Roma (2024), i furti hanno un tasso più '
        "alto di quello italiano e sono in calo dal 2014; la voce è più ampia del "
        'rischio."'
    )
    assert ISTAT_REGOLE_USO.endswith(f"Esempio: {ESEMPIO_ISTAT}")
    for prompt in (SYSTEM_PROMPT_ISTAT, POI_SYSTEM_PROMPT_ISTAT):
        assert ESEMPIO_ISTAT in prompt


def test_niente_parentesi_quadre_per_il_luogo() -> None:
    """D7: il blocco scrive il luogo senza parentesi quadre, e le regole non le
    nominano piu' (il modello le copiava: "del [Comune di Roma, 2024]")."""
    for testo in (ISTAT_REGOLE_USO, INTESTAZIONE_DATI_ISTAT):
        assert "parentesi quadre" not in testo


@pytest.mark.parametrize(
    "frammento",
    ["ESATTAMENTE come fornite", "fonte ISTAT, <luogo>, <anno>", "[ISTAT]"],
)
def test_le_vecchie_istruzioni_sulle_cifre_spariscono(frammento: str) -> None:
    """#365 D1: non si riportano piu' cifre, quindi niente regole per riportarle."""
    for testo in (RULE_ISTAT_A_PAROLE, POI_ISTAT_SECTION, RULE_ISTAT_DIVIETI):
        assert frammento not in testo


@pytest.mark.parametrize(
    "frammento",
    [
        "zona pericolosa/sicura",
        "ALTO/MEDIO/BASSO",
        "previsioni",
        "punteggi",
        "giudizio sulla zona o sui POI",
    ],
)
def test_divieti_d9(frammento: str) -> None:
    assert frammento in RULE_ISTAT_DIVIETI


def test_7_bis_non_chiede_piu_di_riportare_le_cifre() -> None:
    """La 7-bis di #345 dichiarava le cifre ISTAT "da riportare come fornite": con
    #365 le cifre non si scrivono, resta solo il divieto di farne un giudizio."""
    assert RULE_ISTAT_DIVIETI.startswith("7-bis. ")
    assert "riportare" not in RULE_ISTAT_DIVIETI
    assert "confronto e la tendenza" in RULE_ISTAT_DIVIETI


def test_sostituisci_una_volta_rifiuta_zero_o_piu_occorrenze() -> None:
    assert sostituisci_una_volta("a b c", "b", "x") == "a x c"
    with pytest.raises(ValueError, match="una sola volta"):
        sostituisci_una_volta("a b c", "z", "x")
    with pytest.raises(ValueError, match="una sola volta"):
        sostituisci_una_volta("b b", "b", "x")


def test_gli_anni_dell_esempio_sono_quelli_dei_dati() -> None:
    """C-6: un aggiornamento dei dati ISTAT deve far aggiornare anche l'esempio."""
    from crime_risk_analyzer.istat.dati import dati_istat

    delitti = dati_istat().delitti
    assert f"({delitti.anno})" in ESEMPIO_ISTAT
    assert f"dal {delitti.anno_confronto}" in ESEMPIO_ISTAT
