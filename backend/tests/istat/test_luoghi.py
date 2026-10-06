"""Luogo ISTAT di un punto (#345, spec 4.3): comune capoluogo, poi provincia."""

from __future__ import annotations

import pytest
from crime_risk_analyzer.istat.dati import (
    DatiIstat,
    FileDelitti,
    Luogo,
    TipoLuogo,
    dati_istat,
)
from crime_risk_analyzer.istat.luoghi import luogo_di

from crime_risk_analyzer.models.geo import CityBoundary, point_in_multipolygon


@pytest.mark.parametrize(
    ("lat", "lon", "atteso"),
    [
        (41.8902, 12.4922, "058091"),  # Colosseo -> Comune di Roma
        (45.4642, 9.1900, "015146"),  # Duomo -> Comune di Milano
        (40.8530, 14.2730, "063049"),  # Piazza Garibaldi -> Comune di Napoli
        (45.0620, 7.6787, "001272"),  # Porta Nuova -> Comune di Torino
        (41.7700, 12.2400, "ITE43"),  # Fiumicino -> Provincia di Roma
        (46.5667, 12.6833, "ITD42"),  # Sappada: Udine dal 2017
        (43.8170, 12.2667, "ITD59"),  # Pennabilli (Alta Valmarecchia) -> Rimini
        (40.2980, 8.4980, "ITG26"),  # Bosa: Nuoro con i confini 2001
        (40.9230, 9.4980, "ITG25"),  # Olbia -> Sassari storica
        (39.1670, 8.5220, "ITG27"),  # Carbonia -> Cagliari storica
        (45.7375, 7.3201, "007003"),  # Aosta
        (46.4983, 11.3548, "021008"),  # Bolzano
    ],
)
def test_campione_di_luoghi_reali(lat: float, lon: float, atteso: str) -> None:
    luogo = luogo_di(lat, lon)
    assert luogo is not None
    assert luogo.codice == atteso


@pytest.mark.parametrize(("lat", "lon"), [(41.0, 12.0), (46.0037, 8.9511)])
def test_fuori_da_ogni_poligono(lat: float, lon: float) -> None:
    """Mare davanti al Lazio, Lugano (Svizzera)."""
    assert luogo_di(lat, lon) is None


def test_nomi_per_la_narrativa() -> None:
    roma = luogo_di(41.8902, 12.4922)
    provincia = luogo_di(41.7700, 12.2400)
    assert roma is not None and provincia is not None
    assert (roma.nome, roma.nome_breve, roma.tipo) == (
        "Comune di Roma",
        "Roma",
        "comune",
    )
    assert (provincia.nome, provincia.tipo) == ("Provincia di Roma", "provincia")


def test_ogni_capoluogo_cade_nel_suo_comune_e_nella_sua_provincia() -> None:
    dati = dati_istat()
    province = {x.codice: x for x in dati.luoghi if x.tipo == "provincia"}
    for comune in (x for x in dati.luoghi if x.tipo == "comune"):
        lon, lat = comune.punto_interno
        trovato = luogo_di(lat, lon, dati=dati)
        assert trovato is not None and trovato.codice == comune.codice
        assert comune.provincia is not None
        assert point_in_multipolygon(
            comune.punto_interno, province[comune.provincia].confine
        )


def _quadrato(x0: float, y0: float, x1: float, y1: float) -> CityBoundary:
    return CityBoundary(polygons=[[[(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]]])


def _luogo(
    codice: str, tipo: TipoLuogo, box: tuple[float, float, float, float]
) -> Luogo:
    x0, y0, x1, y1 = box
    return Luogo(
        codice=codice,
        tipo=tipo,
        nome=codice,
        nome_breve=codice,
        provincia=None,
        bbox=box,
        punto_interno=((x0 + x1) / 2, (y0 + y1) / 2),
        confine=_quadrato(*box),
    )


def test_luogo_di_sovrapposizioni_buchi_e_riquadro() -> None:
    """Review Focus 1: comune prima della provincia, a parita' il codice minore."""
    dati = DatiIstat(
        delitti=FileDelitti(
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
            _luogo("000001", "comune", (0.2, 0.2, 0.8, 0.8)),
            _luogo("ITX01", "provincia", (0.0, 0.0, 2.0, 2.0)),
            _luogo("ITX02", "provincia", (1.0, 0.0, 3.0, 2.0)),
        ),
    )

    def _codice(lat: float, lon: float) -> str | None:
        trovato = luogo_di(lat, lon, dati=dati)
        return trovato.codice if trovato else None

    assert _codice(0.5, 0.5) == "000001"  # dentro comune e provincia: il comune
    assert _codice(1.5, 1.5) == "ITX01"  # due province sovrapposte: codice minore
    assert _codice(1.0, 2.5) == "ITX02"
    assert _codice(1.9, 0.1) == "ITX01"  # fuori dal comune, dentro la provincia
    assert _codice(5.0, 5.0) is None


def test_senza_dati_nessun_luogo(monkeypatch: pytest.MonkeyPatch) -> None:
    from crime_risk_analyzer.istat import luoghi as luoghi_mod

    monkeypatch.setattr(luoghi_mod, "dati_istat_o_none", lambda: None)
    assert luogo_di(41.8902, 12.4922) is None
