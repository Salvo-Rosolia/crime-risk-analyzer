"""Righe ISTAT di un POI e loro formato nel prompt (#345, spec 4.4).

Per ogni (luogo, voce) una funzione PURA produce valori di ``Y`` e ``Y-10``, tasso
nazionale e variazione decennale. La variazione e' intera e calcolata sui CONTEGGI
(non sul tasso arrotondato); non si calcola se un conteggio e' sotto
:data:`SOGLIA_TENDENZA`, se manca un anno o se la voce e' toccata dalla
depenalizzazione del 2016: la riga dice il motivo.

Nel prompt la riga e' a parole (#365 D7, :func:`formatta_riga`): confronto col
tasso italiano gia' classificato (:func:`confronto_italia`) e tendenza, senza
cifre ne' codici. Le cifre restano nella :class:`RigaIstat`: il controllo delle
frasi (:mod:`~crime_risk_analyzer.istat.cifre`) le riconosce e verifica il
confronto con la STESSA funzione, l'interfaccia le mostra.

Nomi del luogo e della voce vengono da etichette fisse (dati e mappatura): nessun
testo da fonti esterne non fidate entra nelle righe.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from crime_risk_analyzer.i18n.terminus_labels import label_it
from crime_risk_analyzer.istat.catalogo import VOCI_ROTTURA_2016
from crime_risk_analyzer.istat.dati import (
    CODICE_ITALIA,
    VOCE_TOTALE,
    DatiIstat,
    Luogo,
    TipoLuogo,
    dati_istat_o_none,
)
from crime_risk_analyzer.istat.luoghi import luogo_di
from crime_risk_analyzer.istat.mappatura import MAPPATURA, Corrispondenza

__all__ = [
    "MOTIVO_ANNO_MANCANTE",
    "MOTIVO_ROTTURA_2016",
    "MOTIVO_SOTTO_SOGLIA",
    "SOGLIA_PIU_ALTO",
    "SOGLIA_PIU_BASSO",
    "SOGLIA_TENDENZA",
    "Collegamento",
    "ConfrontoItalia",
    "IstatPoi",
    "RigaIstat",
    "confronto_italia",
    "formatta_riga",
    "istat_per_poi",
    "riga_istat",
    "variazione",
]

#: Sotto questo numero di delitti in uno dei due anni la variazione non si calcola:
#: su conteggi piccoli una percentuale amplifica il rumore (spec 4.4).
SOGLIA_TENDENZA = 20
MOTIVO_ROTTURA_2016 = "serie interrotta dalla depenalizzazione del 2016 (d.lgs. 7/2016)"
MOTIVO_ANNO_MANCANTE = "dato mancante in uno dei due anni"
MOTIVO_SOTTO_SOGLIA = f"meno di {SOGLIA_TENDENZA} delitti in uno dei due anni"

#: Confronto del tasso del luogo con quello italiano (#365 D2): rapporto
#: ``tasso / tasso_italia`` almeno 1,10 = piu' alto, al massimo 0,90 = piu' basso,
#: in mezzo = simile.
ConfrontoItalia = Literal["piu_alto", "piu_basso", "simile"]
SOGLIA_PIU_ALTO = Decimal("1.10")
SOGLIA_PIU_BASSO = Decimal("0.90")
_DICITURA_CONFRONTO: dict[ConfrontoItalia, str] = {
    "piu_alto": "tasso più alto di quello italiano",
    "piu_basso": "tasso più basso di quello italiano",
    "simile": "tasso simile a quello italiano",
}

_DICITURA: dict[Corrispondenza, str] = {
    "esatta": "corrispondenza esatta",
    "piu_larga": "voce più ampia del rischio",
    "piu_stretta": "voce che copre solo una parte del rischio",
}
_ORDINE_CORRISPONDENZE: tuple[Corrispondenza, ...] = (
    "esatta",
    "piu_larga",
    "piu_stretta",
)


class Collegamento(BaseModel):
    """Un hazard del POI collegato alla voce, con la sua corrispondenza (D3)."""

    model_config = ConfigDict(frozen=True)

    hazard: str
    hazard_label_it: str
    corrispondenza: Corrispondenza


class RigaIstat(BaseModel):
    """Valori di una voce (o del totale) in un luogo, gia' calcolati."""

    model_config = ConfigDict(frozen=True)

    luogo_codice: str
    luogo_nome: str
    luogo_breve: str
    luogo_tipo: TipoLuogo
    voce: str
    voce_label: str
    anno: int
    anno_confronto: int
    delitti: int | None
    delitti_confronto: int | None
    tasso: float | None
    tasso_sotto_soglia: bool = False
    tasso_italia: float | None
    tasso_italia_sotto_soglia: bool = False
    variazione_pct: int | None
    motivo_senza_variazione: str | None = None
    rottura_2016: bool = False
    collegamenti: tuple[Collegamento, ...] = ()


class IstatPoi(BaseModel):
    """Dati ISTAT di un POI: cornice del luogo (D10) e voci collegate ai suoi rischi."""

    model_config = ConfigDict(frozen=True)

    cornice: RigaIstat
    righe: tuple[RigaIstat, ...]


def variazione(
    delitti: int | None, delitti_confronto: int | None, *, rottura_2016: bool
) -> tuple[int | None, str | None]:
    """Variazione % intera ``Y-10 -> Y`` sui conteggi, o ``(None, motivo)``."""
    if rottura_2016:
        return None, MOTIVO_ROTTURA_2016
    if delitti is None or delitti_confronto is None:
        return None, MOTIVO_ANNO_MANCANTE
    if delitti < SOGLIA_TENDENZA or delitti_confronto < SOGLIA_TENDENZA:
        return None, MOTIVO_SOTTO_SOGLIA
    pct = Decimal(delitti - delitti_confronto) * 100 / Decimal(delitti_confronto)
    return int(pct.quantize(Decimal(1), rounding=ROUND_HALF_UP)), None


def riga_istat(
    dati: DatiIstat,
    luogo: Luogo,
    voce: str,
    *,
    collegamenti: tuple[Collegamento, ...] = (),
) -> RigaIstat:
    """Riga di ``voce`` (o del totale) nel ``luogo``."""
    file = dati.delitti
    attuale = file.valore(luogo.codice, voce, file.anno)
    passato = file.valore(luogo.codice, voce, file.anno_confronto)
    italia = file.valore(CODICE_ITALIA, voce, file.anno)
    rottura = voce in VOCI_ROTTURA_2016
    pct, motivo = variazione(
        attuale.delitti if attuale else None,
        passato.delitti if passato else None,
        rottura_2016=rottura,
    )
    return RigaIstat(
        luogo_codice=luogo.codice,
        luogo_nome=luogo.nome,
        luogo_breve=luogo.nome_breve,
        luogo_tipo=luogo.tipo,
        voce=voce,
        voce_label=file.voci.get(voce, voce),
        anno=file.anno,
        anno_confronto=file.anno_confronto,
        delitti=attuale.delitti if attuale else None,
        delitti_confronto=passato.delitti if passato else None,
        tasso=attuale.tasso if attuale else None,
        tasso_sotto_soglia=attuale.tasso_sotto_soglia if attuale else False,
        tasso_italia=italia.tasso if italia else None,
        tasso_italia_sotto_soglia=italia.tasso_sotto_soglia if italia else False,
        variazione_pct=pct,
        motivo_senza_variazione=motivo,
        rottura_2016=rottura,
        collegamenti=collegamenti,
    )


def istat_per_poi(
    lat: float, lon: float, hazards: Iterable[str], *, dati: DatiIstat | None = None
) -> IstatPoi | None:
    """Cornice e voci del luogo del POI collegate ai suoi hazard; ``None`` se nessuna.

    ``None`` anche fuori da ogni poligono o senza dati: la cornice da sola non entra
    nel prompt (decisione del piano: il totale e' contesto delle voci, non un dato
    a se').
    """
    sorgente = dati if dati is not None else dati_istat_o_none()
    if sorgente is None:
        return None
    luogo = luogo_di(lat, lon, dati=sorgente)
    if luogo is None:
        return None
    per_voce: dict[str, list[Collegamento]] = {}
    for hazard in dict.fromkeys(hazards):
        mappatura = MAPPATURA.get(hazard)
        if mappatura is None or mappatura.voce_istat is None:
            continue
        # Invariante garantita dai test del Task 2: voce_istat None <=> corrispondenza
        # None, quindi qui corrispondenza e' sempre valorizzata.
        assert mappatura.corrispondenza is not None
        per_voce.setdefault(mappatura.voce_istat, []).append(
            Collegamento(
                hazard=hazard,
                hazard_label_it=label_it(hazard),
                corrispondenza=mappatura.corrispondenza,
            )
        )
    if not per_voce:
        return None
    return IstatPoi(
        cornice=riga_istat(sorgente, luogo, VOCE_TOTALE),
        righe=tuple(
            riga_istat(sorgente, luogo, voce, collegamenti=tuple(collegamenti))
            for voce, collegamenti in sorted(per_voce.items())
        ),
    )


def _tasso_confrontabile(valore: float | None, sotto_soglia: bool) -> Decimal | None:
    """Tasso esatto (da ``str``: niente errori di virgola mobile ai bordi); il
    "meno di 0,1" vale 0, un tasso assente ``None``."""
    if valore is not None:
        return Decimal(str(valore))
    return Decimal(0) if sotto_soglia else None


def confronto_italia(riga: RigaIstat) -> ConfrontoItalia | None:
    """Tasso del luogo rispetto a quello italiano (#365 D2), ``None`` se non si puo'
    dire: un tasso mancante o il nazionale a 0. Vale anche per il totale dei
    delitti (la sua riga lo scrive, D7).

    Unica classificazione del progetto: la usa il blocco DATI ISTAT
    (:func:`formatta_riga`) e il controllo delle frasi la riusa per verificare le
    parole di confronto della narrativa.
    """
    tasso = _tasso_confrontabile(riga.tasso, riga.tasso_sotto_soglia)
    italia = _tasso_confrontabile(riga.tasso_italia, riga.tasso_italia_sotto_soglia)
    if tasso is None or italia is None or italia == 0:
        return None
    rapporto = tasso / italia
    if rapporto >= SOGLIA_PIU_ALTO:
        return "piu_alto"
    if rapporto <= SOGLIA_PIU_BASSO:
        return "piu_basso"
    return "simile"


def _confronto(riga: RigaIstat) -> str:
    classe = confronto_italia(riga)
    if classe is None:
        return "confronto con il tasso italiano non disponibile"
    return _DICITURA_CONFRONTO[classe]


def _tendenza(riga: RigaIstat) -> str:
    """Tendenza a parole (#365 D7): il segno della variazione, mai il valore."""
    if riga.variazione_pct is None:
        motivo = riga.motivo_senza_variazione
        return (
            f"tendenza non calcolata: {motivo}"
            if motivo
            else ("tendenza non calcolata")
        )
    if riga.variazione_pct > 0:
        return f"in crescita dal {riga.anno_confronto}"
    if riga.variazione_pct < 0:
        return f"in calo dal {riga.anno_confronto}"
    return f"stabile dal {riga.anno_confronto}"


def _collegamenti(collegamenti: tuple[Collegamento, ...]) -> str:
    gruppi: list[str] = []
    for corrispondenza in _ORDINE_CORRISPONDENZE:
        etichette = sorted(
            {
                c.hazard_label_it
                for c in collegamenti
                if c.corrispondenza == corrispondenza
            }
        )
        if etichette:
            gruppi.append(f"{', '.join(etichette)} ({_DICITURA[corrispondenza]})")
    return "; ".join(gruppi)


def formatta_riga(riga: RigaIstat) -> str:
    """Riga del blocco DATI ISTAT, a parole (#365 D7).

    Luogo e anno senza parentesi, etichetta italiana della voce (mai il codice),
    confronto col tasso italiano (:func:`confronto_italia`), tendenza a parole,
    rischi collegati con la corrispondenza. Niente conteggi, tassi, percentuali:
    il modello non puo' riportare cifre che non vede; restano in
    :class:`RigaIstat` per il controllo delle frasi e per l'interfaccia.
    """
    testa = f"- {riga.luogo_nome}, {riga.anno}: "
    if riga.voce == VOCE_TOTALE:
        return (
            f"{testa}totale dei delitti denunciati: {_confronto(riga)}; contesto "
            "generale, non legato a un rischio."
        )
    testo = f"{testa}{riga.voce_label}: {_confronto(riga)}; {_tendenza(riga)}."
    if riga.collegamenti:
        testo += f" Collegata a: {_collegamenti(riga.collegamenti)}."
    return testo
