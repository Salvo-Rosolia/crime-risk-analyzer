"""Forma e dimensione dei file dati ISTAT committati (#345, spec 4.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import crime_risk_analyzer
import crime_risk_analyzer.istat as istat_pkg
from crime_risk_analyzer.istat.mappatura import MAPPATURA

_CARTELLA = Path(istat_pkg.__file__).parent


def _json(nome: str) -> dict[str, Any]:
    return json.loads((_CARTELLA / nome).read_text(encoding="utf-8"))


def test_dimensione_dei_file() -> None:
    delitti = (_CARTELLA / "delitti.json").stat().st_size
    luoghi = (_CARTELLA / "luoghi.json").stat().st_size
    assert delitti <= 2_000_000 and luoghi <= 2_000_000
    assert delitti + luoghi <= 3_000_000


def test_intestazione_di_delitti() -> None:
    d = _json("delitti.json")
    assert (d["dataset"], d["anno"], d["anno_confronto"]) == ("73_67", 2024, 2014)
    assert d["licenza"] == "CC BY 4.0"
    assert d["url"].startswith("https://esploradati.istat.it/SDMXWS/rest/data/")


def test_voci_sono_le_mappate_piu_il_totale() -> None:
    mappate = {m.voce_istat for m in MAPPATURA.values() if m.voce_istat}
    assert set(_json("delitti.json")["voci"]) == mappate | {"TOT"}


def test_territori_del_dataset() -> None:
    valori = _json("delitti.json")["valori"]
    province = [c for c in valori if c.startswith("IT") and len(c) == 5]
    comuni = [c for c in valori if len(c) == 6 and c.isdigit()]
    assert (len(province), len(comuni)) == (106, 108)
    assert "IT" in valori


def test_ogni_voce_mappata_ha_l_anno_di_riferimento_ovunque() -> None:
    d = _json("delitti.json")
    for luogo, per_voce in d["valori"].items():
        for voce in d["voci"]:
            assert per_voce[voce]["2024"] is not None, (luogo, voce)


def test_ogni_codice_del_dataset_ha_un_poligono() -> None:
    codici = set(_json("delitti.json")["valori"]) - {"IT"}
    luoghi = _json("luoghi.json")["luoghi"]
    assert {luogo["codice"] for luogo in luoghi} == codici
    assert len(luoghi) == 214


def test_comuni_portano_la_provincia_del_dataset() -> None:
    luoghi = _json("luoghi.json")["luoghi"]
    province = {x["codice"] for x in luoghi if x["tipo"] == "provincia"}
    for x in luoghi:
        if x["tipo"] == "comune":
            assert x["provincia"] in province, x["codice"]
            assert x["nome"].startswith("Comune di ")


def test_geometrie_sono_multipolygon_in_lon_lat_italiane() -> None:
    for x in _json("luoghi.json")["luoghi"]:
        assert x["geometria"]["type"] == "MultiPolygon"
        min_lon, min_lat, max_lon, max_lat = x["bbox"]
        assert 6.0 <= min_lon <= max_lon <= 19.0, x["codice"]
        assert 35.0 <= min_lat <= max_lat <= 48.0, x["codice"]


def test_il_runtime_non_importa_le_librerie_geometriche() -> None:
    """Le librerie dei confini sono solo dev, per lo script (decisione 6)."""
    radice = Path(crime_risk_analyzer.__file__).parent
    for py in radice.rglob("*.py"):
        testo = py.read_text(encoding="utf-8")
        for lib in ("shapefile", "pyproj", "shapely"):
            assert f"import {lib}" not in testo, (py, lib)
            assert f"from {lib}" not in testo, (py, lib)
