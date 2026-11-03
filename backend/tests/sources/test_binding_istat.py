"""ISTAT data, mapping, non-comparable series and version from the active set (#414)."""

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

ROME = (41.8902, 12.4922)


def _set(
    id_: str,
    *,
    data: IstatData | None,
    mapping: dict[str, HazardMapping] | None = None,
    break_items: frozenset[str] = frozenset(),
    version: str | None = "v-custom",
) -> SourceSet:
    return dataclasses.replace(
        default_set(),
        id=id_,
        kind="custom",
        istat=IstatSource(
            dati=data,
            mappatura=HAZARD_MAPPING if mapping is None else mapping,
            voci_rottura=break_items,
            versione=version,
        ),
    )


def _data_with_year(current_crimes: int) -> IstatData:
    """Copy of the real data where Rome/BANKROB has a different count."""
    real = istat_data()
    values = {
        k: {v: dict(a) for v, a in items.items()}
        for k, items in real.delitti.valori.items()
    }
    year = str(real.delitti.anno)
    base = values["058091"]["BANKROB"][year]
    assert base is not None
    values["058091"]["BANKROB"][year] = base.model_copy(
        update={"delitti": current_crimes}
    )
    crimes = real.delitti.model_copy(
        update={"valori": values, "estratto_il": "2030-01-01"}
    )
    return IstatData(delitti=crimes, luoghi=real.luoghi)


def _bankrob_crimes(poi_set: SourceSet | None) -> int | None:
    def compute() -> int | None:
        istat = istat_for_poi(*ROME, ["Bank_robbery"])
        assert istat is not None
        return istat.righe[0].delitti

    if poi_set is None:
        return compute()
    with bind(poi_set):
        return compute()


def test_default_identical() -> None:
    active = default_set().istat
    assert active.versione == data_version()
    assert context.istat_data_version() == data_version()
    assert active.mappatura is HAZARD_MAPPING
    assert active.voci_rottura is BREAK_ITEMS_2016
    assert istat_version_for(True) == data_version()
    hazards = ["Bank_robbery", "Landslide"]
    data = istat_data()
    rome = place_of(*ROME, data=data)
    assert rome is not None
    items = ["BANKROB", *BREAK_ITEMS_2016]  # includes the non-comparable series
    pois: list[Poi] = [
        {
            "id": "node/1",
            "name": "Banca A",
            "lat": 41.89,
            "lon": 12.49,
            "osm_tags": "amenity=bank",
            "ontology_class": "Bank",
            "citta": "Roma",
        }
    ]

    def compute() -> tuple[object, list[object], str, str | None]:
        return (
            istat_for_poi(*ROME, hazards),
            [istat_row(data, rome, item) for item in items],
            fingerprint(pois, istat_version=istat_version_for(True)),
            active_sources_id(),
        )

    outside = compute()  # no bind: falls back to the default
    with bind(default_set()):
        inside = compute()
    assert inside == outside
    assert outside[0] is not None
    assert any(r.rottura_2016 for r in outside[1])  # type: ignore[attr-defined]
    assert inside[2] == outside[2]  # byte-identical fingerprint


def test_rows_from_the_set_data() -> None:
    custom = _set("c1", data=_data_with_year(7), mapping=HAZARD_MAPPING)
    real = _bankrob_crimes(None)
    assert real != 7
    assert _bankrob_crimes(custom) == 7
    assert _bankrob_crimes(None) == real  # outside the bind, the default again


def test_set_without_data_does_not_fall_back_to_default() -> None:
    with bind(_set("c2", data=None, version=None)):
        assert istat_for_poi(*ROME, ["Bank_robbery"]) is None
        assert context.istat_data_version() is None


def test_mapping_from_the_set() -> None:
    mapping = {
        "Landslide": HazardMapping(
            voce_istat="BANKROB",
            corrispondenza="piu_stretta",
            rottura_2016=False,
            nota="",
        )
    }
    with bind(_set("c3", data=istat_data(), mapping=mapping)):
        assert istat_for_poi(*ROME, ["Bank_robbery"]) is None  # it is not in the set
        istat = istat_for_poi(*ROME, ["Landslide"])
    assert istat is not None
    assert [r.voce for r in istat.righe] == ["BANKROB"]
    assert istat.righe[0].collegamenti[0].corrispondenza == "piu_stretta"
    assert istat_for_poi(*ROME, ["Landslide"]) is None  # default unchanged


def test_break_series_items_from_the_set() -> None:
    data = istat_data()
    rome = place_of(*ROME, data=data)
    assert rome is not None
    assert not istat_row(data, rome, "BANKROB").rottura_2016
    with bind(_set("c4", data=data, break_items=frozenset({"BANKROB"}))):
        row = istat_row(data, rome, "BANKROB")
        via_poi = istat_for_poi(*ROME, ["Bank_robbery"])
    assert row.rottura_2016
    assert row.motivo_senza_variazione == REASON_BREAK_2016
    assert via_poi is not None and via_poi.righe[0].rottura_2016
    assert not istat_row(data, rome, "BANKROB").rottura_2016


def test_fingerprint_changes_with_the_set_version() -> None:
    pois: list[Poi] = [
        {
            "id": "node/1",
            "name": "Banca A",
            "lat": 41.89,
            "lon": 12.49,
            "osm_tags": "amenity=bank",
            "ontology_class": "Bank",
            "citta": "Roma",
        }
    ]
    base = fingerprint(pois, istat_version=istat_version_for(True))
    with bind(_set("stesso", data=istat_data(), version="A")):
        a = fingerprint(pois, istat_version=istat_version_for(True))
    with bind(_set("stesso", data=istat_data(), version="B")):
        b = fingerprint(pois, istat_version=istat_version_for(True))
        off = istat_version_for(False)
    assert len({base, a, b}) == 3
    assert off is None


def test_two_sets_do_not_mix() -> None:
    one, two = _set("u", data=_data_with_year(11)), _set("d", data=_data_with_year(22))
    real = _bankrob_crimes(None)
    for _ in range(2):  # the second read goes through the caches
        assert _bankrob_crimes(one) == 11
        assert _bankrob_crimes(two) == 22
        assert _bankrob_crimes(None) == real


def test_explicit_data_with_mapping_and_breaks_of_the_active_set() -> None:
    """Intentional mixed source: ``data=`` takes the data from the argument, the rest
    from the set."""
    custom = _set(
        "mista",
        data=_data_with_year(7),
        break_items=frozenset({"BANKROB"}),
    )
    real = istat_data()
    with bind(custom):
        istat = istat_for_poi(*ROME, ["Bank_robbery"], data=real)
    assert istat is not None
    row = istat.righe[0]
    assert row.delitti == _bankrob_crimes(
        None
    )  # data from the argument, not from the set
    assert row.delitti != 7
    assert row.rottura_2016  # breaks from the active set
    assert istat_for_poi(*ROME, ["Bank_robbery"], data=real) is not None
