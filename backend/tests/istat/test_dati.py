"""Caricamento dei dati ISTAT (#345, spec 4.1): cache, errori, file reali."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from crime_risk_analyzer.istat import dati as dati_mod
from crime_risk_analyzer.istat.dati import (
    IstatDatiError,
    carica_dati,
    dati_istat,
    dati_istat_o_none,
    svuota_cache,
    versione_dati,
)


@pytest.fixture(autouse=True)
def _cache_pulita() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    svuota_cache()
    yield
    svuota_cache()


def _scrivi(cartella: Path, delitti: object, luoghi: object) -> None:
    (cartella / "delitti.json").write_text(json.dumps(delitti), encoding="utf-8")
    (cartella / "luoghi.json").write_text(json.dumps(luoghi), encoding="utf-8")


def _delitti_minimi(valori: dict[str, object]) -> dict[str, object]:
    return {
        "dataset": "73_67",
        "titolo": "t",
        "url": "u",
        "estratto_il": "2026-10-06",
        "licenza": "CC BY 4.0",
        "anno": 2024,
        "anno_confronto": 2014,
        "voci": {"TOT": "totale"},
        "valori": valori,
    }


def _luoghi_minimi(codici: list[str]) -> dict[str, object]:
    quadrato = [
        [[[12.0, 41.0], [13.0, 41.0], [13.0, 42.0], [12.0, 42.0], [12.0, 41.0]]]
    ]
    return {
        "fonte": "f",
        "url": ["u"],
        "licenza": "CC BY 4.0",
        "generato_il": "2026-10-06",
        "luoghi": [
            {
                "codice": c,
                "tipo": "provincia",
                "nome": f"Provincia di {c}",
                "nome_breve": c,
                "bbox": [12.0, 41.0, 13.0, 42.0],
                "punto_interno": [12.5, 41.5],
                "geometria": {"type": "MultiPolygon", "coordinates": quadrato},
            }
            for c in codici
        ],
    }


def test_carica_i_file_reali() -> None:
    dati = carica_dati()
    assert len(dati.luoghi) == 214
    assert dati.versione == dati.delitti.estratto_il
    assert dati.delitti.anno == 2024
    roma = dati.delitti.valore("058091", "THEFT", 2024)
    assert roma is not None and roma.delitti > 0
    assert dati.delitti.valore("058091", "NONESISTE", 2024) is None


def test_luoghi_ordinati_per_tipo_e_codice() -> None:
    chiavi = [(luogo.tipo, luogo.codice) for luogo in carica_dati().luoghi]
    assert chiavi == sorted(chiavi)


def test_file_mancanti_sollevano(tmp_path: Path) -> None:
    with pytest.raises(IstatDatiError, match="non caricabili"):
        carica_dati(tmp_path)


def test_json_non_valido_solleva(tmp_path: Path) -> None:
    (tmp_path / "delitti.json").write_text("{", encoding="utf-8")
    (tmp_path / "luoghi.json").write_text("{}", encoding="utf-8")
    with pytest.raises(IstatDatiError):
        carica_dati(tmp_path)


def test_manca_la_riga_italia(tmp_path: Path) -> None:
    _scrivi(tmp_path, _delitti_minimi({"ITX01": {}}), _luoghi_minimi(["ITX01"]))
    with pytest.raises(IstatDatiError, match="Italia"):
        carica_dati(tmp_path)


def test_luogo_senza_poligono(tmp_path: Path) -> None:
    _scrivi(
        tmp_path,
        _delitti_minimi({"IT": {}, "ITX01": {}, "ITX02": {}}),
        _luoghi_minimi(["ITX01"]),
    )
    with pytest.raises(IstatDatiError, match="ITX02"):
        carica_dati(tmp_path)


def test_dati_istat_o_none_con_file_mancanti(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review Focus 5: senza file, con l'interruttore spento si prosegue senza dati."""
    monkeypatch.setattr(dati_mod, "_CARTELLA", tmp_path)
    assert dati_istat_o_none() is None
    assert versione_dati() is None
    with pytest.raises(IstatDatiError):
        dati_istat()


def test_esito_in_cache_anche_quando_fallisce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    letture: list[Path | None] = []
    originale = dati_mod.carica_dati

    def _spia(cartella: Path | None = None) -> dati_mod.DatiIstat:
        letture.append(cartella)
        return originale(cartella)

    monkeypatch.setattr(dati_mod, "_CARTELLA", tmp_path)
    monkeypatch.setattr(dati_mod, "carica_dati", _spia)
    assert dati_istat_o_none() is None
    assert dati_istat_o_none() is None
    assert len(letture) == 1


def test_versione_dati_reale() -> None:
    assert versione_dati() == carica_dati().versione
