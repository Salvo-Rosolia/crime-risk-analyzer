"""Controllo delle cifre della narrativa con i dati ISTAT nel prompt (#345, spec 4.7).

Meccanismo NUOVO: per la prima volta una frase generata puo' essere tolta dopo la
generazione. Gira solo quando il prompt conteneva il blocco DATI ISTAT.

1. Divisione in frasi che non spezza i numeri ("3.016", "1.162,7"): si spezza dopo
   ``.!?`` seguiti da spazio e a ogni a-capo; il ``;`` NON chiude la frase (la
   citazione "(fonte ISTAT, ...); variazione 2014-2024: -10%" resta una frase sola,
   con la voce che la regge); i marcatori d'elenco a inizio riga ("1.", "-", "*")
   non fanno parte della frase. (``eval.metrics._sentences`` spezza a ogni punto e
   non va riusata.) La prosa scritta sulla stessa riga dell'etichetta, dopo il
   token (``Dati statistici ISTAT [ISTAT]: nel Comune ...``), appartiene al blocco
   che l'etichetta apre: solo il controllo delle cifre la sposta, il parser dei
   blocchi (che alimenta M1) resta com'e'. Le abbreviazioni comuni (``d.lgs.``,
   ``art.``, ``n.``, ``es.``, ``ecc.``, ``cfr.``) non chiudono la frase: le righe
   DATI ISTAT stesse scrivono "(d.lgs. 7/2016)" (R4, review 2).
2. Numeri normalizzati all'italiana: ``.`` seguito da gruppi di tre cifre e' il
   separatore delle migliaia (come l'NBSP e lo spazio stretto NNBSP), altrimenti
   e' decimale; ``,`` e' decimale; ``−`` e ``–`` (trattino medio) valgono ``-``;
   un ``-`` (o ``–``) fra due cifre e' un intervallo ("2014-2024" sono due anni,
   non un segno); "per cento"/"percento" dopo un numero vale ``%``. Lo spazio
   normale vale come separatore delle migliaia solo se il numero unito e' ammesso
   o se le sue parti non lo sono tutte: "134 169" resta 134.169, ma "negli ultimi
   10 340 furti" sono 10 e 340 (R8, review 2). Un riferimento ``N/AAAA``
   ("d.lgs. 7/2016") non e' un numero da controllare.
3. Ammessi: fuori dal blocco ``[ISTAT]``, tutti i numeri dello user_content
   (blocco DATI ISTAT compreso) TRANNE quelli della domanda dell'utente (input non
   fidato: non deve mai mettere in lista una cifra, R2 review 2); dentro
   ``[ISTAT]`` solo i numeri del blocco DATI ISTAT (i numeri che stanno solo nel
   resto del contesto — POI totali, nomi dei POI e dei vicini — li' non sono
   ammessi). In entrambi i casi piu' la
   lista fissa (100.000, ``Y``, ``Y-10``, 0,1, i POI coinvolti) e l'ampiezza del
   periodo ``Y - Y_confronto`` ("negli ultimi 10 anni"), che senza ``%`` e' un
   numero qualunque e mai una cifra ISTAT. Cifre ISTAT:
   conteggi, tassi, tasso nazionale delle righe, piu' le variazioni ma SOLO quando
   scritte con ``%`` (un numero senza ``%`` puo' coincidere per caso col valore
   assoluto di una variazione — es. "10" in "negli ultimi 10 anni" — e non va
   scambiato per una cifra ISTAT); in ogni caso tranne quelli che compaiono anche
   nel contesto fuori dal blocco o nella lista fissa (non si puo' dire a cosa si
   riferiscano).
4. Regole, nell'ordine: numero non ammesso; cifra ISTAT fuori dal blocco
   ``[ISTAT]`` (il blocco ``[SPECULATIVO]`` non e' il blocco ISTAT: una cifra
   ISTAT li' dentro e' trattata come fuori blocco); nel blocco, ogni cifra ISTAT
   deve appartenere a una voce nominata nella stessa frase (etichetta o codice) e
   il segno esplicito di una variazione deve essere quello giusto; parole di
   direzione contrarie al segno della variazione della voce nominata — dentro
   ``[ISTAT]`` sempre; fuori (overview, ``[ONTOLOGIA]``/``[CONTESTO]``/
   ``[SPECULATIVO]``) solo quando la frase si riferisce ESPLICITAMENTE ai dati
   ISTAT: nomina "ISTAT" o i "delitti denunciati", o contiene una cifra ISTAT. Il
   solo nome del luogo non basta (R1, review 2): "A Roma la folla aumenta le
   occasioni di furti" in ``[ONTOLOGIA]`` parla del rischio, non della statistica,
   e resta. Le parole di direzione sono solo di tendenza ("in aumento",
   "aumentati", "in calo", "scesi"...): forme causali o aggettivali ("aumenta le
   occasioni", "ridotta", "riduzione", le "sale" giochi) non contano. Se la frase
   nomina un luogo delle righe (per esteso, "Comune di Roma", o per nome breve),
   attribuzione, segno e direzione usano i valori di QUEL luogo per la voce; se
   non ne nomina nessuno valgono quelli della voce in qualunque luogo (R6, review
   2). Se la voce nominata non ha
   nessuna tendenza calcolata (serie interrotta, anno mancante, sotto soglia), una
   parola di direzione su di essa non e' verificabile e la frase si toglie lo
   stesso, con lo stesso motivo ``direzione_contraria`` (scelta di
   implementazione: non si introduce un settimo motivo solo per questo caso).
5. I numeri in lettere ("il doppio") si contano per la valutazione, non si tolgono.

Il testo grezzo resta disponibile: l'esito porta il testo filtrato (cio' che vede
l'operatore) e quello senza le frasi con cifre ISTAT (per la metrica M1).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict

from crime_risk_analyzer.istat.blocco import BloccoIstat
from crime_risk_analyzer.istat.dati import VOCE_TOTALE
from crime_risk_analyzer.istat.righe import RigaIstat

__all__ = [
    "Blocco",
    "EsitoControllo",
    "FraseControllata",
    "Motivo",
    "Numero",
    "SpanBlocco",
    "applica_controllo",
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
    "voce_mancante",
    "voce_errata",
    "segno_errato",
    "direzione_contraria",
]
Direzione = Literal["su", "giu", ""]

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
    r"(?P<corpo>\d{1,3}(?:[.\xa0\u202f ]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"
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
    r"|scende|scendono|sces[oaie])\b"
)
_IN_LETTERE = re.compile(
    r"\b(?:mille|duemila|tremila|quattromila|cinquemila|diecimila|centomila"
    r"|milion[ei]|miliard[oi]|doppio|triplo|met[aà]|raddoppiat\w*|triplicat\w*"
    r"|dimezzat\w*)\b"
)
_POI_COINVOLTI = re.compile(r"POI coinvolti: (\d+)")
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
    cifre_istat: int = 0
    #: Cifre ISTAT nel blocco giusto, attribuite alla voce giusta, col segno giusto.
    cifre_istat_corrette: int = 0
    voci: tuple[str, ...] = ()
    #: Voci nominate a cui appartiene almeno una delle cifre ISTAT corrette (R7).
    voci_cifre: tuple[str, ...] = ()
    direzione: Direzione = ""
    #: ``None`` se la frase non usa parole di direzione su una voce con variazione.
    direzione_coerente: bool | None = None


class EsitoControllo(BaseModel):
    """Esito del controllo su una narrativa."""

    model_config = ConfigDict(frozen=True)

    frasi: tuple[FraseControllata, ...]
    testo_filtrato: str
    testo_senza_cifre_istat: str
    numeri_in_lettere: int
    righe: tuple[RigaIstat, ...]

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


#: Una cifra o una tendenza appartiene a una voce IN un luogo (R6, review 2).
_Chiave = tuple[str, str]


def _figure(
    righe: Sequence[RigaIstat], escluse: set[Decimal]
) -> dict[Decimal, set[_Chiave]]:
    """Conteggi e tassi delle righe: cifre ISTAT sempre, col ``%`` o senza."""
    figure: dict[Decimal, set[_Chiave]] = {}
    for r in righe:
        valori: list[float | int] = [
            v
            for v in (r.delitti, r.delitti_confronto, r.tasso, r.tasso_italia)
            if v is not None
        ]
        for v in valori:
            d = Decimal(str(v))
            if d not in escluse:
                figure.setdefault(d, set()).add((r.luogo_codice, r.voce))
    return figure


def _variazioni(
    righe: Sequence[RigaIstat], escluse: set[Decimal]
) -> dict[Decimal, set[_Chiave]]:
    """Valore assoluto delle variazioni: cifra ISTAT solo se scritto con ``%``
    (altrimenti un numero come "10" in "negli ultimi 10 anni" non e' una cifra
    ISTAT solo perche' coincide col valore assoluto di una variazione)."""
    variazioni: dict[Decimal, set[_Chiave]] = {}
    for r in righe:
        if r.variazione_pct is not None:
            d = Decimal(str(abs(r.variazione_pct)))
            if d not in escluse:
                variazioni.setdefault(d, set()).add((r.luogo_codice, r.voce))
    return variazioni


def _tendenze(righe: Sequence[RigaIstat]) -> dict[_Chiave, set[int]]:
    tendenze: dict[_Chiave, set[int]] = {}
    for r in righe:
        if r.variazione_pct is not None:
            tendenze.setdefault((r.luogo_codice, r.voce), set()).add(r.variazione_pct)
    return tendenze


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


def voci_nominate(testo: str, etichette: Sequence[tuple[str, str]]) -> set[str]:
    """Voci nominate in ``testo`` per etichetta (esatta) o per codice ISTAT."""
    trovate: set[str] = set()
    resto = testo.lower()
    for voce, etichetta in etichette:
        modello = re.compile(rf"\b{re.escape(etichetta)}\b")
        if modello.search(resto):
            trovate.add(voce)
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
    resto = testo.lower()
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
    """``su``/``giu`` se la frase ha parole di una sola direzione, altrimenti ``""``."""
    minuscolo = testo.lower()
    su = bool(_SU.search(minuscolo))
    giu = bool(_GIU.search(minuscolo))
    if su == giu:
        return ""
    return "su" if su else "giu"


def _coerente(direzione: Direzione, tendenza: int) -> bool:
    return tendenza > 0 if direzione == "su" else tendenza < 0


def _nel_luogo(chiavi: Iterable[_Chiave], luoghi: set[str] | None) -> set[str]:
    """Voci delle ``chiavi`` nei ``luoghi`` nominati (tutti se ``None``)."""
    return {voce for luogo, voce in chiavi if luoghi is None or luogo in luoghi}


def _segni(
    voci: set[str], luoghi: set[str] | None, tendenze: dict[_Chiave, set[int]]
) -> list[int]:
    """Tendenze delle ``voci`` nei ``luoghi`` nominati (tutti se ``None``)."""
    return [
        t
        for (luogo, voce), valori in tendenze.items()
        if voce in voci and (luoghi is None or luogo in luoghi)
        for t in valori
    ]


def _segno_coerente(
    n: Numero,
    voci: set[str],
    luoghi: set[str] | None,
    tendenze: dict[_Chiave, set[int]],
) -> bool:
    if not n.segno:
        return True
    candidate = [t for t in _segni(voci, luoghi, tendenze) if abs(t) == n.valore]
    if not candidate:
        return True
    return any(t == 0 or (t > 0) == (n.segno == "+") for t in candidate)


class _Regole(NamedTuple):
    fissi: set[Decimal]
    #: Ampiezza del periodo (``Y - Y_confronto``): ammessa, mai cifra ISTAT senza ``%``.
    intervalli: set[Decimal]
    #: ``(codice, nome, nome breve)`` dei luoghi delle righe, in minuscolo.
    luoghi: list[tuple[str, str, str]]
    #: Ammessi fuori da ``[ISTAT]``: contesto (senza domanda utente) e blocco.
    ammessi: set[Decimal]
    #: Ammessi dentro ``[ISTAT]``: solo il blocco DATI ISTAT e la lista fissa (R2).
    ammessi_istat: set[Decimal]
    figure: dict[Decimal, set[_Chiave]]
    variazioni: dict[Decimal, set[_Chiave]]
    tendenze: dict[_Chiave, set[int]]
    etichette: list[tuple[str, str]]


def _e_cifra_istat(n: Numero, regole: _Regole) -> bool:
    """``True`` se ``n`` e' una cifra ISTAT: conteggio/tasso sempre, variazione
    solo se scritta con ``%`` (ruling minore b). L'ampiezza del periodo senza ``%``
    non e' mai una cifra ISTAT (F2 della review finale)."""
    if not n.percentuale and n.valore in regole.intervalli:
        return False
    if n.valore in regole.figure:
        return True
    return n.percentuale and n.valore in regole.variazioni


def _voci_di(n: Numero, regole: _Regole, luoghi: set[str] | None) -> set[str]:
    """Voci a cui ``n`` puo' riferirsi nei ``luoghi`` nominati (conteggi/tassi
    sempre, variazioni solo se ``n`` e' scritto con ``%``)."""
    voci = _nel_luogo(regole.figure.get(n.valore, ()), luoghi)
    if n.percentuale:
        voci |= _nel_luogo(regole.variazioni.get(n.valore, ()), luoghi)
    return voci


def _parla_di_istat(testo: str, cifre_istat: bool) -> bool:
    """``True`` se la frase si riferisce esplicitamente ai dati ISTAT (F5 della
    review finale, ristretto da R1 della review 2: il solo nome del luogo non
    basta)."""
    if cifre_istat:
        return True
    minuscolo = testo.lower()
    return "istat" in minuscolo or "delitti denunciati" in minuscolo


def _valuta(
    testo: str, blocco: Blocco, inizio: int, fine: int, regole: _Regole
) -> FraseControllata:
    ammessi = regole.ammessi_istat if blocco == "istat" else regole.ammessi
    numeri = estrai_numeri(testo, ammessi)
    non_fissi = [
        n
        for n in numeri
        if n.valore not in regole.fissi
        and (n.percentuale or n.valore not in regole.intervalli)
    ]
    istat = [n for n in non_fissi if _e_cifra_istat(n, regole)]
    voci = voci_nominate(testo, regole.etichette)
    luoghi = _luoghi_nominati(testo, regole.luoghi)
    # Il controllo di direzione vale in [ISTAT] e, fuori, nelle frasi che si
    # riferiscono esplicitamente ai dati ISTAT (F5, ristretto da R1 della review
    # 2): "a Roma la folla aumenta le occasioni di furti" parla del rischio.
    direzione = direzione_di(testo)
    verifica = blocco == "istat" or _parla_di_istat(testo, bool(istat))
    motivo: Motivo | None = None
    corrette = 0
    voci_cifre: set[str] = set()
    if any(n.valore not in ammessi for n in numeri):
        motivo = "numero_non_ammesso"
    elif istat and blocco != "istat":
        motivo = "cifra_istat_fuori_blocco"
    elif istat:
        if not voci:
            motivo = "voce_mancante"
        elif any(not (_voci_di(n, regole, luoghi) & voci) for n in istat):
            motivo = "voce_errata"
        elif any(not _segno_coerente(n, voci, luoghi, regole.tendenze) for n in istat):
            motivo = "segno_errato"
        else:
            corrette = len(istat)
            voci_cifre = {v for n in istat for v in _voci_di(n, regole, luoghi) & voci}
    coerente: bool | None = None
    if direzione and voci and verifica:
        segni = _segni(voci, luoghi, regole.tendenze)
        if segni:
            coerente = any(_coerente(direzione, t) for t in segni)
            if not coerente and motivo is None:
                motivo = "direzione_contraria"
        elif motivo is None:
            # Voce nominata con una parola di direzione ma senza tendenza
            # calcolata (serie interrotta, anno mancante, sotto soglia), o senza
            # tendenza nel luogo nominato: non si puo' verificare la direzione,
            # quindi la frase si toglie comunque (ruling minore a).
            # ``direzione_coerente`` resta ``None`` perche' non c'e' una
            # tendenza con cui confrontarsi.
            motivo = "direzione_contraria"
    return FraseControllata(
        testo=testo,
        blocco=blocco,
        inizio=inizio,
        fine=fine,
        motivo=motivo,
        cifre=len(non_fissi),
        cifre_istat=len(istat),
        cifre_istat_corrette=corrette,
        voci=tuple(sorted(voci)),
        voci_cifre=tuple(sorted(voci_cifre)),
        direzione=direzione,
        direzione_coerente=coerente,
    )


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
            if nuova and not _MARCATORE_ELENCO.fullmatch(nuova + " "):
                righe.append(nuova)
        pos = fine_riga + 1
    return "\n".join(righe)


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
    fissi |= {Decimal(n) for n in _POI_COINVOLTI.findall(blocco_istat)}
    intervalli = {Decimal(r.anno - r.anno_confronto) for r in righe}
    # La domanda dell'utente e' input non fidato: i suoi numeri non sono ne'
    # ammessi ne' esclusi dalle cifre ISTAT (R2, review 2).
    nel_contesto = valori_del_testo(_DOMANDA_UTENTE.sub(" ", contesto_senza_istat))
    nel_blocco = valori_del_testo(blocco_istat)
    escluse = fissi | nel_contesto
    regole = _Regole(
        fissi=fissi,
        intervalli=intervalli,
        luoghi=_luoghi(righe),
        ammessi=fissi | intervalli | nel_contesto | nel_blocco,
        ammessi_istat=fissi | intervalli | nel_blocco,
        figure=_figure(righe, escluse),
        variazioni=_variazioni(righe, escluse),
        tendenze=_tendenze(righe),
        etichette=_etichette(righe),
    )
    blocchi, tagli = _prosa_in_intestazione(narrativa, blocchi)
    frasi = tuple(
        _valuta(narrativa[a:b], _blocco_di(a, blocchi), a, b, regole)
        for a, b in _frasi(narrativa, tagli)
    )
    return EsitoControllo(
        frasi=frasi,
        testo_filtrato=_senza(
            narrativa, [(f.inizio, f.fine) for f in frasi if f.motivo]
        ),
        testo_senza_cifre_istat=_senza(
            narrativa, [(f.inizio, f.fine) for f in frasi if f.cifre_istat]
        ),
        numeri_in_lettere=len(_IN_LETTERE.findall(narrativa.lower())),
        righe=tuple(righe),
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
