"""Dati ISTAT, mappatura, serie non confrontabili e versione dal set attivo (#414)."""

from __future__ import annotations

import dataclasses

from crime_risk_analyzer.context_fingerprint import (
    active_sources_id,
    fingerprint,
    istat_version_for,
)
from crime_risk_analyzer.istat.catalog import BREAK_ITEMS_2016
from crime_risk_analyzer.istat.data import IstatData, data_version, istat_data
from crime_risk_analyzer.istat.mapping import HAZARD_MAPPING, HazardMapping
from crime_risk_analyzer.istat.places import place_of
from crime_risk_analyzer.istat.rows import (
    REASON_BREAK_2016,
    istat_for_poi,
    istat_row,
)
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.sources import context
from crime_risk_analyzer.sources.context import bind, default_set
from crime_risk_analyzer.sources.model import IstatSource, SourceSet

ROMA = (41.8902, 12.4922)


def _set(
    id_: str,
    *,
    dati: IstatData | None,
    mappatura: dict[str, HazardMapping] | None = None,
    voci_rottura: frozenset[str] = frozenset(),
    versione: str | None = "v-custom",
) -> SourceSet:
    return dataclasses.replace(
        default_set(),
        id=id_,
        kind="custom",
        istat=IstatSource(
            dati=dati,
            mappatura=HAZARD_MAPPING if mappatura is None else mappatura,
            voci_rottura=voci_rottura,
            versione=versione,
        ),
    )


def _dati_con_anno(delitti_attuale: int) -> IstatData:
    """Copia dei dati reali in cui Roma/BANKROB ha un altro conteggio."""
    reali = istat_data()
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
    return IstatData(delitti=delitti, luoghi=reali.luoghi)


def _delitti_bankrob(poi_set: SourceSet | None) -> int | None:
    def calcola() -> int | None:
        istat = istat_for_poi(*ROMA, ["Bank_robbery"])
        assert istat is not None
        return istat.righe[0].delitti

    if poi_set is None:
        return calcola()
    with bind(poi_set):
        return calcola()


def test_default_identico() -> None:
    attivo = default_set().istat
    assert attivo.versione == data_version()
    assert context.istat_data_version() == data_version()
    assert attivo.mappatura is HAZARD_MAPPING
    assert attivo.voci_rottura is BREAK_ITEMS_2016
    assert istat_version_for(True) == data_version()
    hazards = ["Bank_robbery", "Landslide"]
    dati = istat_data()
    roma = place_of(*ROMA, data=dati)
    assert roma is not None
    voci = ["BANKROB", *BREAK_ITEMS_2016]  # include le serie non confrontabili
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
            istat_for_poi(*ROMA, hazards),
            [istat_row(dati, roma, voce) for voce in voci],
            fingerprint(pois, istat_version=istat_version_for(True)),
            active_sources_id(),
        )

    fuori = calcola()  # nessun bind: ripiego sul default
    with bind(default_set()):
        dentro = calcola()
    assert dentro == fuori
    assert fuori[0] is not None
    assert any(r.rottura_2016 for r in fuori[1])  # type: ignore[attr-defined]
    assert dentro[2] == fuori[2]  # impronta byte-identica


def test_righe_dai_dati_del_set() -> None:
    custom = _set("c1", dati=_dati_con_anno(7), mappatura=HAZARD_MAPPING)
    reale = _delitti_bankrob(None)
    assert reale != 7
    assert _delitti_bankrob(custom) == 7
    assert _delitti_bankrob(None) == reale  # fuori dal bind, di nuovo il default


def test_set_senza_dati_non_ricade_sul_default() -> None:
    with bind(_set("c2", dati=None, versione=None)):
        assert istat_for_poi(*ROMA, ["Bank_robbery"]) is None
        assert context.istat_data_version() is None


def test_mappatura_dal_set() -> None:
    mappatura = {
        "Landslide": HazardMapping(
            voce_istat="BANKROB",
            corrispondenza="piu_stretta",
            rottura_2016=False,
            nota="",
        )
    }
    with bind(_set("c3", dati=istat_data(), mappatura=mappatura)):
        assert istat_for_poi(*ROMA, ["Bank_robbery"]) is None  # non e' nel set
        istat = istat_for_poi(*ROMA, ["Landslide"])
    assert istat is not None
    assert [r.voce for r in istat.righe] == ["BANKROB"]
    assert istat.righe[0].collegamenti[0].corrispondenza == "piu_stretta"
    assert istat_for_poi(*ROMA, ["Landslide"]) is None  # default invariato


def test_voci_a_serie_non_confrontabile_dal_set() -> None:
    dati = istat_data()
    roma = place_of(*ROMA, data=dati)
    assert roma is not None
    assert not istat_row(dati, roma, "BANKROB").rottura_2016
    with bind(_set("c4", dati=dati, voci_rottura=frozenset({"BANKROB"}))):
        riga = istat_row(dati, roma, "BANKROB")
        via_poi = istat_for_poi(*ROMA, ["Bank_robbery"])
    assert riga.rottura_2016
    assert riga.motivo_senza_variazione == REASON_BREAK_2016
    assert via_poi is not None and via_poi.righe[0].rottura_2016
    assert not istat_row(dati, roma, "BANKROB").rottura_2016


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
    base = fingerprint(pois, istat_version=istat_version_for(True))
    with bind(_set("stesso", dati=istat_data(), versione="A")):
        a = fingerprint(pois, istat_version=istat_version_for(True))
    with bind(_set("stesso", dati=istat_data(), versione="B")):
        b = fingerprint(pois, istat_version=istat_version_for(True))
        spento = istat_version_for(False)
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
    """Fonte mista voluta: ``data=`` prende i dati dall'argomento, il resto dal set."""
    custom = _set(
        "mista",
        dati=_dati_con_anno(7),
        voci_rottura=frozenset({"BANKROB"}),
    )
    reali = istat_data()
    with bind(custom):
        istat = istat_for_poi(*ROMA, ["Bank_robbery"], data=reali)
    assert istat is not None
    riga = istat.righe[0]
    assert riga.delitti == _delitti_bankrob(None)  # dati dall'argomento, non dal set
    assert riga.delitti != 7
    assert riga.rottura_2016  # rotture dal set attivo
    assert istat_for_poi(*ROMA, ["Bank_robbery"], data=reali) is not None
