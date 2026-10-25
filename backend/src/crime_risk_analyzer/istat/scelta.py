"""Il modello sceglie i dati ISTAT che pesano, l'app scrive le frasi (#366).

Con questo modo il modello NON scrive frasi sui dati ISTAT: in coda alla risposta
elenca, per ogni rischio, la voce ISTAT che lo sostiene e quanto pesa::

    SCELTA DATI ISTAT:
    <etichetta del rischio> | <etichetta della voce> | alto|medio|basso

Le righe si ancorano alle righe del blocco DATI ISTAT (:func:`risolvi_scelta`):
una voce o un rischio che non vi compaiono, o non collegati fra loro, si scartano
(e si contano per motivo, :class:`ScartiScelta`).
Luogo, confronto con l'Italia e tendenza li compone l'app (:func:`componi_frase`)
con la stessa classificazione dell'indicatore
(:func:`~crime_risk_analyzer.istat.righe.confronto_italia`), quindi nessun pezzo
interno della riga (tendenza non calcolata, tipo di corrispondenza) finisce nel
testo. Le frasi vanno in fondo al blocco [ONTOLOGIA] (:func:`inserisci_frasi`),
ordinate dal peso piu' alto al piu' basso.

Il peso del modello decide solo l'ordine delle frasi: non e' un livello di
pericolosita' e non esce mai nel testo.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Final, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict

from crime_risk_analyzer.istat.cifre import SpanBlocco
from crime_risk_analyzer.istat.dati import VOCE_TOTALE
from crime_risk_analyzer.istat.righe import (
    DICITURA_CONFRONTO,
    RigaIstat,
    confronto_italia,
)

__all__ = [
    "INTESTAZIONE_SCELTA",
    "PESI",
    "RULE_ISTAT_SCELTA",
    "ScartiScelta",
    "SceltaGrezza",
    "SceltaIstat",
    "componi_frase",
    "componi_frasi",
    "estrai_scelta",
    "inserisci_frasi",
    "risolvi_scelta",
]

Peso = Literal["alto", "medio", "basso"]
#: Dal piu' al meno solido: l'ordine delle frasi composte.
PESI: Final[tuple[Peso, ...]] = ("alto", "medio", "basso")
_PESO_DI: Final[dict[str, Peso]] = {p: p for p in PESI}

#: Riga che il modello scrive prima dell'elenco delle scelte.
INTESTAZIONE_SCELTA = "SCELTA DATI ISTAT:"
_HEADER_SCELTA = re.compile(
    r"^[ \t*_#]*scelta dati istat[ \t*_:#]*(?P<resto>[^\n]*)$",
    re.IGNORECASE | re.MULTILINE,
)
_ELENCO = re.compile(r"^[\s\-*•]+")

#: Regola del prompt: sostituisce la regola 3c di #365 (frasi scritte dal modello).
RULE_ISTAT_SCELTA = (
    "3c. NON scrivere frasi sui dati ISTAT: le scrive l'applicazione. Per ogni "
    "rischio che ha una voce ISTAT collegata nella sezione DATI ISTAT, indica quale "
    "voce lo sostiene e quanto pesa, cosi' l'applicazione ordina i rischi e da' piu' "
    "spazio a quelli con un dato solido. Usa il peso per dare piu' spazio, nel testo, "
    "ai rischi con un dato solido (voce di corrispondenza esatta, tendenza e "
    "confronto indicati) e meno a quelli con un dato debole. In coda alla risposta, "
    f'dopo i blocchi, scrivi la riga "{INTESTAZIONE_SCELTA}" e, per ogni scelta, una '
    "riga nella forma: etichetta del rischio | etichetta della voce ISTAT | peso. "
    "Le etichette sono ESATTAMENTE quelle della sezione DATI ISTAT (la voce) e del "
    "VOCABOLARIO CONTROLLATO (il rischio); il peso e' uno fra alto, medio, basso. "
    "Nel testo non nominare i dati ISTAT, non scrivere cifre ISTAT ne' codici delle "
    "voci. Non scegliere la riga del totale dei delitti"
)


class SceltaGrezza(NamedTuple):
    """Riga di scelta letta dalla risposta, ancora da ancorare ai dati (peso grezzo)."""

    rischio: str
    voce: str
    peso: str


class SceltaIstat(BaseModel):
    """Scelta ancorata: la riga ISTAT, il rischio collegato e il peso."""

    model_config = ConfigDict(frozen=True)

    riga: RigaIstat
    hazard: str
    rischio: str
    peso: Peso


class ScartiScelta(BaseModel):
    """Righe di scelta scartate, per motivo (misura #368/#369, solo in memoria)."""

    model_config = ConfigDict(frozen=True)

    malformate: int = 0
    peso_non_valido: int = 0
    voce_non_nel_blocco: int = 0
    rischio_non_collegato: int = 0
    doppione: int = 0


def _chiave(testo: str) -> str:
    """Chiave di confronto fra etichette: unicode normalizzato, apostrofi tipografici
    e accenti ignorati, maiuscole e spazi ignorati."""
    base = unicodedata.normalize("NFKD", testo)
    base = base.replace("’", "'").replace("‘", "'")
    senza_accenti = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(senza_accenti.casefold().split())


def _parti(linea: str) -> list[str] | None:
    """Campi di una riga di scelta, ``None`` se non e' una riga del blocco."""
    pulita = _ELENCO.sub("", linea)
    if "|" not in pulita:
        return None
    return [p.strip() for p in pulita.split("|")]


def estrai_scelta(testo: str) -> tuple[str, list[SceltaGrezza], int]:
    """``(testo senza il blocco di scelta, righe lette, righe malformate)``.

    Il blocco e' l'intestazione piu' le righe che la seguono (formato ``a | b | c``,
    anche in elenco puntato; la prima puo' stare sulla riga dell'intestazione) e si
    toglie SEMPRE, anche se le righe non sono valide: non deve mai arrivare
    all'operatore. Finisce alla prima riga non vuota che non e' una riga di scelta:
    i blocchi successivi della risposta restano. Il peso resta grezzo (lo valida
    :func:`risolvi_scelta`).
    """
    trovata = _HEADER_SCELTA.search(testo)
    if trovata is None:
        return testo, [], 0
    linee = [(trovata.group("resto"), trovata.end())]
    cursore = trovata.end() + 1
    for linea in testo[cursore:].split("\n"):
        cursore += len(linea)
        linee.append((linea, cursore))
        cursore += 1
    grezze: list[SceltaGrezza] = []
    malformate = 0
    fine = trovata.end()
    for linea, fine_linea in linee:
        if not linea.strip():
            continue
        parti = _parti(linea)
        if parti is None:
            break
        fine = fine_linea
        if len(parti) == 3 and all(parti):
            grezze.append(SceltaGrezza(parti[0], parti[1], parti[2]))
        else:
            malformate += 1
    prima = testo[: trovata.start()].rstrip()
    dopo = testo[fine:].lstrip("\n")
    return (f"{prima}\n\n{dopo}" if dopo.strip() else prima), grezze, malformate


def risolvi_scelta(
    grezze: Sequence[SceltaGrezza],
    righe: Sequence[RigaIstat],
    *,
    malformate: int = 0,
) -> tuple[list[SceltaIstat], ScartiScelta]:
    """Ancora le scelte alle ``righe`` del blocco; scarta (contando) quelle che non
    reggono.

    Regge solo la scelta con peso fra alto/medio/basso (maiuscole e punto finale
    ignorati), la cui voce e' una riga del blocco (mai il totale) e il cui rischio e'
    uno di quelli collegati a quella voce. Ogni (luogo, voce, rischio) vale una
    volta, la prima. Ogni riga scartata conta per un solo motivo.
    """
    scelte: list[SceltaIstat] = []
    viste: set[tuple[str, str, str]] = set()
    peso_non_valido = voce_non_nel_blocco = rischio_non_collegato = doppione = 0
    for g in grezze:
        peso = _PESO_DI.get(_chiave(g.peso).strip(" .*_"))
        if peso is None:
            peso_non_valido += 1
            continue
        con_voce = [
            r
            for r in righe
            if r.voce != VOCE_TOTALE and _chiave(r.voce_label) == _chiave(g.voce)
        ]
        if not con_voce:
            voce_non_nel_blocco += 1
            continue
        collegate = [
            (r, c)
            for r in con_voce
            for c in r.collegamenti
            if _chiave(c.hazard_label_it) == _chiave(g.rischio)
        ]
        if not collegate:
            rischio_non_collegato += 1
            continue
        nuove = 0
        for riga, c in collegate:
            chiave = (riga.luogo_codice, riga.voce, c.hazard)
            if chiave in viste:
                continue
            viste.add(chiave)
            nuove += 1
            scelte.append(
                SceltaIstat(
                    riga=riga, hazard=c.hazard, rischio=c.hazard_label_it, peso=peso
                )
            )
        if not nuove:
            doppione += 1
    scarti = ScartiScelta(
        malformate=malformate,
        peso_non_valido=peso_non_valido,
        voce_non_nel_blocco=voce_non_nel_blocco,
        rischio_non_collegato=rischio_non_collegato,
        doppione=doppione,
    )
    return scelte, scarti


_QUALIFICA = {
    "piu_larga": "la voce comprende anche altri reati",
    "piu_stretta": "la voce copre solo una parte del rischio",
}


def componi_frase(scelta: SceltaIstat) -> str | None:
    """Frase della scelta, o ``None`` se non c'e' ne' confronto ne' tendenza da dire.

    Niente cifre (le mostra l'interfaccia). La tendenza si dice solo se calcolata;
    la corrispondenza solo se la voce non coincide col rischio.
    """
    riga = scelta.riga
    classe = confronto_italia(riga)
    parti: list[str] = []
    if classe is not None:
        parti.append(f"un {DICITURA_CONFRONTO[classe]}")
    if riga.variazione_pct is not None:
        if riga.variazione_pct > 0:
            andamento = "in crescita"
        elif riga.variazione_pct < 0:
            andamento = "in calo"
        else:
            andamento = "stabile"
        parti.append(f"un andamento {andamento} dal {riga.anno_confronto}")
    if not parti:
        return None
    frase = (
        f"Secondo i dati ISTAT del {riga.luogo_nome} ({riga.anno}), la voce "
        f"«{riga.voce_label}» (rischio: {scelta.rischio}) ha {' e '.join(parti)}"
    )
    corrispondenza = next(
        (c.corrispondenza for c in riga.collegamenti if c.hazard == scelta.hazard),
        None,
    )
    qualifica = _QUALIFICA.get(corrispondenza or "")
    return f"{frase}; {qualifica}." if qualifica else f"{frase}."


def componi_frasi(scelte: Sequence[SceltaIstat]) -> list[str]:
    """Frasi delle scelte, dal peso piu' alto al piu' basso (stabile a parita')."""
    ordinate = sorted(scelte, key=lambda s: PESI.index(s.peso))
    frasi = (componi_frase(s) for s in ordinate)
    return [f for f in frasi if f is not None]


def inserisci_frasi(
    testo: str, spans: Sequence[SpanBlocco], frasi: Sequence[str]
) -> str:
    """Mette ``frasi`` in fondo al blocco [ONTOLOGIA] di ``testo`` (``spans`` sono i
    suoi blocchi); se non c'e' ne apre uno in coda."""
    if not frasi:
        return testo
    prosa = " ".join(frasi)
    ontologia = next((s for s in spans if s.campo == "ontologia"), None)
    if ontologia is None:
        return f"{testo.rstrip()}\n\nRischi da ontologia [ONTOLOGIA]\n{prosa}"
    corpo = testo[ontologia.inizio : ontologia.fine]
    pieno = corpo.rstrip()
    return (
        f"{testo[: ontologia.inizio]}{pieno}\n{prosa}"
        f"{corpo[len(pieno) :]}{testo[ontologia.fine :]}"
    )
