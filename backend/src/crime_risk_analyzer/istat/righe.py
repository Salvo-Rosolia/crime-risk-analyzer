"""Righe ISTAT di un POI e loro formato nel prompt (#345, spec 4.4).

Per ogni (luogo, voce) una funzione PURA produce valori di ``Y`` e ``Y-10``, tasso
nazionale e variazione decennale. La variazione e' intera e calcolata sui CONTEGGI
(non sul tasso arrotondato); non si calcola se un conteggio e' sotto
:data:`SOGLIA_TENDENZA`, se manca un anno o se la voce e' toccata dalla
depenalizzazione del 2016: la riga dice il motivo.

Nomi del luogo e della voce vengono da etichette fisse (dati e mappatura): nessun
testo da fonti esterne non fidate entra nelle righe.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict

from crime_risk_analyzer.i18n.terminus_labels import label_it
from crime_risk_analyzer.istat.dati import (
    CODICE_ITALIA,
    VOCE_TOTALE,
    DatiIstat,
    Luogo,
    TipoLuogo,
    dati_istat_o_none,
)
from crime_risk_analyzer.istat.luoghi import luogo_di
from crime_risk_analyzer.istat.mappatura import (
    MAPPATURA,
    VOCI_ROTTURA_2016,
    Corrispondenza,
)

__all__ = [
    "MOTIVO_ANNO_MANCANTE",
    "MOTIVO_ROTTURA_2016",
    "MOTIVO_SOTTO_SOGLIA",
    "SOGLIA_TENDENZA",
    "Collegamento",
    "IstatPoi",
    "RigaIstat",
    "formatta_decimale",
    "formatta_intero",
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


def formatta_intero(n: int) -> str:
    """``134169`` -> ``"134.169"`` (migliaia col punto, all'italiana)."""
    return f"{n:,}".replace(",", ".")


def formatta_decimale(x: float) -> str:
    """``1162.7`` -> ``"1.162,7"``: un decimale, virgola decimale, punto migliaia."""
    testo = f"{x:,.1f}"
    return testo.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _tasso(valore: float | None, sotto_soglia: bool) -> str:
    if valore is not None:
        return f"{formatta_decimale(valore)} ogni 100.000 abitanti"
    if sotto_soglia:
        return "meno di 0,1 ogni 100.000 abitanti"
    return "tasso ogni 100.000 abitanti non disponibile"


def _italia(valore: float | None, sotto_soglia: bool) -> str:
    if valore is not None:
        return formatta_decimale(valore)
    return "meno di 0,1" if sotto_soglia else "non disponibile"


def _variazione(riga: RigaIstat) -> str:
    intervallo = f"{riga.anno_confronto}-{riga.anno}"
    if riga.variazione_pct is None:
        return f"variazione {intervallo} non calcolata ({riga.motivo_senza_variazione})"
    segno = "+" if riga.variazione_pct > 0 else ""
    return f"variazione {intervallo}: {segno}{riga.variazione_pct}%"


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


def formatta_riga(riga: RigaIstat, *, poi_coinvolti: int | None = None) -> str:
    """Riga del blocco DATI ISTAT nel formato della spec 4.4 (cornice compresa)."""
    if riga.delitti is not None:
        delitti = f"{formatta_intero(riga.delitti)} delitti denunciati"
    else:
        delitti = f"delitti denunciati nel {riga.anno} non disponibili"
    confronto = (
        formatta_intero(riga.delitti_confronto)
        if riga.delitti_confronto is not None
        else "non disponibile"
    )
    if riga.voce == VOCE_TOTALE:
        testa = (
            f"- [{riga.luogo_nome}, {riga.anno}] totale dei delitti denunciati "
            "(contesto generale, non legato a un rischio)"
        )
    else:
        testa = (
            f"- [{riga.luogo_nome}, {riga.anno}] {riga.voce_label} "
            f"(voce ISTAT {riga.voce})"
        )
    testo = (
        f"{testa}: {delitti} ({riga.anno_confronto}: {confronto}), "
        f"{_tasso(riga.tasso, riga.tasso_sotto_soglia)} "
        f"(Italia: {_italia(riga.tasso_italia, riga.tasso_italia_sotto_soglia)}); "
        f"{_variazione(riga)}."
    )
    if riga.collegamenti:
        testo += f" Collegata a: {_collegamenti(riga.collegamenti)}."
    if poi_coinvolti is not None:
        testo += f" POI coinvolti: {poi_coinvolti}."
    return testo
