"""Downloadable CSV templates (#415)."""

from __future__ import annotations

import csv
import io
from dataclasses import replace

import pytest

from crime_risk_analyzer.sources.parsing import UploadedFiles, check_sources
from crime_risk_analyzer.sources.templates import (
    TEMPLATE_NAMES,
    CsvTemplateName,
    TemplateName,
    template_bytes,
    template_csv,
    template_filename,
    template_media_type,
)
from tests.sources._factories import VOCABULARY, boundaries_json, valid_files

BOM = b"\xef\xbb\xbf"

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
    assert set(TEMPLATE_NAMES) == {"osm_table", "data", "hazard_table", "ontology"}


@pytest.mark.parametrize("name", sorted(_HEADERS))
def test_correct_header(name: CsvTemplateName) -> None:
    rows = list(csv.reader(io.StringIO(template_csv(name)), delimiter=";"))
    assert rows[0] == _HEADERS[name]
    assert len(rows) >= 2  # at least one example row
    assert all(len(r) == len(rows[0]) for r in rows)


@pytest.mark.parametrize("name", sorted(_HEADERS))
def test_template_reread_without_format_errors(name: TemplateName) -> None:
    files = replace(valid_files(), **{name: template_bytes(name)})
    _, report = check_sources(files, VOCABULARY)
    format_codes = {
        "colonna_mancante",
        "colonna_in_piu",
        "separatore_non_valido",
        "separatore_ambiguo",
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
    files = replace(valid_files(), data=template_bytes("data"))
    _, report = check_sources(files, VOCABULARY)
    assert not [p for p in report.errors if p.file == "data"]


def test_downloadable_file_name() -> None:
    assert template_filename("osm_table") == "modello_osm_table.csv"
    assert template_filename("data") == "modello_data.csv"
    assert template_filename("hazard_table") == "modello_hazard_table.csv"
    assert template_filename("ontology") == "modello_ontology.ttl"


def test_media_types() -> None:
    assert template_media_type("data") == "text/csv; charset=utf-8"
    assert template_media_type("ontology") == "text/turtle; charset=utf-8"


@pytest.mark.parametrize("name", ["osm_table", "data", "hazard_table"])
def test_csv_templates_are_utf8_with_bom_and_semicolon(name: CsvTemplateName) -> None:
    raw = template_bytes(name)
    assert raw.startswith(BOM)
    first_line = raw.decode("utf-8-sig").splitlines()[0]
    assert ";" in first_line
    assert "," not in first_line


@pytest.mark.parametrize("name", ["osm_table", "hazard_table"])
def test_csv_templates_are_short(name: CsvTemplateName) -> None:
    assert len(template_csv(name).splitlines()) <= 4  # header + 2-3 rows


def test_ontology_template_has_no_bom() -> None:
    assert not template_bytes("ontology").startswith(BOM)


def test_all_templates_together_pass_the_sources_check() -> None:
    """Default (TERMINUS) vocabulary, no extra parameters: no errors."""
    files = UploadedFiles(
        ontology=template_bytes("ontology"),
        ontology_name="modello_ontology.ttl",
        osm_table=template_bytes("osm_table"),
        data=template_bytes("data"),
        hazard_table=template_bytes("hazard_table"),
        boundaries=boundaries_json(),
    )
    parsed, report = check_sources(files)
    assert report.errors == []
    # Only the expected label fallbacks (the hazard classes have no labels).
    assert [w.code for w in report.warnings] == ["etichetta_mancante"] * 2
    assert parsed is not None
    assert parsed.classes >= {"Bank", "Hospital"}
    assert parsed.osm_to_class
    assert set(parsed.osm_to_class.values()) <= parsed.classes
    assert parsed.mappatura
    assert set(parsed.mappatura) <= parsed.classes


def test_unknown_name() -> None:
    with pytest.raises(ValueError):
        template_csv("boundaries")  # pyright: ignore[reportArgumentType]
