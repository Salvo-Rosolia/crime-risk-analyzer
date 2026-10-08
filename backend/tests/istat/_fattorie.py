"""Righe ISTAT sintetiche per i test (#345): nessuna dipendenza dai dati reali."""

from __future__ import annotations

from crime_risk_analyzer.istat.dati import TipoLuogo
from crime_risk_analyzer.istat.mappatura import Corrispondenza
from crime_risk_analyzer.istat.righe import (
    MOTIVO_ROTTURA_2016,
    MOTIVO_SOTTO_SOGLIA,
    Collegamento,
    IstatPoi,
    RigaIstat,
)


def collegamento(
    hazard: str = "Property_theft",
    label: str = "Furto di beni",
    corrispondenza: Corrispondenza = "piu_larga",
) -> Collegamento:
    return Collegamento(
        hazard=hazard, hazard_label_it=label, corrispondenza=corrispondenza
    )


def riga(
    voce: str = "THEFT",
    *,
    label: str = "furti",
    luogo: str = "058091",
    nome: str = "Comune di Roma",
    breve: str = "Roma",
    tipo: TipoLuogo = "comune",
    delitti: int | None = 134169,
    confronto: int | None = 148910,
    tasso: float | None = 4876.4,
    sotto_soglia: bool = False,
    italia: float | None = 1788.7,
    variazione: int | None = -10,
    motivo: str | None = None,
    rottura_2016: bool = False,
    collegamenti: tuple[Collegamento, ...] | None = None,
) -> RigaIstat:
    return RigaIstat(
        luogo_codice=luogo,
        luogo_nome=nome,
        luogo_breve=breve,
        luogo_tipo=tipo,
        voce=voce,
        voce_label=label,
        anno=2024,
        anno_confronto=2014,
        delitti=delitti,
        delitti_confronto=confronto,
        tasso=tasso,
        tasso_sotto_soglia=sotto_soglia,
        tasso_italia=italia,
        variazione_pct=variazione,
        motivo_senza_variazione=motivo,
        rottura_2016=rottura_2016,
        collegamenti=(collegamento(),) if collegamenti is None else collegamenti,
    )


def cornice(
    *,
    luogo: str = "058091",
    nome: str = "Comune di Roma",
    breve: str = "Roma",
    tipo: TipoLuogo = "comune",
) -> RigaIstat:
    return riga(
        "TOT",
        label="totale",
        luogo=luogo,
        nome=nome,
        breve=breve,
        tipo=tipo,
        delitti=217536,
        confronto=216750,
        tasso=7906.3,
        italia=4069.6,
        # Il totale comprende fatti depenalizzati nel 2016: niente variazione (#353).
        variazione=None,
        motivo=MOTIVO_ROTTURA_2016,
        rottura_2016=True,
        collegamenti=(),
    )


def istat_poi(*righe: RigaIstat) -> IstatPoi:
    prima = righe[0]
    return IstatPoi(
        cornice=cornice(
            luogo=prima.luogo_codice,
            nome=prima.luogo_nome,
            breve=prima.luogo_breve,
            tipo=prima.luogo_tipo,
        ),
        righe=righe,
    )


BANKROB = riga(
    "BANKROB",
    label="rapine in banca",
    delitti=3,
    confronto=46,
    tasso=0.1,
    italia=0.1,
    variazione=None,
    motivo=MOTIVO_SOTTO_SOGLIA,
    collegamenti=(collegamento("Bank_robbery", "Rapina in banca", "esatta"),),
)
