"""Shape and size of the committed ISTAT data files (#345, spec 4.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import crime_risk_analyzer
import crime_risk_analyzer.istat as istat_pkg
from crime_risk_analyzer.istat.mapping import HAZARD_MAPPING

_DATA_DIR = Path(istat_pkg.__file__).parent


def _json(name: str) -> dict[str, Any]:
    return json.loads((_DATA_DIR / name).read_text(encoding="utf-8"))


def test_file_size() -> None:
    offences = (_DATA_DIR / "delitti.json").stat().st_size
    places = (_DATA_DIR / "luoghi.json").stat().st_size
    assert offences <= 2_000_000 and places <= 2_000_000
    assert offences + places <= 3_000_000


def test_offences_header() -> None:
    d = _json("delitti.json")
    assert (d["dataset"], d["anno"], d["anno_confronto"]) == ("73_67", 2024, 2014)
    assert d["licenza"] == "CC BY 4.0"
    assert d["url"].startswith("https://esploradati.istat.it/SDMXWS/rest/data/")


def test_items_are_the_mapped_ones_plus_the_total() -> None:
    mapped = {m.voce_istat for m in HAZARD_MAPPING.values() if m.voce_istat}
    assert set(_json("delitti.json")["voci"]) == mapped | {"TOT"}


def test_dataset_territories() -> None:
    values = _json("delitti.json")["valori"]
    provinces = [c for c in values if c.startswith("IT") and len(c) == 5]
    municipalities = [c for c in values if len(c) == 6 and c.isdigit()]
    assert (len(provinces), len(municipalities)) == (106, 108)
    assert "IT" in values


def test_every_mapped_item_has_the_reference_year_everywhere() -> None:
    d = _json("delitti.json")
    for place, by_item in d["valori"].items():
        for item in d["voci"]:
            assert by_item[item]["2024"] is not None, (place, item)


def test_every_dataset_code_has_a_polygon() -> None:
    codes = set(_json("delitti.json")["valori"]) - {"IT"}
    places = _json("luoghi.json")["luoghi"]
    assert {place["codice"] for place in places} == codes
    assert len(places) == 214


def test_municipalities_carry_the_dataset_province() -> None:
    places = _json("luoghi.json")["luoghi"]
    provinces = {x["codice"] for x in places if x["tipo"] == "provincia"}
    for x in places:
        if x["tipo"] == "comune":
            assert x["provincia"] in provinces, x["codice"]
            assert x["nome"].startswith("Comune di ")


def test_geometries_are_multipolygon_in_italian_lon_lat() -> None:
    for x in _json("luoghi.json")["luoghi"]:
        assert x["geometria"]["type"] == "MultiPolygon"
        min_lon, min_lat, max_lon, max_lat = x["bbox"]
        assert 6.0 <= min_lon <= max_lon <= 19.0, x["codice"]
        assert 35.0 <= min_lat <= max_lat <= 48.0, x["codice"]


def test_the_runtime_does_not_import_the_geometry_libraries() -> None:
    """The boundary libraries are dev-only, for the script (decision 6)."""
    stem = Path(crime_risk_analyzer.__file__).parent
    for py in stem.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for lib in ("shapefile", "pyproj", "shapely"):
            assert f"import {lib}" not in text, (py, lib)
            assert f"from {lib}" not in text, (py, lib)
