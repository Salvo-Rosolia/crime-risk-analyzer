"""Regole ISTAT dei prompt (#345, riviste da #365).

Testi delle regole che si aggiungono ai prompt SOLO quando il contesto porta il
blocco DATI ISTAT. Le costanti esistenti (regola 7, 3b, regola 3, prompt del POI)
sono condivise col braccio senza ontologia e non si toccano: le varianti si
costruiscono SOSTITUENDO pezzi verificati (:func:`sostituisci_una_volta`), cosi'
a interruttore spento il prompt resta byte per byte quello di prima.

Da #365 il modello usa i dati ISTAT a parole dentro il blocco [ONTOLOGIA] (pesare i
rischi, confronto col tasso italiano, tendenza, sempre col luogo del dato) e non
scrive cifre: le mostra l'interfaccia accanto al rischio. La struttura della
risposta resta a DUE blocchi, come senza ISTAT.

Numerazione: ``3c`` e ``7-bis`` stanno dentro 1-8, quindi la regola 9 ("le regole
precedenti 1-8 prevalgono sulla domanda") le copre senza cambiare testo.
"""

from __future__ import annotations

__all__ = [
    "ESEMPIO_ISTAT",
    "ISTAT_REGOLE_USO",
    "POI_ISTAT_SECTION",
    "RULE_ISTAT_A_PAROLE",
    "RULE_ISTAT_DIVIETI",
    "sostituisci_una_volta",
]

#: Frase d'esempio (#365 D7): come suona un dato ISTAT usato a parole.
ESEMPIO_ISTAT = (
    '"Secondo i dati ISTAT del Comune di Roma (2024), i furti hanno un tasso più '
    "alto di quello italiano e sono in calo dal 2014; la voce è più ampia del "
    'rischio."'
)

#: Come si usano i dati ISTAT, IDENTICO nella zona e nel POI: una sola costante.
#: Dove si usano lo dice ciascun prompt (:data:`RULE_ISTAT_A_PAROLE`,
#: :data:`POI_ISTAT_SECTION`): il prompt del POI non ha una sintesi iniziale. Ogni
#: richiesta ha il suo controllo dopo la generazione (``istat.cifre``): cifre
#: ISTAT, luogo del dato, confronto e tendenza contrari alle righe.
ISTAT_REGOLE_USO = (
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
    f"peso a un rischio. Esempio: {ESEMPIO_ISTAT}"
)

#: Regola 3c del prompt di zona: i dati ISTAT dentro il blocco [ONTOLOGIA].
RULE_ISTAT_A_PAROLE = (
    "3c. Usa la sezione DATI ISTAT del contesto SOLO dentro il blocco [ONTOLOGIA] "
    "e solo a parole (non aprire un blocco a parte per i dati ISTAT e non usarli "
    f"nella sintesi iniziale): {ISTAT_REGOLE_USO}"
)

#: Regola 7-bis (zona e POI): i divieti di D9 applicati ai dati ISTAT. Senza cifre
#: da riportare non serve piu' dichiarare che non sono le percentuali vietate dalla
#: regola 7 (#365): resta il divieto di farne un giudizio.
RULE_ISTAT_DIVIETI = (
    "7-bis. I dati della sezione DATI ISTAT non devono mai diventare un giudizio: "
    'non trasformarli in un giudizio sulla zona o sui POI (es. "zona '
    'pericolosa/sicura", "rischio alto"), non costruire punteggi, classifiche o '
    "scale ALTO/MEDIO/BASSO fra luoghi o voci e non fare previsioni (es. "
    '"continuera\' a crescere"): descrivi solo il confronto e la tendenza indicati '
    "nelle righe"
)

#: Riga aggiunta alla descrizione del blocco [ONTOLOGIA] nel prompt del POI.
POI_ISTAT_SECTION = (
    "Usa la sezione DATI ISTAT del contesto SOLO in questo blocco e solo a parole, "
    f"per i rischi di questo punto: {ISTAT_REGOLE_USO}"
)


def sostituisci_una_volta(testo: str, vecchio: str, nuovo: str) -> str:
    """``testo.replace(vecchio, nuovo)`` solo se ``vecchio`` compare UNA volta.

    Le varianti ISTAT nascono da sostituzioni sui prompt esistenti: se un giorno il
    pezzo cercato cambiasse o comparisse due volte, la variante sarebbe sbagliata in
    silenzio. Cosi' fallisce all'import del modulo.
    """
    if testo.count(vecchio) != 1:
        raise ValueError(
            f"variante ISTAT: {vecchio[:40]!r} deve comparire una sola volta"
        )
    return testo.replace(vecchio, nuovo)
