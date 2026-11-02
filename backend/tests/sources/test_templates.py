"""Downloadable CSV templates (#415)."""

from __future__ import annotations

import csv
import io
from dataclasses import replace

import pytest

from crime_risk_analyzer.sources.parsing import check_sources
from crime_risk_analyzer.sources.templates import (
    TEMPLATE_NAMES,
    TemplateName,
    template_csv,
    template_filename,
)
from tests.sources._factories import VOCABULARY, valid_files

_HEADERS: dict[str, list[str]] = {
    "osm_table": ["osm_tag", "classe"],
    "data": [
        "luogo",
        "voce",
        "voce_etichetta",
        "anno",
        "delitti",
        "tasso",
        "tasso_sotto_soglia",
    ],
    "hazard_table": [
        "hazard",
        "voce",
        "corrispondenza",
        "serie_non_confrontabile",
        "nota",
    ],
}


def test_template_names() -> None:
    assert set(TEMPLATE_NAMES) == {"osm_table", "data", "hazard_table"}


@pytest.mark.parametrize("name", sorted(_HEADERS))
def test_correct_header(name: TemplateName) -> None:
    rows = list(csv.reader(io.StringIO(template_csv(name))))
    assert rows[0] == _HEADERS[name]
    assert len(rows) >= 2  # at least one example row
    assert all(len(r) == len(rows[0]) for r in rows)


@pytest.mark.parametrize("name", sorted(_HEADERS))
def test_template_reread_without_format_errors(name: TemplateName) -> None:
    files = replace(valid_files(), **{name: template_csv(name).encode("utf-8")})
    _, report = check_sources(files, VOCABULARY)
    format_codes = {
        "colonna_mancante",
        "colonna_in_piu",
        "separatore_non_valido",
        "codifica_non_valida",
        "file_vuoto",
        "file_senza_righe",
        "riga_malformata",
        "osm_tag_non_valido",
        "valore_non_valido",
        "corrispondenza_non_valida",
        "codice_non_valido",
        "testo_non_ammesso",
        "voce_corrispondenza_incoerenti",
    }
    problems = [p for p in report.errors + report.warnings if p.code in format_codes]
    assert problems == []


def test_complete_data_template_is_valid_as_example_set() -> None:
    """The data template has a national row and a total: it is a complete file."""
    files = replace(valid_files(), data=template_csv("data").encode("utf-8"))
    _, report = check_sources(files, VOCABULARY)
    assert not [p for p in report.errors if p.file == "data"]


def test_downloadable_file_name() -> None:
    assert template_filename("osm_table") == "modello_osm_table.csv"
    assert template_filename("data") == "modello_data.csv"
    assert template_filename("hazard_table") == "modello_hazard_table.csv"


def test_unknown_name() -> None:
    with pytest.raises(ValueError):
        template_csv("boundaries")  # pyright: ignore[reportArgumentType]
