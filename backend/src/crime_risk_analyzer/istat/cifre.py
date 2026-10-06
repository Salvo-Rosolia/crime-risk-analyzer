"""Controllo delle cifre della narrativa con i dati ISTAT nel prompt (#345, spec 4.7).

Meccanismo NUOVO: per la prima volta una frase generata puo' essere tolta dopo la
generazione. Gira solo quando il prompt conteneva il blocco DATI ISTAT.

1. Divisione in frasi che non spezza i numeri ("3.016", "1.162,7"): si spezza dopo
   ``.!?;`` seguiti da spazio e a ogni a-capo; i marcatori d'elenco a inizio riga
   ("1.", "-", "*") non fanno parte della frase. (``eval.metrics._sentences``
   spezza a ogni punto e non va riusata.)
2. Numeri normalizzati all'italiana: ``.`` seguito da gruppi di tre cifre e' il
   separatore delle migliaia (come lo spazio e lo spazio stretto), altrimenti e'
   decimale; ``,`` e' decimale; ``−`` vale ``-``; un ``-`` fra due cifre e' un
   intervallo ("2014-2024" sono due anni).
3. Ammessi: tutti i numeri dello user_content (blocco DATI ISTAT compreso) piu' la
   lista fissa (100.000, ``Y``, ``Y-10``, 0,1, i POI coinvolti). Cifre ISTAT:
   conteggi, tassi, tasso nazionale e variazioni delle righe, tranne quelli che
   compaiono anche nel contesto fuori dal blocco o nella lista fissa (non si puo'
   dire a cosa si riferiscano).
4. Regole, nell'ordine: numero non ammesso; cifra ISTAT fuori dal blocco
   ``[ISTAT]`` (il blocco ``[SPECULATIVO]`` non e' il blocco ISTAT: una cifra
   ISTAT li' dentro e' trattata come fuori blocco); nel blocco, ogni cifra ISTAT
   deve appartenere a una voce nominata nella stessa frase (etichetta o codice) e
   il segno esplicito di una variazione deve essere quello giusto; parole di
   direzione contrarie al segno della variazione della voce nominata.
5. I numeri in lettere ("il doppio") si contano per la valutazione, non si tolgono.

Il testo grezzo resta disponibile: l'esito porta il testo filtrato (cio' che vede
l'operatore) e quello senza le frasi con cifre ISTAT (per la metrica M1).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict

from crime_risk_analyzer.istat.dati import VOCE_TOTALE
from crime_risk_analyzer.istat.righe import RigaIstat

__all__ = [
    "Blocco",
    "EsitoControllo",
    "FraseControllata",
    "Motivo",
    "Numero",
    "SpanBlocco",
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
    r"(?P<segno>[+\-−])?"
    r"(?P<corpo>\d{1,3}(?:[.   ]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"
    r"(?!\w)"
    r"(?P<pct>\s?%)?"
)
_MIGLIAIA_CON_PUNTO = re.compile(r"\d{1,3}(?:\.\d{3})+")
_MARCATORE_ELENCO = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+")
_FINE_FRASE = re.compile(r"(?<=[.!?;])\s+")
_SU = re.compile(
    r"\b(?:aumento|aumenti|aumentat[oaie]|aumenta|aumentano|crescita|cresciut[oaie]"
    r"|cresce|crescono|incremento|incrementi|rialzo)\b"
)
_GIU = re.compile(
    r"\b(?:calo|cali|calat[oaie]|cala|calano|diminuzione|diminuzioni|diminuit[oaie]"
    r"|diminuisce|diminuiscono|riduzione|ridott[oaie]|flessione|discesa|ribasso)\b"
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
    pulito = corpo.replace(" ", "").replace(" ", "").replace(" ", "")
    if "," in pulito:
        intera, decimali = pulito.split(",", 1)
        return Decimal(f"{intera.replace('.', '')}.{decimali}")
    if _MIGLIAIA_CON_PUNTO.fullmatch(pulito):
        return Decimal(pulito.replace(".", ""))
    return Decimal(pulito)


def estrai_numeri(testo: str) -> list[Numero]:
    """Numeri di una frase o di una riga (il marcatore d'elenco iniziale non conta)."""
    testo = _MARCATORE_ELENCO.sub("", testo, count=1)
    numeri: list[Numero] = []
    for m in _NUMERO.finditer(testo):
        segno = (m.group("segno") or "").replace("−", "-")
        numeri.append(
            Numero(_valore(m.group("corpo")), segno, m.group("pct") is not None)
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


def _figure(
    righe: Sequence[RigaIstat], escluse: set[Decimal]
) -> dict[Decimal, set[str]]:
    figure: dict[Decimal, set[str]] = {}
    for r in righe:
        valori: list[float | int] = [
            v
            for v in (r.delitti, r.delitti_confronto, r.tasso, r.tasso_italia)
            if v is not None
        ]
        if r.variazione_pct is not None:
            valori.append(abs(r.variazione_pct))
        for v in valori:
            d = Decimal(str(v))
            if d not in escluse:
                figure.setdefault(d, set()).add(r.voce)
    return figure


def _tendenze(righe: Sequence[RigaIstat]) -> dict[str, set[int]]:
    tendenze: dict[str, set[int]] = {}
    for r in righe:
        if r.variazione_pct is not None:
            tendenze.setdefault(r.voce, set()).add(r.variazione_pct)
    return tendenze


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


def _segno_coerente(n: Numero, voci: set[str], tendenze: dict[str, set[int]]) -> bool:
    if not n.segno:
        return True
    candidate = [t for v in voci for t in tendenze.get(v, set()) if abs(t) == n.valore]
    if not candidate:
        return True
    return any(t == 0 or (t > 0) == (n.segno == "+") for t in candidate)


class _Regole(NamedTuple):
    fissi: set[Decimal]
    ammessi: set[Decimal]
    figure: dict[Decimal, set[str]]
    tendenze: dict[str, set[int]]
    etichette: list[tuple[str, str]]


def _valuta(
    testo: str, blocco: Blocco, inizio: int, fine: int, regole: _Regole
) -> FraseControllata:
    numeri = estrai_numeri(testo)
    non_fissi = [n for n in numeri if n.valore not in regole.fissi]
    istat = [n for n in non_fissi if n.valore in regole.figure]
    voci = voci_nominate(testo, regole.etichette)
    direzione = direzione_di(testo) if blocco == "istat" else ""
    motivo: Motivo | None = None
    corrette = 0
    if any(n.valore not in regole.ammessi for n in numeri):
        motivo = "numero_non_ammesso"
    elif istat and blocco != "istat":
        motivo = "cifra_istat_fuori_blocco"
    elif istat:
        if not voci:
            motivo = "voce_mancante"
        elif any(not (regole.figure[n.valore] & voci) for n in istat):
            motivo = "voce_errata"
        elif any(not _segno_coerente(n, voci, regole.tendenze) for n in istat):
            motivo = "segno_errato"
        else:
            corrette = len(istat)
    coerente: bool | None = None
    if direzione:
        segni = [t for v in voci for t in regole.tendenze.get(v, set())]
        if segni:
            coerente = any(_coerente(direzione, t) for t in segni)
            if not coerente and motivo is None:
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
    nel_contesto = valori_del_testo(contesto_senza_istat)
    regole = _Regole(
        fissi=fissi,
        ammessi=fissi | nel_contesto | valori_del_testo(blocco_istat),
        figure=_figure(righe, fissi | nel_contesto),
        tendenze=_tendenze(righe),
        etichette=_etichette(righe),
    )
    frasi = tuple(
        _valuta(narrativa[a:b], _blocco_di(a, blocchi), a, b, regole)
        for a, b in dividi_frasi(narrativa)
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
