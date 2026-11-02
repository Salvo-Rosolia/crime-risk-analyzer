# pyright: basic
"""Regenerates the ISTAT data of the ``crime_risk_analyzer.istat`` package (#345).

MANUAL script (D2): the app never calls ISTAT at runtime. It re-downloads the values
of dataset 73_67 for the reference year and for ten years earlier and rewrites
``delitti.json``; with ``--confini`` it also regenerates ``luoghi.json`` from the
ISTAT generalized administrative boundaries.

Usage (from the ``backend`` folder)::

    uv run python scripts/istat_refresh.py            # only delitti.json
    uv run python scripts/istat_refresh.py --confini  # also luoghi.json

The geometry libraries (pyshp, pyproj, shapely) are dependencies of the ``dev``
group only: they are imported inside the boundary functions, so the package runtime
does not depend on them and the crimes part also runs without them.

``# pyright: basic`` at the top: pyshp and shapely do not have complete types and in
strict mode every call would be a ``reportUnknownMemberType``; the script is not part
of the package and does not run in production.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import httpx

from crime_risk_analyzer.istat.mapping import HAZARD_MAPPING

#: Reference year ``Y`` and comparison year ``Y-10`` (spec 3).
YEAR = 2024
COMPARISON_YEAR = YEAR - 10

DATASET = "73_67"
TITLE = "Delitti denunciati dalle forze di polizia all'autorità giudiziaria"
LICENSE = "CC BY 4.0"
DATA_URL = (
    "https://esploradati.istat.it/SDMXWS/rest/data/IT1,73_67,1.0/"
    "A..CRIMEN+CRIMET..9.YRDUR?startPeriod={start}&endPeriod={end}&format=csv"
)
STRUCTURE_URL = (
    "https://esploradati.istat.it/SDMXWS/rest/dataflow/IT1/73_67/1.0?references=all"
)
BOUNDARIES_URL_2024 = (
    "https://www.istat.it/storage/cartografia/confini_amministrativi/"
    "generalizzati/2024/Limiti01012024_g.zip"
)
BOUNDARIES_URL_2001 = (
    "https://www.istat.it/storage/cartografia/confini_amministrativi/"
    "generalizzati/Limiti2001_g.zip"
)

#: Code of Italy in the dataset.
ITALY_CODE = "IT"
#: Item for the total of crimes (frame, D10).
TOTAL_ITEM = "TOT"
#: ISTAT flag "the datum does not reach half of the minimum figure considered":
#: rate shown as "meno di 0,1 ogni 100.000 abitanti" (spec 3).
BELOW_THRESHOLD_FLAG = "0"

#: ISTAT province code (COD_PROV of the 2024 boundaries) -> NUTS3 code of the dataset.
#: Built by comparing the names of the CL_ITTER107 codelist with DEN_UTS of the 2024
#: boundaries and verified by the script at every regeneration (:func:`check_names`).
#: The four historical Sardinian provinces are NOT here: see :data:`SARDINIA_2001`.
PROVINCE_NUTS: dict[int, str] = {
    1: "ITC11",
    2: "ITC12",
    3: "ITC15",
    4: "ITC16",
    5: "ITC17",
    6: "ITC18",
    7: "ITC20",
    8: "ITC31",
    9: "ITC32",
    10: "ITC33",
    11: "ITC34",
    12: "ITC41",
    13: "ITC42",
    14: "ITC44",
    15: "ITC45",
    16: "ITC46",
    17: "ITC47",
    18: "ITC48",
    19: "ITC4A",
    20: "ITC4B",
    21: "ITD10",
    22: "ITD20",
    23: "ITD31",
    24: "ITD32",
    25: "ITD33",
    26: "ITD34",
    27: "ITD35",
    28: "ITD36",
    29: "ITD37",
    30: "ITD42",
    31: "ITD43",
    32: "ITD44",
    33: "ITD51",
    34: "ITD52",
    35: "ITD53",
    36: "ITD54",
    37: "ITD55",
    38: "ITD56",
    39: "ITD57",
    40: "ITD58",
    41: "ITE31",
    42: "ITE32",
    43: "ITE33",
    44: "ITE34",
    45: "ITE11",
    46: "ITE12",
    47: "ITE13",
    48: "ITE14",
    49: "ITE16",
    50: "ITE17",
    51: "ITE18",
    52: "ITE19",
    53: "ITE1A",
    54: "ITE21",
    55: "ITE22",
    56: "ITE41",
    57: "ITE42",
    58: "ITE43",
    59: "ITE44",
    60: "ITE45",
    61: "ITF31",
    62: "ITF32",
    63: "ITF33",
    64: "ITF34",
    65: "ITF35",
    66: "ITF11",
    67: "ITF12",
    68: "ITF13",
    69: "ITF14",
    70: "ITF22",
    71: "ITF41",
    72: "ITF42",
    73: "ITF43",
    74: "ITF44",
    75: "ITF45",
    76: "ITF51",
    77: "ITF52",
    78: "ITF61",
    79: "ITF63",
    80: "ITF65",
    81: "ITG11",
    82: "ITG12",
    83: "ITG13",
    84: "ITG14",
    85: "ITG15",
    86: "ITG16",
    87: "ITG17",
    88: "ITG18",
    89: "ITG19",
    93: "ITD41",
    94: "ITF21",
    96: "ITC13",
    97: "ITC43",
    98: "ITC49",
    99: "ITD59",
    100: "ITE15",
    101: "ITF62",
    102: "ITF64",
    103: "ITC14",
    108: "IT108",
    109: "IT109",
    110: "IT110",
}

#: Sardinia rule (spec 4.1): the dataset uses the 4 historical provinces with the
#: boundaries at the beginning of 2001 (ISTAT note). Their polygons are taken from the
#: 2001 generalized boundaries (``Prov2001_g``), not from an assignment of the current
#: municipalities: this way no municipality -> historical province table is needed and
#: there is no margin of error to declare (e.g. Bosa, moved to Oristano in 2005, stays
#: in Nuoro).
SARDINIA_2001: dict[int, str] = {90: "ITG25", 91: "ITG26", 92: "ITG27", 95: "ITG28"}

#: Sardinian 2024 provinces NOT to use (replaced by the 2001 polygons).
SARDINIA_2024 = frozenset({90, 91, 92, 95, 111})

#: Full names that do not follow the "Provincia di <name>" form.
SPECIAL_FULL_NAMES: dict[str, str] = {
    "ITC20": "Valle d'Aosta",
    "ITD10": "Provincia autonoma di Bolzano",
    "ITD20": "Provincia autonoma di Trento",
}
#: Short names (the ones the narrative writes) that differ from the codelist.
SPECIAL_SHORT_NAMES: dict[str, str] = {
    "ITC20": "Valle d'Aosta",
    "ITD10": "Bolzano",
    "021008": "Bolzano",
}

#: Simplification tolerances in degrees (~200 m for provinces, ~50 m for the
#: capital municipalities, where precision at the edges matters more).
PROVINCE_TOLERANCE = 0.002
MUNICIPALITY_TOLERANCE = 0.0005
DECIMALS = 5

_NS = {
    "s": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
    "c": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
}
_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

FOLDER = Path(__file__).resolve().parents[1] / "src" / "crime_risk_analyzer" / "istat"


def requested_items() -> list[str]:
    """Items to extract: those linked to a hazard plus the total (D10)."""
    items = {m.voce_istat for m in HAZARD_MAPPING.values() if m.voce_istat}
    return sorted(items | {TOTAL_ITEM})


def is_province(code: str) -> bool:
    """Dataset provinces have a 5-character NUTS3 code (e.g. ITE43, IT108)."""
    return code.startswith("IT") and len(code) == 5


def is_municipality(code: str) -> bool:
    """Capital municipalities have the 6-digit ISTAT municipality code."""
    return len(code) == 6 and code.isdigit()


def download(url: str) -> bytes:
    """GET with a generous timeout: the ISTAT files weigh tens of MB."""
    response = httpx.get(url, timeout=300.0, follow_redirects=True)
    response.raise_for_status()
    return response.content


def codelist(xml: bytes, identifier: str) -> dict[str, str]:
    """Code -> Italian name of an SDMX codelist (e.g. CL_ITTER107)."""
    root = ET.fromstring(xml)
    out: dict[str, str] = {}
    for clist in root.iter(f"{{{_NS['s']}}}Codelist"):
        if clist.get("id") != identifier:
            continue
        for code in clist.findall("s:Code", _NS):
            names = {n.get(_LANG): n.text or "" for n in code.findall("c:Name", _NS)}
            out[str(code.get("id"))] = names.get("it") or names.get("en") or ""
    return out


def values_from_csv(
    text: str, *, years: Iterable[int], items: Iterable[str]
) -> dict[str, dict[str, dict[str, dict[str, Any] | None]]]:
    """``place -> item -> year -> {delitti, tasso, tasso_sotto_soglia}`` from SDMX CSV.

    Keeps only provinces, capital municipalities and Italy (drops regions and
    macro-areas) and only the requested ``years``/``items``. A year without
    ``CRIMEN`` stays ``None``.
    """
    years_str = {str(y) for y in years}
    items_set = set(items)
    raw: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        area = row["REF_AREA"]
        if not (area == ITALY_CODE or is_province(area) or is_municipality(area)):
            continue
        if row["TYPE_CRIME"] not in items_set or row["TIME_PERIOD"] not in years_str:
            continue
        key = (area, row["TYPE_CRIME"], row["TIME_PERIOD"])
        entry = raw.setdefault(key, {})
        value = row["OBS_VALUE"].strip()
        if row["DATA_TYPE"] == "CRIMEN":
            entry["delitti"] = int(float(value)) if value else None
        elif row["DATA_TYPE"] == "CRIMET":
            entry["tasso"] = float(value) if value else None
            entry["tasso_sotto_soglia"] = (
                not value and row["OBS_STATUS"] == BELOW_THRESHOLD_FLAG
            )
    out: dict[str, dict[str, dict[str, dict[str, Any] | None]]] = {}
    for (area, item, year), v in sorted(raw.items()):
        if v.get("delitti") is None:
            datum = None
        else:
            datum = {
                "delitti": v["delitti"],
                "tasso": v.get("tasso"),
                "tasso_sotto_soglia": bool(v.get("tasso_sotto_soglia", False)),
            }
        out.setdefault(area, {}).setdefault(item, {})[year] = datum
    for area in out:
        for item in out[area]:
            for year in sorted(years_str):
                out[area][item].setdefault(year, None)
    return out


def check_completeness(
    values: Mapping[str, Mapping[str, Mapping[str, object]]], items: Iterable[str]
) -> list[str]:
    """Blocking problems: territory counts and items without ``YEAR`` (spec 3)."""
    problems: list[str] = []
    provinces = [c for c in values if is_province(c)]
    municipalities = [c for c in values if is_municipality(c)]
    if len(provinces) != 106:
        problems.append(f"expected 106 provinces, found {len(provinces)}")
    if len(municipalities) != 108:
        problems.append(
            f"expected 108 capital municipalities, found {len(municipalities)}"
        )
    if ITALY_CODE not in values:
        problems.append("the Italy row is missing")
    for area, per_item in values.items():
        for item in items:
            if per_item.get(item, {}).get(str(YEAR)) is None:
                problems.append(f"{area}/{item}: the {YEAR} datum is missing")
    return problems


def write_json(path: Path, content: object) -> None:
    """Compact, deterministic JSON (sorted keys, UTF-8, LF)."""
    text = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def refresh_crimes(folder: Path) -> None:
    items = requested_items()
    structure = download(STRUCTURE_URL)
    labels = codelist(structure, "CL_REATI_PS")
    url = DATA_URL.format(start=COMPARISON_YEAR, end=YEAR)
    text = download(url).decode("utf-8-sig")
    values = values_from_csv(text, years=(YEAR, COMPARISON_YEAR), items=items)
    problems = check_completeness(values, items)
    if problems:
        raise SystemExit("incomplete ISTAT data:\n  " + "\n  ".join(problems))
    write_json(
        folder / "delitti.json",
        {
            "dataset": DATASET,
            "titolo": TITLE,
            "url": url,
            "estratto_il": dt.date.today().isoformat(),
            "licenza": LICENSE,
            "anno": YEAR,
            "anno_confronto": COMPARISON_YEAR,
            "voci": {v: labels[v] for v in items},
            "valori": values,
        },
    )


def _polygons(geometry: Any) -> list[Any]:
    """Only the areal parts of a geometry (make_valid may return a collection)."""
    from shapely.geometry import MultiPolygon, Polygon

    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return [p for part in getattr(geometry, "geoms", []) for p in _polygons(part)]


def _multipolygon(geometry: Any) -> dict[str, Any]:
    """Shapely geometry -> rounded GeoJSON MultiPolygon, coordinates (lon, lat)."""
    from shapely.geometry import mapping

    coordinates = [
        [
            [[round(x, DECIMALS), round(y, DECIMALS)] for x, y in ring]
            for ring in mapping(polygon)["coordinates"]
        ]
        for polygon in _polygons(geometry)
    ]
    return {"type": "MultiPolygon", "coordinates": coordinates}


def _shape(
    zip_bytes: bytes, prefix: str, folder: Path
) -> list[tuple[dict[str, Any], Any]]:
    """Record + WGS84 geometry (not simplified) of a shapefile inside the zip."""
    import shapefile
    from pyproj import Transformer
    from shapely.geometry import shape
    from shapely.ops import transform

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        archive.extractall(folder)
    base = next(folder.rglob(f"{prefix}*.shp")).with_suffix("")
    # The files are named *_WGS84 but the projection in the .prj is WGS84 UTM 32N.
    to_wgs84 = Transformer.from_crs("EPSG:32632", "EPSG:4326", always_xy=True).transform
    # ``with`` (not ``as``, whose stubs type the return as ``_HasExitStack``):
    # on Windows a .dbf left open blocks the cleanup of the tmpdir.
    reader = shapefile.Reader(str(base))
    with reader:
        result: list[tuple[dict[str, Any], Any]] = []
        for sr in reader.iterShapeRecords():
            # ``record``/``shape`` are optional only in the stub (ctor with default
            # None): ``iterShapeRecords`` always populates them.
            assert sr.record is not None and sr.shape is not None
            result.append(
                (
                    sr.record.as_dict(),
                    transform(to_wgs84, shape(sr.shape.__geo_interface__)),
                )
            )
        return result


def _place(
    code: str, name: str, kind: str, geometry: Any, tolerance: float, **extra: Any
) -> dict[str, Any]:
    from shapely.validation import make_valid

    simple = make_valid(geometry.simplify(tolerance, preserve_topology=True))
    point = geometry.representative_point()
    if not simple.contains(point):
        point = simple.representative_point()
    min_lon, min_lat, max_lon, max_lat = simple.bounds
    short = SPECIAL_SHORT_NAMES.get(code, name)
    if kind == "comune":
        full = f"Comune di {short}"
    else:
        full = SPECIAL_FULL_NAMES.get(code, f"Provincia di {short}")
    return {
        "codice": code,
        "tipo": kind,
        "nome": full,
        "nome_breve": short,
        "bbox": [
            round(min_lon, DECIMALS),
            round(min_lat, DECIMALS),
            round(max_lon, DECIMALS),
            round(max_lat, DECIMALS),
        ],
        "punto_interno": [round(point.x, DECIMALS), round(point.y, DECIMALS)],
        "geometria": _multipolygon(simple),
        **extra,
    }


def _normalize(name: str) -> str:
    import unicodedata

    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return "".join(c for c in plain.split("/")[0].lower() if c.isalpha())


def check_names(
    provinces_2024: Iterable[tuple[int, str]], dataset_names: Mapping[str, str]
) -> list[str]:
    """Cross-check of the :data:`PROVINCE_NUTS` table against the names."""
    problems: list[str] = []
    for province_code, den in provinces_2024:
        if province_code in SARDINIA_2024:
            continue
        nuts = PROVINCE_NUTS.get(province_code)
        if nuts is None:
            problems.append(f"COD_PROV {province_code} ({den}) without NUTS code")
            continue
        expected = _normalize(dataset_names.get(nuts, ""))
        if nuts == "ITC20":
            expected = "aosta"
        if _normalize(den) != expected:
            problems.append(
                f"COD_PROV {province_code}: {den!r} != "
                f"{dataset_names.get(nuts)!r} ({nuts})"
            )
    return problems


def refresh_places(folder: Path) -> None:
    structure = download(STRUCTURE_URL)
    names = codelist(structure, "CL_ITTER107")
    crimes = json.loads((folder / "delitti.json").read_text(encoding="utf-8"))
    codes = set(crimes["valori"]) - {ITALY_CODE}
    places: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        zip_2024 = download(BOUNDARIES_URL_2024)
        zip_2001 = download(BOUNDARIES_URL_2001)
        provinces = _shape(zip_2024, "ProvCM01012024_g", Path(tmp) / "2024p")
        problems = check_names(
            ((r["COD_PROV"], r["DEN_UTS"]) for r, _ in provinces), names
        )
        if problems:
            raise SystemExit("inconsistent province table:\n  " + "\n  ".join(problems))
        for record, geometry in provinces:
            if record["COD_PROV"] in SARDINIA_2024:
                continue
            nuts = PROVINCE_NUTS[record["COD_PROV"]]
            places.append(
                _place(nuts, names[nuts], "provincia", geometry, PROVINCE_TOLERANCE)
            )
        for record, geometry in _shape(zip_2001, "Prov2001_g", Path(tmp) / "2001p"):
            nuts = SARDINIA_2001.get(record["COD_PROV"])
            if nuts:
                places.append(
                    _place(nuts, names[nuts], "provincia", geometry, PROVINCE_TOLERANCE)
                )
        for record, geometry in _shape(zip_2024, "Com01012024_g", Path(tmp) / "2024c"):
            code = record["PRO_COM_T"]
            if code not in codes:
                continue
            province_code = record["COD_PROV"]
            province = SARDINIA_2001.get(province_code) or PROVINCE_NUTS[province_code]
            places.append(
                _place(
                    code,
                    names[code],
                    "comune",
                    geometry,
                    MUNICIPALITY_TOLERANCE,
                    provincia=province,
                )
            )
    found = {place["codice"] for place in places}
    if found != codes:
        raise SystemExit(
            f"missing polygons: {sorted(codes - found)}; extra: {sorted(found - codes)}"
        )
    places.sort(key=lambda place: (place["tipo"], place["codice"]))
    write_json(
        folder / "luoghi.json",
        {
            "fonte": (
                "ISTAT, confini amministrativi generalizzati al 1/1/2024 "
                "(province e comuni capoluogo) e al 2001 (le 4 province sarde storiche)"
            ),
            "url": [BOUNDARIES_URL_2024, BOUNDARIES_URL_2001],
            "licenza": LICENSE,
            "generato_il": dt.date.today().isoformat(),
            "luoghi": places,
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--confini", action="store_true", help="also regenerates luoghi.json"
    )
    parser.add_argument("--cartella", type=Path, default=FOLDER, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    refresh_crimes(args.cartella)
    if args.confini:
        refresh_places(args.cartella)
    for name in ("delitti.json", "luoghi.json"):
        path = args.cartella / name
        if path.exists():
            print(f"{name}: {path.stat().st_size / 1_000_000:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
