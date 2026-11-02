"""Loading of the ISTAT data (#345, spec 4.1): cache, errors, real files."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from crime_risk_analyzer.istat import data as data_mod
from crime_risk_analyzer.istat.data import (
    IstatDataError,
    clear_cache,
    data_version,
    istat_data,
    istat_data_or_none,
    load_data,
)


@pytest.fixture(autouse=True)
def _clean_cache() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    clear_cache()
    yield
    clear_cache()


def _write(directory: Path, offences: object, places: object) -> None:
    (directory / "delitti.json").write_text(json.dumps(offences), encoding="utf-8")
    (directory / "luoghi.json").write_text(json.dumps(places), encoding="utf-8")


def _minimal_offences(values: dict[str, object]) -> dict[str, object]:
    return {
        "dataset": "73_67",
        "titolo": "t",
        "url": "u",
        "estratto_il": "2026-10-06",
        "licenza": "CC BY 4.0",
        "anno": 2024,
        "anno_confronto": 2014,
        "voci": {"TOT": "totale"},
        "valori": values,
    }


def _minimal_places(codes: list[str]) -> dict[str, object]:
    square = [[[[12.0, 41.0], [13.0, 41.0], [13.0, 42.0], [12.0, 42.0], [12.0, 41.0]]]]
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
                "geometria": {"type": "MultiPolygon", "coordinates": square},
            }
            for c in codes
        ],
    }


def test_loads_the_real_files() -> None:
    data = load_data()
    assert len(data.luoghi) == 214
    assert data.versione == data.delitti.estratto_il
    assert data.delitti.anno == 2024
    roma = data.delitti.valore("058091", "THEFT", 2024)
    assert roma is not None and roma.delitti > 0
    assert data.delitti.valore("058091", "NONESISTE", 2024) is None


def test_places_sorted_by_type_and_code() -> None:
    keys = [(place.tipo, place.codice) for place in load_data().luoghi]
    assert keys == sorted(keys)


def test_missing_files_raise(tmp_path: Path) -> None:
    with pytest.raises(IstatDataError, match="non caricabili"):
        load_data(tmp_path)


def test_invalid_json_raises(tmp_path: Path) -> None:
    (tmp_path / "delitti.json").write_text("{", encoding="utf-8")
    (tmp_path / "luoghi.json").write_text("{}", encoding="utf-8")
    with pytest.raises(IstatDataError):
        load_data(tmp_path)


def test_missing_italy_row(tmp_path: Path) -> None:
    _write(tmp_path, _minimal_offences({"ITX01": {}}), _minimal_places(["ITX01"]))
    with pytest.raises(IstatDataError, match="Italia"):
        load_data(tmp_path)


def test_place_without_polygon(tmp_path: Path) -> None:
    _write(
        tmp_path,
        _minimal_offences({"IT": {}, "ITX01": {}, "ITX02": {}}),
        _minimal_places(["ITX01"]),
    )
    with pytest.raises(IstatDataError, match="ITX02"):
        load_data(tmp_path)


def test_istat_data_or_none_with_missing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review Focus 5: without files, with the switch off we proceed without data."""
    monkeypatch.setattr(data_mod, "_DATA_DIR", tmp_path)
    assert istat_data_or_none() is None
    assert data_version() is None
    with pytest.raises(IstatDataError):
        istat_data()


def test_outcome_cached_even_when_it_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readings: list[Path | None] = []
    original = data_mod.load_data

    def _spy(directory: Path | None = None) -> data_mod.IstatData:
        readings.append(directory)
        return original(directory)

    monkeypatch.setattr(data_mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(data_mod, "load_data", _spy)
    assert istat_data_or_none() is None
    assert istat_data_or_none() is None
    assert len(readings) == 1


def test_real_data_version() -> None:
    assert data_version() == load_data().versione
