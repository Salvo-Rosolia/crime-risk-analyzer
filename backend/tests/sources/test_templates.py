"""Modelli CSV scaricabili (#415)."""

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
from tests.sources._fattorie import VOCABOLARIO, file_validi

_INTESTAZIONI: dict[str, list[str]] = {
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


def test_nomi_dei_modelli() -> None:
    assert set(TEMPLATE_NAMES) == {"osm_table", "data", "hazard_table"}


@pytest.mark.parametrize("name", sorted(_INTESTAZIONI))
def test_intestazione_giusta(name: TemplateName) -> None:
    righe = list(csv.reader(io.StringIO(template_csv(name))))
    assert righe[0] == _INTESTAZIONI[name]
    assert len(righe) >= 2  # almeno una riga d'esempio
    assert all(len(r) == len(righe[0]) for r in righe)


@pytest.mark.parametrize("name", sorted(_INTESTAZIONI))
def test_modello_riletto_senza_errori_di_formato(name: TemplateName) -> None:
    files = replace(file_validi(), **{name: template_csv(name).encode("utf-8")})
    _, report = check_sources(files, VOCABOLARIO)
    formato = {
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
    problemi = [p for p in report.errors + report.warnings if p.code in formato]
    assert problemi == []


def test_modello_dati_completo_e_valido_come_set_d_esempio() -> None:
    """Il modello dei dati ha una riga nazionale e un totale: e' un file completo."""
    files = replace(file_validi(), data=template_csv("data").encode("utf-8"))
    _, report = check_sources(files, VOCABOLARIO)
    assert not [p for p in report.errors if p.file == "data"]


def test_nome_file_scaricabile() -> None:
    assert template_filename("osm_table") == "modello_osm_table.csv"
    assert template_filename("data") == "modello_data.csv"
    assert template_filename("hazard_table") == "modello_hazard_table.csv"


def test_nome_ignoto() -> None:
    with pytest.raises(ValueError):
        template_csv("boundaries")  # pyright: ignore[reportArgumentType]
