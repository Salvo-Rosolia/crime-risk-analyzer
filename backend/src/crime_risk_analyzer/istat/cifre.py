"""Controllo delle frasi della narrativa con i dati ISTAT nel prompt (#345, #365).

Meccanismo NUOVO di #345: per la prima volta una frase generata puo' essere tolta
dopo la generazione. Gira solo quando il prompt conteneva il blocco DATI ISTAT. Da
#365 il modello usa i dati ISTAT a parole dentro il blocco [ONTOLOGIA] e non
scrive cifre (le mostra l'interfaccia): nessun blocco e' piu' il posto delle cifre
ISTAT, e il controllo verifica cio' che la frase dice del dato.

1. Divisione in frasi che non spezza i numeri ("3.016", "1.162,7"): si spezza dopo
   ``.!?`` seguiti da spazio e a ogni a-capo; il ``;`` NON chiude la frase; i
   marcatori d'elenco a inizio riga ("1.", "-", "*") non fanno parte della frase.
   (``eval.metrics._sentences`` spezza a ogni punto e non va riusata.) La prosa
   scritta sulla stessa riga dell'etichetta, dopo il token (``Dati statistici
   ISTAT [ISTAT]: nel Comune ...``), appartiene al blocco che l'etichetta apre:
   solo il controllo la sposta, il parser dei blocchi (che alimenta M1) resta
   com'e'. Le abbreviazioni comuni (``d.lgs.``, ``art.``, ``n.``, ``es.``,
   ``ecc.``, ``cfr.``) non chiudono la frase: le righe DATI ISTAT stesse scrivono
   "(d.lgs. 7/2016)" (R4, review 2).
2. Numeri normalizzati all'italiana: ``.`` seguito da gruppi di tre cifre e' il
   separatore delle migliaia (come l'NBSP e lo spazio stretto NNBSP), altrimenti
   e' decimale; ``,`` e' decimale; ``−`` e ``–`` (trattino medio) valgono ``-``;
   un ``-`` (o ``–``) fra due cifre e' un intervallo ("2014-2024" sono due anni,
   non un segno); "per cento"/"percento" dopo un numero vale ``%``. Lo spazio
   normale vale come separatore delle migliaia solo se il numero unito e' ammesso
   o se le sue parti non lo sono tutte: "134 169" resta 134.169, ma "negli ultimi
   10 340 furti" sono 10 e 340 (R8, review 2). Un riferimento ``N/AAAA``
   ("d.lgs. 7/2016") non e' un numero da controllare.
3. Ammessi: tutti i numeri dello user_content (blocco DATI ISTAT compreso) TRANNE
   quelli della domanda dell'utente (input non fidato: non deve mai mettere in
   lista una cifra, R2 review 2), piu' la lista fissa (100.000, ``Y``, ``Y-10``,
   0,1), l'ampiezza del periodo ``Y - Y_confronto`` ("negli ultimi 10 anni"), che
   senza ``%`` e' un numero qualunque e mai una cifra ISTAT, e le cifre ISTAT
   delle righe: il blocco a parole (#365 D7) non le porta piu', ma una cifra ISTAT
   scritta dal modello va riconosciuta come tale e non come numero inventato.
   Cifre ISTAT: conteggi, tassi, tasso nazionale delle righe (le
   :class:`~crime_risk_analyzer.istat.righe.RigaIstat`, non il testo del blocco),
   piu' le variazioni ma SOLO quando scritte con ``%`` (un numero senza ``%`` puo'
   coincidere per caso col valore assoluto di una variazione — es. "10" in "negli
   ultimi 10 anni" — e non va scambiato per una cifra ISTAT); in ogni caso tranne
   quelli che compaiono anche nel contesto fuori dal blocco o nella lista fissa
   (non si puo' dire a cosa si riferiscano).
4. Una frase "parla del dato ISTAT" se nomina "ISTAT", i "delitti denunciati", la
   media, il dato o il tasso italiano o nazionale, "quello italiano", "rispetto
   all'Italia", oppure contiene una cifra ISTAT ("a livello nazionale" no, B1).
   Ne parla anche se nomina una voce delle righe (o un rischio collegato, come
   in C1) insieme a "tasso", "voce" o "dal <anno di confronto>": "I furti hanno
   un tasso piu' alto e sono in calo dal 2014". "tasso" conta solo seguito a
   breve da un confronto o come "tasso di/dei <voce>", "voce" solo come "la/questa
   voce", "voce piu' ampia/stretta", "voce ... coincide/corrisponde"
   (fix 4: "Area ad alto tasso di criminalita'" e' una vulnerabilita'
   dell'ontologia, non un dato ISTAT). Il markdown (``**``, ``_``) si
   toglie prima di cercare etichette e luoghi.
   Il solo nome del luogo non basta (R1, review 2): "A Roma la folla aumenta le
   occasioni di furti" parla del rischio, non della statistica, e resta. Una
   frase dentro un ``[ISTAT]`` residuo ne parla sempre (C3); la sua riga-etichetta
   mai (nomina ISTAT ma non dice nulla del dato). Dentro un paragrafo che ha gia'
   nominato il luogo del dato, ne parla anche una frase con una voce (o un rischio
   collegato) e una parola di tendenza o di confronto: "- furti: in crescita;"
   nell'elenco dopo "I dati ISTAT del Comune di Roma (2024) indicano:" (C-2).
5. Regole, nell'ordine (la prima che scatta e' il motivo):

   - ``numero_non_ammesso``: un numero fuori dagli ammessi;
   - ``cifra_istat_fuori_blocco``: una cifra ISTAT, in QUALUNQUE blocco (#365:
     anche dentro un ``[ISTAT]`` scritto per errore; il nome del motivo e' quello
     di #345);
   - ``luogo_mancante`` (#365): una frase che parla del dato ISTAT non nomina un
     luogo delle righe (per esteso, "Comune di Roma", o per nome breve) e non ne
     eredita uno. Eredita il luogo della frase ISTAT precedente, tenuta, dello
     stesso paragrafo (elenco compreso): "I dati ISTAT del Comune di Roma ...:"
     seguito dalle voci. Un nuovo luogo sostituisce quello ereditato; non si
     eredita oltre una riga vuota, a un cambio di blocco ne' da una frase tolta;
     un'introduzione che finisce con ":" passa pero' il luogo all'elenco che la
     segue anche oltre righe vuote, finche' l'elenco continua (fix 6).
     Il campo ``luogo`` dice solo se il luogo e' esplicito, ``luogo_ereditato``
     se e' ereditato;
   - ``direzione_contraria``: in una frase che parla del dato ISTAT, parole di
     tendenza ("in aumento", "in calo", "scesi", "si sono ridotti", "stabile"...)
     contrarie al segno della variazione di una qualunque delle voci nominate
     (C-1); "stabile" e' giusto solo con variazione 0, come scrive il blocco
     (C-3). Le forme causali o aggettivali ("aumenta le occasioni", "ridotta",
     "riduzione", le "sale" giochi) non contano. Se non c'e' una voce o una voce
     non ha una tendenza calcolata (serie interrotta, anno mancante, sotto soglia)
     la direzione non e' verificabile e la frase si toglie lo stesso, con questo
     motivo;
   - ``confronto_contrario`` (#365): in una frase che parla del dato ISTAT, una
     parola di confronto col dato italiano ("sopra/sotto la media", "al di
     sopra/sotto", "piu' alto/basso/elevato/contenuto/frequente/diffuso", "meno
     alto/elevato/frequente/diffuso" (= piu' basso), "meno basso" (= piu' alto),
     "superiore/inferiore", "maggiore/minore", "supera", "simile", "in linea",
     "pari a") che non concorda, per una qualunque delle voci nominate (C-1), con
     la classificazione della riga
     (:func:`~crime_risk_analyzer.istat.righe.confronto_italia`, la stessa che
     scrive il confronto nel blocco DATI ISTAT). La parola conta solo se seguita a
     breve, nella stessa proposizione, dal termine di paragone (B2, C-4): la
     media, (dato|tasso|valore|livello|quello) italiano o nazionale, l'Italia;
     non l'aggettivo da solo ("una minore presenza di turisti italiani"),
     oppure se poco prima c'e' "tasso" ("un tasso piu' alto": il termine
     implicito e' l'Italia): "reati simili", "piano superiore", "in linea con
     l'ontologia" non sono confronti. Si toglie con lo stesso motivo una frase
     senza voce, su una voce senza classificazione (un tasso mancante, il
     nazionale a 0) o con confronti di classi diverse.

   La voce e' quella nominata con l'etichetta (o il codice); se la frase ha una
   tendenza o un confronto ma nessuna etichetta, si cerca il nome italiano dei
   rischi collegati alle voci (C1: "il furto di beni ha un tasso piu' alto...");
   se ancora nessuna, "delitti denunciati" vale come il totale dei delitti.
   Direzione e confronto devono valere per TUTTE le voci nominate (C-1, anche
   quelle risolte da un rischio collegato a piu' voci) e usano i valori del luogo
   nominato: se la frase nomina un luogo per esteso valgono quelli di QUEL luogo
   per la voce; il nome breve ("Roma") vale per tutti i luoghi delle righe che si
   chiamano cosi' (comune e provincia) e per una voce basta che uno concordi (R6,
   review 2). Una frase con parole di tendenze diverse non si verifica su
   quell'asse.
6. I numeri in lettere ("il doppio") e i codici delle voci scritti dal modello
   ("THEFT") si contano per la valutazione, non si tolgono.
7. Testo filtrato (C5): se tutte le frasi di un ``[ISTAT]`` residuo sono tolte si
   toglie anche la sua riga-etichetta, che resterebbe orfana; niente righe vuote
   in testa ne' buchi di piu' righe vuote lasciati dai tagli.

Il testo grezzo resta disponibile: l'esito porta il testo filtrato (cio' che vede
l'operatore) e quello senza le frasi ISTAT (per la metrica M1, #368).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict

from crime_risk_analyzer.istat.blocco import BloccoIstat
from crime_risk_analyzer.istat.dati import VOCE_TOTALE
from crime_risk_analyzer.istat.righe import ConfrontoItalia, RigaIstat, confronto_italia

__all__ = [
    "Blocco",
    "Confronto",
    "EsitoControllo",
    "FraseControllata",
    "Motivo",
    "Numero",
    "SpanBlocco",
    "applica_controllo",
    "confronto_di",
    "controlla_cifre",
    "direzione_di",
    "dividi_frasi",
    "estrai_numeri",
    "valori_del_testo",
    "voci_nominate",
]

Blocco = Literal[
    "overview", "intestazione", "ontologia", "contesto", "speculativo", "istat"
]
Motivo = Literal[
    "numero_non_ammesso",
    "cifra_istat_fuori_blocco",
    "luogo_mancante",
    "direzione_contraria",
    "confronto_contrario",
]
Direzione = Literal["su", "giu", "stabile", ""]
#: Confronto col dato italiano scritto nella frase: ``""`` se nessuno, ``"misto"``
#: se la frase ne usa di classi diverse (non verificabile, B2).
Confronto = ConfrontoItalia | Literal["", "misto"]

_BLOCCHI_DI_FONTE: frozenset[str] = frozenset(
    {"ontologia", "contesto", "speculativo", "istat"}
)


class SpanBlocco(NamedTuple):
    """Blocco per fonte della narrativa: riga-etichetta e corpo (offset nel testo)."""

    campo: str
    inizio_riga: int
    inizio: int
    fine: int


class Numero(NamedTuple):
    """Numero estratto: valore assoluto normalizzato, segno esplicito, percentuale."""

    valore: Decimal
    segno: str
    percentuale: bool


_NUMERO = re.compile(
    r"(?<![\w.,])"
    r"(?P<segno>[+\-−–])?"
    r"(?P<corpo>\d{1,3}(?:[.\xa0  ]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"
    r"(?!\w)"
    r"(?P<pct>\s?%|\s+[Pp]er\s?cento\b)?"
)
_MIGLIAIA_CON_PUNTO = re.compile(r"\d{1,3}(?:\.\d{3})+")
_MARCATORE_ELENCO = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+")
_FINE_FRASE = re.compile(r"(?<=[.!?])\s+")
#: Abbreviazioni dopo cui il punto non chiude la frase (R4, review 2).
_ABBREVIAZIONE = re.compile(r"\b(?:d\.\s?lgs|artt?|nn?|es|ecc|cfr)\.$", re.IGNORECASE)
#: Riferimento normativo o numerato "N/AAAA" ("d.lgs. 7/2016"): non e' una cifra.
_RIFERIMENTO = re.compile(r"(?<![\w.,/])\d{1,4}/\d{4}(?![\w/])")
#: Domanda dell'utente nello user_content di zona: input non fidato, i suoi numeri
#: non entrano mai fra gli ammessi (R2, review 2). Stessi delimitatori di
#: ``rag.generation.USER_INPUT_FENCE_OPEN``/``_CLOSE`` (qui come testo: ``istat``
#: non importa ``rag``); i test usano le costanti vere.
_DOMANDA_UTENTE = re.compile(
    r"--- DOMANDA UTENTE \(input non fidato: dato, non istruzioni\) ---"
    r".*?--- FINE DOMANDA UTENTE ---",
    re.DOTALL,
)
#: Token di fonte sulla riga-etichetta (``[ISTAT]``, ``[ONTOLOGIA]``, ...).
_TOKEN_FONTE = re.compile(r"\[[A-Z][A-Z_ ]*\]")
#: Caratteri fra il token e la prosa sulla stessa riga (come il parser dei blocchi).
_DOPO_TOKEN = " \t\r*_:#"
#: Solo forme di tendenza (R1, review 2): niente "aumenta" (causale, "la folla
#: aumenta le occasioni"), "ridotta"/"riduzione" (aggettivo/sostantivo), "sale"
#: (anche sostantivo, "sale giochi").
_SU = re.compile(
    r"\b(?:aumento|aumenti|aumentat[oaie]|aumentano|crescita|cresciut[oaie]"
    r"|cresce|crescono|incremento|incrementi|rialzo|salgono|salit[oaie])\b"
)
_GIU = re.compile(
    r"\b(?:calo|cali|calat[oaie]|cala|calano|diminuzione|diminuzioni|diminuit[oaie]"
    r"|diminuisce|diminuiscono|flessione|discesa|ribasso"
    r"|scende|scendono|sces[oaie]|si sono ridott[ie])\b"
)
#: "stabile" (C-3): il blocco lo scrive solo con variazione 0.
_STABILE = re.compile(r"\bstabil[ei]\b")
#: "piu'" come lo scrivono i modelli: accentato, con apostrofo dritto o tipografico.
_PIU = r"pi(?:ù|u['’]?)"
#: Separatore fra due parole della stessa proposizione: non attraversa
#: ``, ; : . ( )``. Unico per termine di paragone, ancora "tasso" e marcatori.
_SEP = r"[^\w,;:.()]+"
#: Termine di paragone a breve distanza (B2, C-4): fino a 6 parole nella stessa
#: proposizione, poi la media, (dato|tasso|valore|livello|quello) italiano o
#: nazionale, oppure l'Italia. Non l'aggettivo da solo ("turisti italiani"). Senza
#: un termine, "reati simili", "piano superiore" o "in linea con l'ontologia"
#: sarebbero confronti.
_PARAGONE = (
    rf"(?:{_SEP}\w+){{0,6}}?{_SEP}"
    r"(?:media\b|(?:dato|tasso|valore|livello|quell[oaie])\s+"
    r"(?:italian[oaie]|nazional[ei])\b|italia\b)"
)
#: Ancora del confronto implicito: "un tasso piu' alto" senza dire di cosa vuol
#: dire rispetto all'Italia (l'unico confronto delle righe). "tasso" deve stare
#: poco prima (al massimo 3 parole) nella stessa proposizione. Lo stesso pezzo fa
#: da marcatore ISTAT (fix 4, :func:`_marcatori`).
_TASSO_PRIMA = rf"\btasso(?:{_SEP}\w+){{0,3}}?{_SEP}"
_PAROLE_CONFRONTO: dict[ConfrontoItalia, str] = {
    "piu_alto": (
        rf"al di sopra|sopra|{_PIU}\s+(?:alt|elevat|frequent|diffus)[oaie]"
        r"|meno\s+bass[oaie]|superior[ei]|maggior[ei]|supera|superano"
    ),
    "piu_basso": (
        rf"al di sotto|sotto|{_PIU}\s+(?:bass|contenut)[oaie]"
        r"|meno\s+(?:alt|elevat|frequent|diffus)[oaie]|inferior[ei]|minor[ei]"
    ),
    "simile": r"simil[ei]|in linea|pari a",
}
_TUTTI_I_CONFRONTI = "|".join(f"(?:{p})" for p in _PAROLE_CONFRONTO.values())
#: Parole di confronto col dato italiano (#365 D3): le tre classi della riga.
#: Contano seguite dal termine di paragone (B2) o precedute da "tasso".
_CONFRONTI: dict[ConfrontoItalia, re.Pattern[str]] = {
    classe: re.compile(rf"\b(?:{parole})\b{_PARAGONE}|{_TASSO_PRIMA}(?:{parole})\b")
    for classe, parole in _PAROLE_CONFRONTO.items()
}
_DELITTI_DENUNCIATI = r"\bdelitti denunciati\b"
#: Il totale nominato come "delitti denunciati" (senza un'altra voce).
_TOTALE_IMPLICITO = re.compile(_DELITTI_DENUNCIATI)
#: Quando una frase parla del dato ISTAT (#365 D3; R1: il solo luogo non basta;
#: B1: "livello"/"valore" nazionale no, "di interesse a livello nazionale").
_PARLA_DI_ISTAT = re.compile(
    rf"\bistat\b|{_DELITTI_DENUNCIATI}"
    r"|\b(?:media|dato|dati|tasso)\s+(?:italian[oai]|nazional[ei])\b"
    r"|\bquell[oa]\s+italian[oa]\b"
    r"|\brispetto all'\s?italia\b"
)
_IN_LETTERE = re.compile(
    r"\b(?:mille|duemila|tremila|quattromila|cinquemila|diecimila|centomila"
    r"|milion[ei]|miliard[oi]|doppio|triplo|met[aà]|raddoppiat\w*|triplicat\w*"
    r"|dimezzat\w*)\b"
)
#: Come il modello nomina la cornice: "totale dei delitti" (denunciati o no).
_ETICHETTA_TOTALE = "totale dei delitti"


class FraseControllata(BaseModel):
    """Una frase della narrativa e il verdetto del controllo."""

    model_config = ConfigDict(frozen=True)

    testo: str
    blocco: Blocco
    inizio: int
    fine: int
    #: ``None`` = tenuta; altrimenti il motivo per cui e' tolta.
    motivo: Motivo | None = None
    #: Numeri fuori dalla lista fissa.
    cifre: int = 0
    #: Cifre ISTAT scritte dal modello (#365: sempre tolte, attese 0).
    cifre_istat: int = 0
    voci: tuple[str, ...] = ()
    #: La frase parla del dato ISTAT (punto 4 del modulo).
    parla_di_istat: bool = False
    #: La frase nomina ESPLICITAMENTE almeno un luogo delle righe.
    luogo: bool = False
    #: La frase parla del dato senza nominare un luogo e usa quello detto prima
    #: nello stesso paragrafo (fix 3).
    luogo_ereditato: bool = False
    #: Codici dei luoghi con cui la frase e' stata verificata (espliciti o
    #: ereditati); vuoto se nessuno.
    luoghi: tuple[str, ...] = ()
    direzione: Direzione = ""
    #: ``None`` se la frase non usa parole di direzione su una voce con variazione.
    direzione_coerente: bool | None = None
    confronto: Confronto = ""
    #: ``None`` se la frase non confronta col dato italiano una voce classificata.
    confronto_coerente: bool | None = None


class EsitoControllo(BaseModel):
    """Esito del controllo su una narrativa."""

    model_config = ConfigDict(frozen=True)

    frasi: tuple[FraseControllata, ...]
    testo_filtrato: str
    #: Testo grezzo senza le frasi che il controllo riconosce come ISTAT (#368): e'
    #: quello su cui M1 misura le asserzioni. Limiti noti (#369): taglia anche frasi
    #: che nominano un POI o un rischio, e il luogo che il controllo eredita passa
    #: solo dalle frasi che il filtro tiene, quindi dipende dal filtro.
    testo_senza_frasi_istat: str
    numeri_in_lettere: int
    righe: tuple[RigaIstat, ...]
    #: Codici delle voci delle righe scritti dal modello (maiuscolo, a parola
    #: intera): si contano per la valutazione, non tolgono la frase.
    codici_voce: int = 0

    @property
    def frasi_scartate(self) -> int:
        """Quante frasi il filtro ha tolto."""
        return sum(1 for f in self.frasi if f.motivo is not None)


def _valore(corpo: str) -> Decimal:
    pulito = corpo.replace("\xa0", "").replace("\u202f", "").replace(" ", "")
    if "," in pulito:
        intera, decimali = pulito.split(",", 1)
        return Decimal(f"{intera.replace('.', '')}.{decimali}")
    if _MIGLIAIA_CON_PUNTO.fullmatch(pulito):
        return Decimal(pulito.replace(".", ""))
    return Decimal(pulito)


def _parti_con_spazio(corpo: str, ammessi: set[Decimal] | None) -> list[Decimal] | None:
    """Le parti di ``corpo`` separate da spazi normali, se vanno lette come numeri
    distinti: il numero unito non e' ammesso e ogni parte si' (R8, review 2)."""
    if ammessi is None or " " not in corpo or _valore(corpo) in ammessi:
        return None
    parti = [_valore(p) for p in corpo.split(" ")]
    return parti if all(p in ammessi for p in parti) else None


def estrai_numeri(testo: str, ammessi: set[Decimal] | None = None) -> list[Numero]:
    """Numeri di una frase o di una riga (il marcatore d'elenco iniziale non conta).

    Con ``ammessi``, un numero con lo spazio normale come separatore delle migliaia
    che non e' ammesso ma le cui parti lo sono tutte si legge come numeri distinti
    ("negli ultimi 10 340 furti" -> 10 e 340). I riferimenti ``N/AAAA`` non contano.
    """
    testo = _MARCATORE_ELENCO.sub("", testo, count=1)
    testo = _RIFERIMENTO.sub(" ", testo)
    numeri: list[Numero] = []
    for m in _NUMERO.finditer(testo):
        segno = (m.group("segno") or "").replace("−", "-").replace("–", "-")
        pct = m.group("pct") is not None
        parti = _parti_con_spazio(m.group("corpo"), ammessi)
        if parti is None:
            numeri.append(Numero(_valore(m.group("corpo")), segno, pct))
            continue
        ultima = len(parti) - 1
        numeri.extend(
            Numero(v, segno if i == 0 else "", pct and i == ultima)
            for i, v in enumerate(parti)
        )
    return numeri


def valori_del_testo(testo: str) -> set[Decimal]:
    """Valori di tutti i numeri di un testo, riga per riga."""
    return {n.valore for riga in testo.split("\n") for n in estrai_numeri(riga)}


def dividi_frasi(testo: str) -> list[tuple[int, int]]:
    """Offset ``(inizio, fine)`` delle frasi; mai a cavallo di un a-capo."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for riga in testo.split("\n"):
        marcatore = _MARCATORE_ELENCO.match(riga)
        inizio = marcatore.end() if marcatore else 0
        for m in _FINE_FRASE.finditer(riga, inizio):
            if _ABBREVIAZIONE.search(riga, inizio, m.start()):
                continue
            if riga[inizio : m.start()].strip():
                spans.append((pos + inizio, pos + m.start()))
            inizio = m.end()
        if riga[inizio:].strip():
            spans.append((pos + inizio, pos + len(riga)))
        pos += len(riga) + 1
    return spans


def _blocco_di(pos: int, blocchi: Sequence[SpanBlocco]) -> Blocco:
    for b in blocchi:
        if b.inizio_riga <= pos < b.inizio:
            return "intestazione"
        if b.inizio <= pos < b.fine and b.campo in _BLOCCHI_DI_FONTE:
            return b.campo  # pyright: ignore[reportReturnType]
    return "overview"


#: Una tendenza o un confronto appartiene a una voce IN un luogo (R6, review 2).
_Chiave = tuple[str, str]


def _cifre_istat(righe: Sequence[RigaIstat], escluse: set[Decimal]) -> set[Decimal]:
    """Conteggi e tassi delle righe: cifre ISTAT sempre, col ``%`` o senza."""
    return {
        d
        for r in righe
        for v in (r.delitti, r.delitti_confronto, r.tasso, r.tasso_italia)
        if v is not None
        for d in (Decimal(str(v)),)
        if d not in escluse
    }


def _variazioni(righe: Sequence[RigaIstat], escluse: set[Decimal]) -> set[Decimal]:
    """Valore assoluto delle variazioni: cifra ISTAT solo se scritto con ``%``
    (altrimenti un numero come "10" in "negli ultimi 10 anni" non e' una cifra
    ISTAT solo perche' coincide col valore assoluto di una variazione)."""
    return {
        d
        for r in righe
        if r.variazione_pct is not None
        for d in (Decimal(str(abs(r.variazione_pct))),)
        if d not in escluse
    }


def _tendenze(righe: Sequence[RigaIstat]) -> dict[_Chiave, set[int]]:
    tendenze: dict[_Chiave, set[int]] = {}
    for r in righe:
        if r.variazione_pct is not None:
            tendenze.setdefault((r.luogo_codice, r.voce), set()).add(r.variazione_pct)
    return tendenze


def _classi(righe: Sequence[RigaIstat]) -> dict[_Chiave, ConfrontoItalia | None]:
    """Confronto col tasso italiano di ogni (luogo, voce), come nel blocco."""
    return {(r.luogo_codice, r.voce): confronto_italia(r) for r in righe}


def _luoghi(righe: Sequence[RigaIstat]) -> list[tuple[str, str, str]]:
    """``(codice, nome, nome breve)`` in minuscolo dei luoghi delle righe."""
    return sorted(
        {(r.luogo_codice, r.luogo_nome.lower(), r.luogo_breve.lower()) for r in righe}
    )


def _etichette(righe: Sequence[RigaIstat]) -> list[tuple[str, str]]:
    coppie = {
        (r.voce, _ETICHETTA_TOTALE if r.voce == VOCE_TOTALE else r.voce_label.lower())
        for r in righe
    }
    # Dalla piu' lunga: "furti con strappo" va riconosciuta prima di "furti".
    return sorted(coppie, key=lambda c: (-len(c[1]), c[0]))


def _rischi(righe: Sequence[RigaIstat]) -> list[tuple[str, str]]:
    """``(voce, etichetta italiana del rischio collegato)`` per risolvere la voce di
    una frase che nomina il rischio invece della voce (C1)."""
    coppie = {
        (r.voce, _normalizza(c.hazard_label_it)) for r in righe for c in r.collegamenti
    }
    return sorted(coppie, key=lambda c: (-len(c[1]), c[0]))


def _normalizza(testo: str) -> str:
    """Minuscolo, apostrofo tipografico come quello dritto, senza il markdown
    (``**furti**``, ``_furti_``) che separerebbe le parole dalle etichette."""
    return re.sub(r"[*_]", "", testo.lower().replace("’", "'"))


def voci_nominate(testo: str, etichette: Sequence[tuple[str, str]]) -> set[str]:
    """Voci nominate in ``testo`` per etichetta (esatta) o per codice ISTAT.

    Un'etichetta riconosciuta si toglie dal testo, cosi' "furti con strappo" non
    nomina anche "furti"; la stessa etichetta vale pero' per tutte le voci che la
    portano (un rischio collegato a piu' voci, C1)."""
    trovate: set[str] = set()
    resto = _normalizza(testo)
    riconosciute: set[str] = set()
    for voce, etichetta in etichette:
        etichetta = _normalizza(etichetta)
        modello = re.compile(rf"\b{re.escape(etichetta)}\b")
        if etichetta in riconosciute or modello.search(resto):
            trovate.add(voce)
            riconosciute.add(etichetta)
            resto = modello.sub(" ", resto)
        if re.search(rf"\b{re.escape(voce)}\b", testo):
            trovate.add(voce)
    return trovate


def _luoghi_nominati(
    testo: str, luoghi: Sequence[tuple[str, str, str]]
) -> set[str] | None:
    """Codici dei luoghi delle righe nominati nella frase, ``None`` se nessuno.

    Prima i nomi per esteso ("comune di roma"), poi i nomi brevi nel testo che
    resta: "Roma" da sola vale per tutti i luoghi delle righe che si chiamano cosi'
    (comune e provincia), quindi non restringe nulla fra i due."""
    resto = _normalizza(testo)
    trovati: set[str] = set()
    for codice, nome, _ in luoghi:
        modello = re.compile(rf"\b{re.escape(nome)}\b")
        if modello.search(resto):
            trovati.add(codice)
            resto = modello.sub(" ", resto)
    for codice, _, breve in luoghi:
        if re.search(rf"\b{re.escape(breve)}\b", resto):
            trovati.add(codice)
    return trovati or None


def direzione_di(testo: str) -> Direzione:
    """``su``/``giu``/``stabile`` se la frase ha parole di una sola tendenza,
    altrimenti ``""``."""
    minuscolo = _normalizza(testo)
    tendenze: tuple[tuple[Direzione, re.Pattern[str]], ...] = (
        ("su", _SU),
        ("giu", _GIU),
        ("stabile", _STABILE),
    )
    trovate: list[Direzione] = [
        d for d, modello in tendenze if modello.search(minuscolo)
    ]
    if len(trovate) != 1:
        return ""
    return trovate[0]


def confronto_di(testo: str) -> Confronto:
    """Classe di confronto col dato italiano scritta nella frase (#365): una parola
    di confronto conta solo se seguita a breve dal termine di paragone (B2);
    ``"misto"`` se la frase ne usa di classi diverse."""
    minuscolo = _normalizza(testo)
    trovati: list[ConfrontoItalia] = [
        c for c, modello in _CONFRONTI.items() if modello.search(minuscolo)
    ]
    if not trovati:
        return ""
    if len(trovati) > 1:
        return "misto"
    return trovati[0]


def _coerente(direzione: Direzione, tendenza: int) -> bool:
    if direzione == "stabile":
        return tendenza == 0
    return tendenza > 0 if direzione == "su" else tendenza < 0


def _nel_luogo(chiave: _Chiave, voci: set[str], luoghi: set[str] | None) -> bool:
    """La (luogo, voce) e' di una voce nominata in un luogo nominato (tutti se
    ``None``)."""
    luogo, voce = chiave
    return voce in voci and (luoghi is None or luogo in luoghi)


class _Regole(NamedTuple):
    fissi: set[Decimal]
    #: Ampiezza del periodo (``Y - Y_confronto``): ammessa, mai cifra ISTAT senza ``%``.
    intervalli: set[Decimal]
    #: ``(codice, nome, nome breve)`` dei luoghi delle righe, in minuscolo.
    luoghi: list[tuple[str, str, str]]
    #: Contesto (senza domanda utente), blocco DATI ISTAT, lista fissa, periodo.
    ammessi: set[Decimal]
    #: Conteggi e tassi delle righe.
    figure: set[Decimal]
    #: Valori assoluti delle variazioni (cifre ISTAT solo col ``%``).
    variazioni: set[Decimal]
    tendenze: dict[_Chiave, set[int]]
    classi: dict[_Chiave, ConfrontoItalia | None]
    etichette: list[tuple[str, str]]
    #: ``(voce, etichetta del rischio collegato)``, per la C1.
    rischi: list[tuple[str, str]]
    #: "tasso", "voce", "dal <anno di confronto>": con una voce nominata fanno
    #: parlare del dato ISTAT una frase senza altri marcatori.
    marcatori: re.Pattern[str]


def _e_cifra_istat(n: Numero, regole: _Regole) -> bool:
    """``True`` se ``n`` e' una cifra ISTAT: conteggio/tasso sempre, variazione
    solo se scritta con ``%`` (ruling minore b). L'ampiezza del periodo senza ``%``
    non arriva qui: :func:`_valuta` la esclude prima (F2 della review finale)."""
    if n.valore in regole.figure:
        return True
    return n.percentuale and n.valore in regole.variazioni


def _marcatori(righe: Sequence[RigaIstat]) -> re.Pattern[str]:
    anni = "|".join(sorted({str(r.anno_confronto) for r in righe})) or r"\d{4}"
    # "tasso" in senso ISTAT (fix 4): seguito a breve da un confronto ("un tasso
    # piu' alto") o "tasso di/dei <voce>". "Area ad alto tasso di criminalita'"
    # (una vulnerabilita' dell'ontologia) non lo e'.
    tasso = rf"{_TASSO_PRIMA}(?:{_TUTTI_I_CONFRONTI})\b"
    etichette = sorted(
        {_normalizza(r.voce_label) for r in righe if r.voce != VOCE_TOTALE},
        key=lambda e: (-len(e), e),
    )
    if etichette:
        voci = "|".join(re.escape(e) for e in etichette)
        tasso += rf"|\btasso (?:di|del|dei|delle|degli) (?:{voci})\b"
    # "voce" in senso ISTAT: "la/questa voce", "voce piu' ampia/stretta", "voce ...
    # coincide/corrisponde"; non "dare voce al disagio". ("voce ISTAT" e' gia'
    # coperta dalla parola ISTAT.)
    voce = (
        r"\b(?:la|questa|quella) voce\b"
        rf"|\bvoce(?:{_SEP}\w+){{0,2}}?{_SEP}(?:ampi[ao]|strett[ao])\b"
        rf"|\bvoce(?:{_SEP}\w+){{0,4}}?{_SEP}(?:corrispond|coincid)\w*"
    )
    return re.compile(rf"{tasso}|{voce}|\bdal (?:{anni})\b")


def _parla_di_istat(
    testo: str, blocco: Blocco, cifre_istat: bool, voce_e_marcatore: bool
) -> bool:
    """``True`` se la frase si riferisce ai dati ISTAT (punto 4).

    La riga-etichetta ("Dati statistici ISTAT [ISTAT]") nomina ISTAT ma non dice
    nulla del dato. Una frase dentro un ``[ISTAT]`` residuo invece ne parla sempre
    (C3): il blocco esiste solo per quello. Ne parla anche una frase che nomina una
    voce delle righe (o un rischio collegato) insieme a "tasso", "voce" o "dal
    2014": "i furti hanno un tasso piu' alto e sono in calo dal 2014"."""
    if blocco == "intestazione":
        return False
    if blocco == "istat" or cifre_istat or voce_e_marcatore:
        return True
    return bool(_PARLA_DI_ISTAT.search(_normalizza(testo)))


def _verifica_direzione(
    direzione: Direzione, voci: set[str], luoghi: set[str] | None, regole: _Regole
) -> bool | None:
    """Coerenza della tendenza scritta per TUTTE le voci nominate (C-1); per una
    voce basta un luogo concorde (R6). ``None`` se una voce non ha tendenza
    calcolata nei luoghi: la frase non e' verificabile."""
    esiti: list[bool] = []
    for voce in voci:
        segni = [
            t
            for chiave, valori in regole.tendenze.items()
            if _nel_luogo(chiave, {voce}, luoghi)
            for t in valori
        ]
        if not segni:
            return None
        esiti.append(any(_coerente(direzione, t) for t in segni))
    return all(esiti) if esiti else None


def _verifica_confronto(
    confronto: Confronto, voci: set[str], luoghi: set[str] | None, regole: _Regole
) -> bool | None:
    """Coerenza del confronto scritto per TUTTE le voci nominate (C-1); per una
    voce basta un luogo concorde (R6). ``None`` se una voce non ha
    classificazione nei luoghi: la frase non e' verificabile."""
    esiti: list[bool] = []
    for voce in voci:
        classi = {
            c
            for chiave, c in regole.classi.items()
            if c is not None and _nel_luogo(chiave, {voce}, luoghi)
        }
        if not classi:
            return None
        esiti.append(confronto in classi)
    return all(esiti) if esiti else None


def _valuta(
    testo: str,
    blocco: Blocco,
    inizio: int,
    fine: int,
    regole: _Regole,
    luoghi_ereditati: set[str] | None = None,
) -> FraseControllata:
    numeri = estrai_numeri(testo, regole.ammessi)
    non_fissi = [
        n
        for n in numeri
        if n.valore not in regole.fissi
        and (n.percentuale or n.valore not in regole.intervalli)
    ]
    istat = [n for n in non_fissi if _e_cifra_istat(n, regole)]
    voci = voci_nominate(testo, regole.etichette)
    # C1: "il furto di beni ha un tasso piu' basso di quello italiano" nomina il
    # rischio, non la voce: la voce si risolve dai rischi collegati.
    voci_rischio: set[str] = set() if voci else voci_nominate(testo, regole.rischi)
    luoghi_espliciti = _luoghi_nominati(testo, regole.luoghi)
    marcatore = bool(regole.marcatori.search(_normalizza(testo)))
    direzione = direzione_di(testo)
    confronto = confronto_di(testo)
    # C-2: dentro un paragrafo che ha gia' nominato il luogo del dato, una voce con
    # una tendenza o un confronto ("- furti: in crescita;") parla del dato.
    if luoghi_ereditati is not None and (direzione or confronto):
        marcatore = True
    parla = _parla_di_istat(
        testo, blocco, bool(istat), bool(voci or voci_rischio) and marcatore
    )
    # Il luogo detto prima nello stesso paragrafo vale anche qui (fix 3): "I dati
    # ISTAT del Comune di Roma ...:" seguito da un elenco di voci.
    ereditato = parla and luoghi_espliciti is None and luoghi_ereditati is not None
    luoghi = luoghi_ereditati if ereditato else luoghi_espliciti
    if parla and (direzione or confronto) and not voci:
        voci = voci_rischio
        if not voci and _TOTALE_IMPLICITO.search(_normalizza(testo)):
            # "i delitti denunciati hanno un tasso piu' alto": senza un'altra voce
            # e' il totale.
            voci = {VOCE_TOTALE}
    # Tendenza e confronto si verificano solo nelle frasi che parlano del dato
    # ISTAT (R1): "a Roma la folla aumenta le occasioni di furti" parla del rischio.
    direzione_coerente = (
        _verifica_direzione(direzione, voci, luoghi, regole)
        if direzione and voci and parla
        else None
    )
    # "misto" non e' mai una classe della riga: risulta non coerente (B2).
    confronto_coerente = (
        _verifica_confronto(confronto, voci, luoghi, regole)
        if confronto and voci and parla
        else None
    )
    motivo: Motivo | None = None
    if any(n.valore not in regole.ammessi for n in numeri):
        motivo = "numero_non_ammesso"
    elif istat:
        motivo = "cifra_istat_fuori_blocco"
    elif parla and luoghi is None:
        motivo = "luogo_mancante"
    elif direzione and parla and not direzione_coerente:
        # ``None`` (nessuna voce, o voce senza tendenza calcolata) non e'
        # verificabile: si toglie comunque, con lo stesso motivo (ruling minore a).
        motivo = "direzione_contraria"
    elif confronto and parla and not confronto_coerente:
        # Idem per un confronto senza voce, su una voce senza classificazione o
        # con classi diverse nella stessa frase (#365 D3, B2, C1).
        motivo = "confronto_contrario"
    return FraseControllata(
        testo=testo,
        blocco=blocco,
        inizio=inizio,
        fine=fine,
        motivo=motivo,
        cifre=len(non_fissi),
        cifre_istat=len(istat),
        voci=tuple(sorted(voci)),
        parla_di_istat=parla,
        luogo=luoghi_espliciti is not None,
        luogo_ereditato=ereditato,
        luoghi=tuple(sorted(luoghi)) if luoghi else (),
        direzione=direzione,
        direzione_coerente=direzione_coerente,
        confronto=confronto,
        confronto_coerente=confronto_coerente,
    )


#: Fine paragrafo: una riga vuota fra due frasi.
_RIGA_VUOTA = re.compile(r"\n[ \t]*\n")


def _valuta_paragrafi(
    narrativa: str,
    spans: Sequence[tuple[int, int]],
    blocchi: Sequence[SpanBlocco],
    regole: _Regole,
) -> tuple[FraseControllata, ...]:
    """:func:`_valuta` frase per frase, col luogo ereditato (fix 3).

    Il luogo di una frase che parla del dato ISTAT e che il controllo TIENE vale
    per le frasi successive dello stesso paragrafo (elenco compreso); un nuovo
    luogo lo sostituisce. Niente eredita' oltre una riga vuota, a un cambio di
    blocco (la sintesi non passa il luogo a un blocco) ne' da una frase tolta.

    Eccezione (fix 6): una frase che passa il luogo e finisce con ":" introduce
    un elenco. Il luogo arriva alla prima voce anche oltre le righe vuote che la
    separano dall'introduzione, e vale per tutte le voci successive (righe che
    cominciano con -, *, • o "N."), anche separate da righe vuote. L'elenco
    finisce alla prima riga che non e' una voce: li' l'eredita' si ferma.
    """
    frasi: list[FraseControllata] = []
    ereditati: set[str] | None = None
    aspetta_elenco = False
    in_elenco = False
    blocco_prima: Blocco | None = None
    fine_prima = 0
    for a, b in spans:
        blocco = _blocco_di(a, blocchi)
        prefisso = narrativa[narrativa.rfind("\n", 0, a) + 1 : a]
        voce_elenco = bool(_MARCATORE_ELENCO.fullmatch(prefisso))
        a_capo = voce_elenco or not prefisso.strip()
        elenco = (aspetta_elenco or in_elenco) and voce_elenco
        if (
            blocco != blocco_prima
            or (in_elenco and a_capo and not voce_elenco)
            or (_RIGA_VUOTA.search(narrativa, fine_prima, a) and not elenco)
        ):
            ereditati, in_elenco = None, False
        elif elenco:
            in_elenco = True
        aspetta_elenco = False
        frase = _valuta(narrativa[a:b], blocco, a, b, regole, ereditati)
        if frase.motivo is None and frase.parla_di_istat and frase.luoghi:
            ereditati = set(frase.luoghi)
            if frase.testo.rstrip().endswith(":"):
                aspetta_elenco, in_elenco = True, False
        frasi.append(frase)
        blocco_prima, fine_prima = blocco, b
    return tuple(frasi)


def _senza(testo: str, tagli: Sequence[tuple[int, int]]) -> str:
    """``testo`` senza le frasi indicate; svuota le righe rimaste col solo marcatore."""
    if not tagli:
        return testo
    righe: list[str] = []
    pos = 0
    for riga in testo.split("\n"):
        fine_riga = pos + len(riga)
        locali = sorted((a - pos, b - pos) for a, b in tagli if pos <= a <= fine_riga)
        if not locali:
            righe.append(riga)
        else:
            pezzi: list[str] = []
            cursore = 0
            for a, b in locali:
                pezzi.append(riga[cursore:a])
                cursore = b
            pezzi.append(riga[cursore:])
            nuova = re.sub(r"[ \t]{2,}", " ", "".join(pezzi)).strip()
            # Resti di sola decorazione (":" fra un'etichetta tolta e la sua prosa
            # tolta) o del solo marcatore d'elenco non sono testo.
            if nuova.strip(_DOPO_TOKEN) and not _MARCATORE_ELENCO.fullmatch(
                nuova + " "
            ):
                righe.append(nuova)
        pos = fine_riga + 1
    return "\n".join(righe)


def _ripulisci(testo: str) -> str:
    """Niente righe vuote in testa, al massimo una riga vuota fra i paragrafi e in
    coda solo l'a-capo finale (C5): i tagli possono lasciare buchi."""
    pulito = re.sub(r"\n{3,}", "\n\n", testo).lstrip("\n")
    return pulito.rstrip("\n") + "\n" if pulito.endswith("\n") else pulito


def _etichette_orfane(
    frasi: Sequence[FraseControllata], blocchi: Sequence[SpanBlocco]
) -> list[tuple[int, int]]:
    """Righe-etichetta dei blocchi ``[ISTAT]`` residui le cui frasi sono tutte
    tolte (C5): restate da sole, annuncerebbero un blocco vuoto."""
    tagli: list[tuple[int, int]] = []
    for b in blocchi:
        if b.campo != "istat":
            continue
        corpo = [
            f for f in frasi if f.blocco == "istat" and b.inizio <= f.inizio < b.fine
        ]
        if corpo and all(f.motivo for f in corpo):
            tagli += [
                (f.inizio, f.fine)
                for f in frasi
                if f.blocco == "intestazione" and b.inizio_riga <= f.inizio < b.inizio
            ]
    return tagli


def _prosa_in_intestazione(
    narrativa: str, blocchi: Sequence[SpanBlocco]
) -> tuple[list[SpanBlocco], dict[int, int]]:
    """Blocchi con la prosa della riga-etichetta dentro il blocco (F7).

    Se dopo il token della riga-etichetta c'e' del testo, per il controllo delle
    cifre il blocco comincia da li' (non dalla riga dopo). Ritorna anche
    ``{fine del token: inizio della prosa}`` per spezzare la frase che
    :func:`dividi_frasi` farebbe a cavallo fra etichetta e prosa.
    """
    adattati: list[SpanBlocco] = []
    tagli: dict[int, int] = {}
    for b in blocchi:
        riga = narrativa[b.inizio_riga : b.inizio].rstrip("\n")
        token = _TOKEN_FONTE.search(riga)
        resto = riga[token.end() :] if token else ""
        if token is None or not resto.strip(_DOPO_TOKEN):
            adattati.append(b)
            continue
        fine_token = b.inizio_riga + token.end()
        prosa = fine_token + len(resto) - len(resto.lstrip(_DOPO_TOKEN))
        tagli[fine_token] = prosa
        adattati.append(b._replace(inizio=prosa))
    return adattati, tagli


def _frasi(narrativa: str, tagli: dict[int, int]) -> list[tuple[int, int]]:
    """:func:`dividi_frasi`, con l'etichetta separata dalla prosa che la segue."""
    spans: list[tuple[int, int]] = []
    for a, b in dividi_frasi(narrativa):
        taglio = next((t for t in tagli if a < t and tagli[t] < b), None)
        if taglio is None:
            spans.append((a, b))
        else:
            spans += [(a, taglio), (tagli[taglio], b)]
    return spans


def controlla_cifre(
    narrativa: str,
    *,
    blocchi: Sequence[SpanBlocco],
    blocco_istat: str,
    contesto_senza_istat: str,
    righe: Sequence[RigaIstat],
) -> EsitoControllo:
    """Verifica le cifre di ``narrativa`` contro il contesto inviato al modello."""
    fissi = {Decimal(100000), Decimal("0.1")}
    fissi |= {Decimal(r.anno) for r in righe} | {
        Decimal(r.anno_confronto) for r in righe
    }
    intervalli = {Decimal(r.anno - r.anno_confronto) for r in righe}
    # La domanda dell'utente e' input non fidato: i suoi numeri non sono ne'
    # ammessi ne' esclusi dalle cifre ISTAT (R2, review 2).
    nel_contesto = valori_del_testo(_DOMANDA_UTENTE.sub(" ", contesto_senza_istat))
    nel_blocco = valori_del_testo(blocco_istat)
    escluse = fissi | nel_contesto
    figure = _cifre_istat(righe, escluse)
    variazioni = _variazioni(righe, escluse)
    regole = _Regole(
        fissi=fissi,
        intervalli=intervalli,
        luoghi=_luoghi(righe),
        # Il blocco a parole (D7) non porta piu' le cifre: quelle delle righe sono
        # ammesse come numeri, cosi' una cifra ISTAT scritta dal modello si toglie
        # come tale e non come numero inventato.
        ammessi=fissi | intervalli | nel_contesto | nel_blocco | figure | variazioni,
        figure=figure,
        variazioni=variazioni,
        tendenze=_tendenze(righe),
        classi=_classi(righe),
        etichette=_etichette(righe),
        rischi=_rischi(righe),
        marcatori=_marcatori(righe),
    )
    blocchi, tagli = _prosa_in_intestazione(narrativa, blocchi)
    frasi = _valuta_paragrafi(narrativa, _frasi(narrativa, tagli), blocchi, regole)
    tolte = [(f.inizio, f.fine) for f in frasi if f.motivo]
    filtrato = (
        _ripulisci(_senza(narrativa, tolte + _etichette_orfane(frasi, blocchi)))
        if tolte
        else narrativa
    )
    return EsitoControllo(
        frasi=frasi,
        testo_filtrato=filtrato,
        testo_senza_frasi_istat=_senza(
            narrativa,
            [(f.inizio, f.fine) for f in frasi if f.parla_di_istat or f.cifre_istat],
        ),
        numeri_in_lettere=len(_IN_LETTERE.findall(narrativa.lower())),
        righe=tuple(righe),
        codici_voce=sum(
            len(re.findall(rf"\b{re.escape(codice)}\b", narrativa))
            for codice in {r.voce for r in righe}
        ),
    )


def applica_controllo(
    testo: str,
    *,
    blocco: BloccoIstat | None,
    spans: Sequence[SpanBlocco],
    contesto: str,
) -> tuple[str, EsitoControllo | None]:
    """Applica il controllo delle cifre a ``testo`` se il prompt portava ISTAT (#345).

    Helper CONDIVISO fra la narrativa di zona (``rag.generation.generate_analysis``)
    e quella per-POI (``rag.poi_generation``, stesso schema): incapsula la
    decisione "il prompt aveva il blocco DATI ISTAT?" insieme alla chiamata a
    :func:`controlla_cifre`, cosi' i due generation layer non duplicano la stessa
    logica (ruling P4 del controller: niente if-ISTAT inline in ``generate_analysis``).

    ``blocco`` e' quello EFFETTIVAMENTE finito nel prompt: puo' essere ``None``
    (il chiamante non ha nemmeno provato ad accendere ISTAT) o avere ``testo``
    vuoto (righe ISTAT richieste ma nessuna per i POI inclusi, #345 D-no-righe). In
    entrambi i casi il prompt non portava il blocco e il controllo non si applica:
    ``testo`` torna invariato e l'esito e' ``None`` — lo stesso ramo di "ISTAT
    spento". Altrimenti chiama :func:`controlla_cifre` e ritorna il testo filtrato
    (quello che vede l'operatore) insieme all':class:`EsitoControllo` completo, che
    il chiamante tiene in memoria per l'harness di valutazione.
    """
    if blocco is None or not blocco.testo:
        return testo, None
    controllo = controlla_cifre(
        testo,
        blocchi=spans,
        blocco_istat=blocco.testo,
        contesto_senza_istat=contesto,
        righe=blocco.righe,
    )
    return controllo.testo_filtrato, controllo
