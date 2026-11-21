"""Downloadable templates (#415, #531): files to fill in, apart from the example set.

The CSV columns are those read by :mod:`~crime_risk_analyzer.sources.parsing`
(same constants, no copy). The example rows show the format of the values; the
templates are consistent with each other and with the ontology template, so the
four of them together pass the sources check with the default (TERMINUS)
vocabulary. CSV: ``;`` as separator and UTF-8 with BOM, so that Italian Excel
opens the columns separated (the reader accepts both ``,`` and ``;`` and ignores
the BOM); in the ``tasso`` column the decimal comma is accepted in ``;`` files.
The ontology template is Turtle, UTF-8 without BOM.
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

__all__ = [
    "TEMPLATE_NAMES",
    "CsvTemplateName",
    "TemplateName",
    "template_bytes",
    "template_csv",
    "template_filename",
    "template_media_type",
]

TemplateName = Literal["osm_table", "data", "hazard_table", "ontology"]
CsvTemplateName = Literal["osm_table", "data", "hazard_table"]
TEMPLATE_NAMES: tuple[TemplateName, ...] = get_args(TemplateName)

_BOM = b"\xef\xbb\xbf"
_DELIMITER = ";"

_MODELS: dict[CsvTemplateName, tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]] = {
    "osm_table": (
        OSM_COLUMNS,
        (("amenity=bank", "Bank"), ("amenity=hospital", "Hospital")),
    ),
    "data": (
        (*DATA_COLUMNS, *DATA_OPTIONAL_COLUMNS),
        (
            ("IT", "TOT", "totale", "2024", "2000000", "3400,0", "no"),
            ("IT", "TOT", "totale", "2014", "2100000", "3500,0", "no"),
            ("IT", "THEFT", "furti", "2024", "900000", "1500,0", "no"),
            ("IT", "THEFT", "furti", "2014", "1000000", "1700,0", "no"),
            ("001", "TOT", "totale", "2024", "5000", "4000,0", "no"),
            ("001", "TOT", "totale", "2014", "5200", "4100,0", "no"),
            ("001", "THEFT", "furti", "2024", "2000", "2500,0", "no"),
            ("001", "THEFT", "furti", "2014", "2500", "3000,0", "no"),
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

# The comments are user-facing (Italian). The namespace and the property names are
# the TERMINUS defaults of the upload form, so no extra parameter is needed.
_ONTOLOGY = """\
@prefix t:    <http://www.enea-terin-sen-apic.it/TERMINUS-crime-v01#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .

# MODELLO DI ONTOLOGIA: sostituisci le classi d'esempio con le tue.
# Il namespace "t:" e i nomi delle proprieta' (havingHazard, ...) sono quelli
# predefiniti del form di caricamento: se li cambi, indica i tuoi nel form.

<http://example.org/my-ontology> a owl:Ontology .

# Una classe di luogo (POI): il suo nome va nella colonna "classe" della tabella
# OSM. Le etichette in italiano e inglese sono facoltative.
# Ogni restrizione havingHazard collega il luogo a un rischio.
t:Bank a owl:Class ;
    rdfs:label "Banca"@it, "Bank"@en ;
    rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty t:havingHazard ; owl:someValuesFrom t:Bank_robbery ] .

t:Hospital a owl:Class ;
    rdfs:label "Ospedale"@it, "Hospital"@en ;
    rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty t:havingHazard ; owl:someValuesFrom t:Vandalism ] .

# Un rischio: il suo nome va nella colonna "hazard" della tabella dei rischi.
t:Bank_robbery a owl:Class .
t:Vandalism a owl:Class .
"""


def template_csv(name: CsvTemplateName) -> str:
    """Text of the CSV template ``name``: header plus example rows (no BOM)."""
    if name not in _MODELS:
        raise ValueError(f"modello sconosciuto: {name!r}")
    header, rows = _MODELS[name]
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=_DELIMITER, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def template_bytes(name: TemplateName) -> bytes:
    """Bytes to download: CSV in UTF-8 with BOM, ontology in UTF-8 without BOM."""
    if name == "ontology":
        return _ONTOLOGY.encode("utf-8")
    return _BOM + template_csv(name).encode("utf-8")


def template_media_type(name: TemplateName) -> str:
    """Media type of the template download."""
    if name == "ontology":
        return "text/turtle; charset=utf-8"
    return "text/csv; charset=utf-8"


def template_filename(name: TemplateName) -> str:
    """File name proposed for the download of the template."""
    extension = "ttl" if name == "ontology" else "csv"
    return f"modello_{name}.{extension}"
