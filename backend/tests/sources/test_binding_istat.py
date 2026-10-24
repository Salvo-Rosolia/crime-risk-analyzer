"""Dati ISTAT, mappatura, serie non confrontabili e versione dal set attivo (#414)."""

from __future__ import annotations

import dataclasses

from crime_risk_analyzer.context_fingerprint import (
    fingerprint,
    fonti_attive_id,
    istat_versione_per,
)
from crime_risk_analyzer.istat.catalogo import VOCI_ROTTURA_2016
from crime_risk_analyzer.istat.dati import DatiIstat, dati_istat, versione_dati
from crime_risk_analyzer.istat.luoghi import luogo_di
from crime_risk_analyzer.istat.mappatura import MAPPATURA, Mappatura
from crime_risk_analyzer.istat.righe import (
    MOTIVO_ROTTURA_2016,
    istat_per_poi,
    riga_istat,
)
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.sources import context
from crime_risk_analyzer.sources.context import bind, default_set
from crime_risk_analyzer.sources.model import IstatSource, SourceSet

ROMA = (41.8902, 12.4922)


def _set(
    id_: str,
    *,
    dati: DatiIstat | None,
    mappatura: dict[str, Mappatura] | None = None,
    voci_rottura: frozenset[str] = frozenset(),
    versione: str | None = "v-custom",
) -> SourceSet:
    return dataclasses.replace(
        default_set(),
        id=id_,
        kind="custom",
        istat=IstatSource(
            dati=dati,
            mappatura=MAPPATURA if mappatura is None else mappatura,
            voci_rottura=voci_rottura,
            versione=versione,
        ),
    )


def _dati_con_anno(delitti_attuale: int) -> DatiIstat:
    """Copia dei dati reali in cui Roma/BANKROB ha un altro conteggio."""
    reali = dati_istat()
    valori = {
        k: {v: dict(a) for v, a in voci.items()}
        for k, voci in reali.delitti.valori.items()
    }
    anno = str(reali.delitti.anno)
    base = valori["058091"]["BANKROB"][anno]
    assert base is not None
    valori["058091"]["BANKROB"][anno] = base.model_copy(
        update={"delitti": delitti_attuale}
    )
    delitti = reali.delitti.model_copy(
        update={"valori": valori, "estratto_il": "2030-01-01"}
    )
    return DatiIstat(delitti=delitti, luoghi=reali.luoghi)


def _delitti_bankrob(poi_set: SourceSet | None) -> int | None:
    def calcola() -> int | None:
        istat = istat_per_poi(*ROMA, ["Bank_robbery"])
        assert istat is not None
        return istat.righe[0].delitti

    if poi_set is None:
        return calcola()
    with bind(poi_set):
        return calcola()


def test_default_identico() -> None:
    attivo = default_set().istat
    assert attivo.versione == versione_dati()
    assert context.versione_dati() == versione_dati()
    assert attivo.mappatura is MAPPATURA
    assert attivo.voci_rottura is VOCI_ROTTURA_2016
    assert istat_versione_per(True) == versione_dati()
    hazards = ["Bank_robbery", "Landslide"]
    dati = dati_istat()
    roma = luogo_di(*ROMA, dati=dati)
    assert roma is not None
    voci = ["BANKROB", *VOCI_ROTTURA_2016]  # include le serie non confrontabili
    pois: list[Poi] = [
        {
            "id": "node/1",
            "name": "Banca A",
            "lat": 41.89,
            "lon": 12.49,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": "Roma",
        }
    ]

    def calcola() -> tuple[object, list[object], str, str | None]:
        return (
            istat_per_poi(*ROMA, hazards),
            [riga_istat(dati, roma, voce) for voce in voci],
            fingerprint(pois, istat_versione=istat_versione_per(True)),
            fonti_attive_id(),
        )

    fuori = calcola()  # nessun bind: ripiego sul default
    with bind(default_set()):
        dentro = calcola()
    assert dentro == fuori
    assert fuori[0] is not None
    assert any(r.rottura_2016 for r in fuori[1])  # type: ignore[attr-defined]
    assert dentro[2] == fuori[2]  # impronta byte-identica


def test_righe_dai_dati_del_set() -> None:
    custom = _set("c1", dati=_dati_con_anno(7), mappatura=MAPPATURA)
    reale = _delitti_bankrob(None)
    assert reale != 7
    assert _delitti_bankrob(custom) == 7
    assert _delitti_bankrob(None) == reale  # fuori dal bind, di nuovo il default


def test_set_senza_dati_non_ricade_sul_default() -> None:
    with bind(_set("c2", dati=None, versione=None)):
        assert istat_per_poi(*ROMA, ["Bank_robbery"]) is None
        assert context.versione_dati() is None


def test_mappatura_dal_set() -> None:
    mappatura = {
        "Landslide": Mappatura(
            voce_istat="BANKROB",
            corrispondenza="piu_stretta",
            rottura_2016=False,
            nota="",
        )
    }
    with bind(_set("c3", dati=dati_istat(), mappatura=mappatura)):
        assert istat_per_poi(*ROMA, ["Bank_robbery"]) is None  # non e' nel set
        istat = istat_per_poi(*ROMA, ["Landslide"])
    assert istat is not None
    assert [r.voce for r in istat.righe] == ["BANKROB"]
    assert istat.righe[0].collegamenti[0].corrispondenza == "piu_stretta"
    assert istat_per_poi(*ROMA, ["Landslide"]) is None  # default invariato


def test_voci_a_serie_non_confrontabile_dal_set() -> None:
    dati = dati_istat()
    roma = luogo_di(*ROMA, dati=dati)
    assert roma is not None
    assert not riga_istat(dati, roma, "BANKROB").rottura_2016
    with bind(_set("c4", dati=dati, voci_rottura=frozenset({"BANKROB"}))):
        riga = riga_istat(dati, roma, "BANKROB")
        via_poi = istat_per_poi(*ROMA, ["Bank_robbery"])
    assert riga.rottura_2016
    assert riga.motivo_senza_variazione == MOTIVO_ROTTURA_2016
    assert via_poi is not None and via_poi.righe[0].rottura_2016
    assert not riga_istat(dati, roma, "BANKROB").rottura_2016


def test_impronta_cambia_con_la_versione_del_set() -> None:
    pois: list[Poi] = [
        {
            "id": "node/1",
            "name": "Banca A",
            "lat": 41.89,
            "lon": 12.49,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": "Roma",
        }
    ]
    base = fingerprint(pois, istat_versione=istat_versione_per(True))
    with bind(_set("stesso", dati=dati_istat(), versione="A")):
        a = fingerprint(pois, istat_versione=istat_versione_per(True))
    with bind(_set("stesso", dati=dati_istat(), versione="B")):
        b = fingerprint(pois, istat_versione=istat_versione_per(True))
        spento = istat_versione_per(False)
    assert len({base, a, b}) == 3
    assert spento is None


def test_due_set_non_si_mescolano() -> None:
    uno, due = _set("u", dati=_dati_con_anno(11)), _set("d", dati=_dati_con_anno(22))
    reale = _delitti_bankrob(None)
    for _ in range(2):  # la seconda lettura passa dalle cache
        assert _delitti_bankrob(uno) == 11
        assert _delitti_bankrob(due) == 22
        assert _delitti_bankrob(None) == reale


def test_dati_espliciti_con_mappatura_e_rotture_del_set_attivo() -> None:
    """Fonte mista voluta: ``dati=`` prende i dati dall'argomento, il resto dal set."""
    custom = _set(
        "mista",
        dati=_dati_con_anno(7),
        voci_rottura=frozenset({"BANKROB"}),
    )
    reali = dati_istat()
    with bind(custom):
        istat = istat_per_poi(*ROMA, ["Bank_robbery"], dati=reali)
    assert istat is not None
    riga = istat.righe[0]
    assert riga.delitti == _delitti_bankrob(None)  # dati dall'argomento, non dal set
    assert riga.delitti != 7
    assert riga.rottura_2016  # rotture dal set attivo
    assert istat_per_poi(*ROMA, ["Bank_robbery"], dati=reali) is not None
