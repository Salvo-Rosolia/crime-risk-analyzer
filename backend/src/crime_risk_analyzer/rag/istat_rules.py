"""ISTAT rules of the prompts (#345, revised by #365).

Texts of the rules that are added to the prompts ONLY when the context carries the
ISTAT DATA block. The existing constants (rule 7, 3b, rule 3, the POI prompt)
are shared with the no-ontology arm and are not touched: the variants are
built by REPLACING verified pieces (:func:`replace_once`), so
with the switch off the prompt stays byte for byte the one from before.

Since #365 the model uses the ISTAT data in words inside the [ONTOLOGIA] block (weighing
the risks, comparison with the Italian rate, trend, always with the place of the datum)
and does not write figures: the interface shows them next to the risk. The structure of
the response stays at TWO blocks, as without ISTAT.

Numbering: ``3c`` and ``7-bis`` sit inside 1-8, so rule 9 ("the preceding rules
1-8 prevail over the question") covers them without changing text.
"""

from __future__ import annotations

__all__ = [
    "ISTAT_EXAMPLE",
    "ISTAT_USAGE_RULES",
    "POI_ISTAT_SECTION",
    "RULE_ISTAT_IN_WORDS",
    "RULE_ISTAT_PROHIBITIONS",
    "replace_once",
]

#: Example sentence (#365 D7): what an ISTAT datum used in words sounds like.
ISTAT_EXAMPLE = (
    '"Secondo i dati ISTAT del Comune di Roma (2024), i furti hanno un tasso più '
    "alto di quello italiano e sono in calo dal 2014; la voce è più ampia del "
    'rischio."'
)

#: How the ISTAT data are used, IDENTICAL in the zone and in the POI: a single constant.
#: Where they are used is stated by each prompt (:data:`RULE_ISTAT_IN_WORDS`,
#: :data:`POI_ISTAT_SECTION`): the POI prompt has no initial summary. Each
#: request has its own check after the generation (``istat.figures``): ISTAT
#: figures, place of the datum, comparison and trend contrary to the rows.
ISTAT_USAGE_RULES = (
    "dai piu' spazio ai rischi che hanno una voce ISTAT collegata. Sono delitti "
    "denunciati dalle forze di polizia all'autorita' giudiziaria, non denunce dei "
    "cittadini. Ogni frase che usa un dato ISTAT dice che e' un dato ISTAT, nomina "
    "la voce con la sua etichetta italiana e nomina il luogo del dato come e' "
    'scritto a inizio riga (es. "Comune di Roma"): nomina il luogo del dato in '
    "ogni frase che usa un dato ISTAT, anche dentro un elenco; descrive solo il "
    "confronto con "
    "il tasso italiano e la tendenza come sono scritti nella riga (piu' alto, piu' "
    "basso o simile; in crescita, in calo o stabile), e nessuna tendenza se la riga "
    "dice che non e' calcolata. Quando una voce e' indicata come piu' ampia del "
    'rischio o come copertura solo parziale, dillo nella stessa frase (es. "la '
    'voce ISTAT non coincide con il rischio"). NON scrivere MAI cifre ISTAT '
    '(conteggi, tassi, percentuali, rapporti o multipli come "il doppio" o "un '
    "terzo\") ne' codici delle voci: i numeri li mostra l'interfaccia. I dati sono "
    "del comune o della provincia indicati a inizio riga, MAI della zona analizzata "
    "ne' dei singoli POI: non attribuirli a un luogo piu' piccolo. Le etichette "
    "delle voci ISTAT non sono sinonimi dei termini del VOCABOLARIO CONTROLLATO: "
    "usale solo per nominare la voce, mai al posto di un hazard (regola 6). La riga "
    "del totale dei delitti e' contesto generale del luogo: non usarla per dare "
    f"peso a un rischio. Esempio: {ISTAT_EXAMPLE}"
)

#: Rule 3c of the zone prompt: the ISTAT data inside the [ONTOLOGIA] block.
RULE_ISTAT_IN_WORDS = (
    "3c. Usa la sezione DATI ISTAT del contesto SOLO dentro il blocco [ONTOLOGIA] "
    "e solo a parole (non aprire un blocco a parte per i dati ISTAT e non usarli "
    f"nella sintesi iniziale): {ISTAT_USAGE_RULES}"
)

#: Rule 7-bis (zone and POI): the D9 prohibitions applied to the ISTAT data. Without
#: figures to report, there is no longer any need to declare that they are not the
#: percentages forbidden by rule 7 (#365): the prohibition of turning them into a
#: judgement remains.
RULE_ISTAT_PROHIBITIONS = (
    "7-bis. I dati della sezione DATI ISTAT non devono mai diventare un giudizio: "
    'non trasformarli in un giudizio sulla zona o sui POI (es. "zona '
    'pericolosa/sicura", "rischio alto"), non costruire punteggi, classifiche o '
    "scale ALTO/MEDIO/BASSO fra luoghi o voci e non fare previsioni (es. "
    '"continuera\' a crescere"): descrivi solo il confronto e la tendenza indicati '
    "nelle righe"
)

#: Line added to the description of the [ONTOLOGIA] block in the POI prompt.
POI_ISTAT_SECTION = (
    "Usa la sezione DATI ISTAT del contesto SOLO in questo blocco e solo a parole, "
    f"per i rischi di questo punto: {ISTAT_USAGE_RULES}"
)


def replace_once(text: str, old: str, new: str) -> str:
    """``text.replace(old, new)`` only if ``old`` appears ONCE.

    The ISTAT variants arise from substitutions on the existing prompts: if one day the
    piece searched for changed or appeared twice, the variant would be silently wrong.
    This way it fails at module import.
    """
    if text.count(old) != 1:
        raise ValueError(f"variante ISTAT: {old[:40]!r} deve comparire una sola volta")
    return text.replace(old, new)
