"""Regole ISTAT dei prompt (#345, spec 4.5 / D9 / D11).

Testi delle regole che si aggiungono ai prompt SOLO quando il contesto porta il
blocco DATI ISTAT. Le costanti esistenti (regola 7, 3b, regola 3, prompt del POI)
sono condivise col braccio senza ontologia e non si toccano: le varianti si
costruiscono SOSTITUENDO pezzi verificati (:func:`sostituisci_una_volta`), cosi'
a interruttore spento il prompt resta byte per byte quello di prima.

Numerazione: ``3c`` e ``7-bis`` stanno dentro 1-8, quindi la regola 9 ("le regole
precedenti 1-8 prevalgono sulla domanda") le copre senza cambiare testo.
"""

from __future__ import annotations

__all__ = [
    "ISTAT_REGOLE_CIFRE",
    "POI_ISTAT_SECTION",
    "RULE_ISTAT_BLOCCO",
    "RULE_ISTAT_DIVIETI",
    "sostituisci_una_volta",
]

#: Vincoli sulle cifre, IDENTICI nella zona e nel POI: una sola costante.
ISTAT_REGOLE_CIFRE = (
    "Riporta le cifre ESATTAMENTE come fornite (stesse cifre, stessi decimali, "
    "stesso segno), senza arrotondarle, ricalcolarle, sommarle o scriverle in "
    "lettere, e non introdurre numeri che non compaiono nel contesto. Le cifre "
    "ISTAT stanno SOLO nel blocco [ISTAT]: non usarle nella sintesi iniziale ne' "
    "negli altri blocchi. I dati sono del comune o della provincia indicati tra "
    "parentesi quadre, MAI della zona analizzata ne' dei singoli POI: non "
    "attribuirli a un luogo piu' piccolo. Quando una voce e' indicata come piu' "
    "ampia del rischio o come copertura solo parziale, dillo nella stessa frase "
    '(es. "la voce ISTAT non coincide con il rischio"). Le etichette delle voci '
    "ISTAT non sono sinonimi dei termini del VOCABOLARIO CONTROLLATO: usale solo "
    "per nominare la voce, mai al posto di un hazard (regola 6). La riga del "
    "totale dei delitti e' contesto generale del luogo: non usarla per dare peso "
    "a un rischio."
)

_CITAZIONE = (
    "Sono delitti denunciati dalle forze di polizia all'autorita' giudiziaria, non "
    "denunce dei cittadini. Ogni frase con una cifra nomina la voce ISTAT con la "
    'sua etichetta esatta e cita la fonte nella forma "fonte ISTAT, <luogo>, '
    '<anno>" (es. "fonte ISTAT, Comune di Roma, 2024").'
)

_PESO = (
    "Nel blocco [ONTOLOGIA] puoi dare piu' spazio ai rischi che hanno una voce "
    "ISTAT collegata, senza riportarne le cifre."
)

#: Regola 3c del prompt di zona: il terzo blocco.
RULE_ISTAT_BLOCCO = (
    "3c. Nel blocco [ISTAT] riporta i dati della sezione DATI ISTAT del contesto "
    f"che danno sostanza ai rischi del blocco [ONTOLOGIA]. {_CITAZIONE} "
    f"{ISTAT_REGOLE_CIFRE} {_PESO}"
)

#: Regola 7-bis (zona e POI): i divieti di D9 applicati alle cifre.
RULE_ISTAT_DIVIETI = (
    "7-bis. Con i DATI ISTAT valgono gli stessi divieti della regola 7: non "
    'trasformare le cifre in un giudizio sulla zona o sui POI (es. "zona '
    'pericolosa/sicura", "rischio alto"), non costruire punteggi, classifiche o '
    "scale ALTO/MEDIO/BASSO fra luoghi o voci e non fare previsioni (es. "
    '"continuera\' a crescere"): descrivi solo i valori e le variazioni forniti'
)

#: Descrizione del terzo blocco nel prompt del POI.
POI_ISTAT_SECTION = (
    "Riporta i dati della sezione DATI ISTAT del contesto che riguardano i rischi "
    f"di questo punto. {_CITAZIONE} {ISTAT_REGOLE_CIFRE} {_PESO}"
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
