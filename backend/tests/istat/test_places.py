"""ISTAT place of a point (#345, spec 4.3): provincial capital, then province."""

from __future__ import annotations

import pytest

from crime_risk_analyzer.istat.data import (
    IstatData,
    OffencesFile,
    Place,
    PlaceType,
    istat_data,
)
from crime_risk_analyzer.istat.places import place_of
from crime_risk_analyzer.models.geo import CityBoundary, point_in_multipolygon


@pytest.mark.parametrize(
    ("lat", "lon", "expected"),
    [
        (41.8902, 12.4922, "058091"),  # Colosseum -> Comune di Roma
        (45.4642, 9.1900, "015146"),  # Duomo -> Comune di Milano
        (40.8530, 14.2730, "063049"),  # Piazza Garibaldi -> Comune di Napoli
        (45.0620, 7.6787, "001272"),  # Porta Nuova -> Comune di Torino
        (41.7700, 12.2400, "ITE43"),  # Fiumicino -> Provincia di Roma
        (46.5667, 12.6833, "ITD42"),  # Sappada: Udine since 2017
        (43.8170, 12.2667, "ITD59"),  # Pennabilli (Alta Valmarecchia) -> Rimini
        (40.2980, 8.4980, "ITG26"),  # Bosa: Nuoro with the 2001 boundaries
        (40.9230, 9.4980, "ITG25"),  # Olbia -> historical Sassari
        (39.1670, 8.5220, "ITG27"),  # Carbonia -> historical Cagliari
        (45.7375, 7.3201, "007003"),  # Aosta
        (46.4983, 11.3548, "021008"),  # Bolzano
    ],
)
def test_sample_of_real_places(lat: float, lon: float, expected: str) -> None:
    place = place_of(lat, lon)
    assert place is not None
    assert place.codice == expected


@pytest.mark.parametrize(("lat", "lon"), [(41.0, 12.0), (46.0037, 8.9511)])
def test_outside_every_polygon(lat: float, lon: float) -> None:
    """Sea off Lazio, Lugano (Switzerland)."""
    assert place_of(lat, lon) is None


def test_names_for_the_narrative() -> None:
    roma = place_of(41.8902, 12.4922)
    province = place_of(41.7700, 12.2400)
    assert roma is not None and province is not None
    assert (roma.nome, roma.nome_breve, roma.tipo) == (
        "Comune di Roma",
        "Roma",
        "comune",
    )
    assert (province.nome, province.tipo) == ("Provincia di Roma", "provincia")


def test_every_capital_falls_in_its_municipality_and_province() -> None:
    data = istat_data()
    provinces = {x.codice: x for x in data.luoghi if x.tipo == "provincia"}
    for municipality in (x for x in data.luoghi if x.tipo == "comune"):
        lon, lat = municipality.punto_interno
        found = place_of(lat, lon, data=data)
        assert found is not None and found.codice == municipality.codice
        assert municipality.provincia is not None
        assert point_in_multipolygon(
            municipality.punto_interno, provinces[municipality.provincia].confine
        )


def _square(x0: float, y0: float, x1: float, y1: float) -> CityBoundary:
    return CityBoundary(polygons=[[[(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]]])


def _place(code: str, kind: PlaceType, box: tuple[float, float, float, float]) -> Place:
    x0, y0, x1, y1 = box
    return Place(
        codice=code,
        tipo=kind,
        nome=code,
        nome_breve=code,
        provincia=None,
        bbox=box,
        punto_interno=((x0 + x1) / 2, (y0 + y1) / 2),
        confine=_square(*box),
    )


def test_place_of_overlaps_holes_and_bbox() -> None:
    """Review Focus 1: municipality before province, on a tie the lower code."""
    data = IstatData(
        delitti=OffencesFile(
            dataset="73_67",
            titolo="t",
            url="u",
            estratto_il="2026-10-06",
            licenza="CC BY 4.0",
            anno=2024,
            anno_confronto=2014,
            voci={},
            valori={},
        ),
        luoghi=(
            _place("000001", "comune", (0.2, 0.2, 0.8, 0.8)),
            _place("ITX01", "provincia", (0.0, 0.0, 2.0, 2.0)),
            _place("ITX02", "provincia", (1.0, 0.0, 3.0, 2.0)),
        ),
    )

    def _code(lat: float, lon: float) -> str | None:
        found = place_of(lat, lon, data=data)
        return found.codice if found else None

    assert (
        _code(0.5, 0.5) == "000001"
    )  # inside municipality and province: the municipality
    assert _code(1.5, 1.5) == "ITX01"  # two overlapping provinces: lower code
    assert _code(1.0, 2.5) == "ITX02"
    assert _code(1.9, 0.1) == "ITX01"  # outside the municipality, inside the province
    assert _code(5.0, 5.0) is None


def test_without_data_no_place(monkeypatch: pytest.MonkeyPatch) -> None:
    from crime_risk_analyzer.istat import places as places_mod

    monkeypatch.setattr(places_mod, "istat_data_or_none", lambda: None)
    assert place_of(41.8902, 12.4922) is None
