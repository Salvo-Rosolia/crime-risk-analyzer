"""Downloadable CSV templates (#415): the right header and a few example rows.

The columns are those read by :mod:`~crime_risk_analyzer.sources.parsing`
(same constants, no copy). The example rows show the format of the
values with generic names: they must be replaced with those of the uploaded ontology.
Comma as separator, UTF-8, LF rows.
"""

from __future__ import annotations

import csv
import io
from typing import Literal, get_args

from crime_risk_analyzer.sources.parsing import (
    DATA_COLUMNS,
    DATA_OPTIONAL_COLUMNS,
    HAZARD_COLUMNS,
    HAZARD_OPTIONAL_COLUMNS,
    OSM_COLUMNS,
)

__all__ = ["TEMPLATE_NAMES", "TemplateName", "template_csv", "template_filename"]

TemplateName = Literal["osm_table", "data", "hazard_table"]
TEMPLATE_NAMES: tuple[TemplateName, ...] = get_args(TemplateName)

_MODELS: dict[TemplateName, tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]] = {
    "osm_table": (
        OSM_COLUMNS,
        (("amenity=bank", "Bank"), ("amenity=hospital", "Hospital")),
    ),
    "data": (
        (*DATA_COLUMNS, *DATA_OPTIONAL_COLUMNS),
        (
            ("IT", "TOT", "totale", "2024", "2000000", "3400.0", "no"),
            ("IT", "TOT", "totale", "2014", "2100000", "3500.0", "no"),
            ("IT", "THEFT", "furti", "2024", "900000", "1500.0", "no"),
            ("IT", "THEFT", "furti", "2014", "1000000", "1700.0", "no"),
            ("001", "TOT", "totale", "2024", "5000", "4000.0", "no"),
            ("001", "TOT", "totale", "2014", "5200", "4100.0", "no"),
            ("001", "THEFT", "furti", "2024", "2000", "2500.0", "no"),
            ("001", "THEFT", "furti", "2014", "2500", "3000.0", "no"),
        ),
    ),
    "hazard_table": (
        (*HAZARD_COLUMNS, *HAZARD_OPTIONAL_COLUMNS),
        (
            ("Bank_robbery", "THEFT", "piu_larga", "no", ""),
            ("Vandalism", "", "", "si", "Nessuna voce adeguata"),
        ),
    ),
}


def template_csv(name: TemplateName) -> str:
    """Text of the template ``name``: header plus example rows."""
    if name not in _MODELS:
        raise ValueError(f"modello sconosciuto: {name!r}")
    header, rows = _MODELS[name]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def template_filename(name: TemplateName) -> str:
    """File name proposed for the download of the template."""
    return f"modello_{name}.csv"
