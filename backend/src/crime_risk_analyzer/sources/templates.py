"""Modelli CSV scaricabili (#415): intestazione giusta e qualche riga d'esempio.

Le colonne sono quelle lette da :mod:`~crime_risk_analyzer.sources.parsing`
(stesse costanti, nessuna copia). Le righe d'esempio mostrano il formato dei
valori con nomi generici: vanno sostituite con quelle dell'ontologia caricata.
Virgola come separatore, UTF-8, righe LF.
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

_MODELLI: dict[TemplateName, tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]] = {
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
    """Testo del modello ``name``: intestazione piu' righe d'esempio."""
    if name not in _MODELLI:
        raise ValueError(f"modello sconosciuto: {name!r}")
    intestazione, righe = _MODELLI[name]
    buffer = io.StringIO()
    scrittore = csv.writer(buffer, lineterminator="\n")
    scrittore.writerow(intestazione)
    scrittore.writerows(righe)
    return buffer.getvalue()


def template_filename(name: TemplateName) -> str:
    """Nome del file proposto per il download del modello."""
    return f"modello_{name}.csv"
