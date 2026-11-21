"""The Sources page legend must not drift from the parser (#538).

The columns and allowed values written in the frontend legend live in a shared
JSON file under ``frontend/`` (so that touching it also runs the frontend lane).
This module checks that the file matches what the parser really accepts; the
frontend spec checks that the legend matches the same file.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from crime_risk_analyzer.sources import parsing
from crime_risk_analyzer.sources.parsing import check_sources
from tests.sources._factories import (
    BOUNDARIES,
    HAZARD_CSV,
    VOCABULARY,
    boundaries_json,
    with_fields,
)

CONTRACT_PATH = (
    Path(__file__).resolve().parents[3]
    / "frontend/src/app/features/panels/sources/sources-contract.json"
)


def _load_contract() -> dict[str, Any]:
    if not CONTRACT_PATH.is_file():
        raise RuntimeError(
            f"legend contract not found at {CONTRACT_PATH}: these tests need the "
            "whole repository checkout (the file lives under frontend/)"
        )
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


CONTRACT: dict[str, Any] = _load_contract()

_PARSER_COLUMNS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "osm_table": (parsing.OSM_COLUMNS, ()),
    "data": (parsing.DATA_COLUMNS, parsing.DATA_OPTIONAL_COLUMNS),
    "hazard_table": (parsing.HAZARD_COLUMNS, parsing.HAZARD_OPTIONAL_COLUMNS),
}

_VALID_PROPERTIES = {
    "codice": "001",
    "tipo": "comune",
    "nome": "Comune di Esempio",
    "nome_breve": "Esempio",
}


@pytest.mark.parametrize("name", sorted(_PARSER_COLUMNS))
def test_csv_columns_match_the_parser(name: str) -> None:
    required, optional = _PARSER_COLUMNS[name]
    assert tuple(CONTRACT[name]["required"]) == required
    assert tuple(CONTRACT[name]["optional"]) == optional


def _error_codes(properties: dict[str, str]) -> list[str]:
    document: dict[str, Any] = copy.deepcopy(BOUNDARIES)
    document["features"][0]["properties"] = properties
    files = with_fields(boundaries=boundaries_json(document))
    _, report = check_sources(files, VOCABULARY)
    return [problem.code for problem in report.errors]


def test_boundaries_accept_exactly_the_contract_properties() -> None:
    required = CONTRACT["boundaries"]["required"]
    assert set(required) == set(_VALID_PROPERTIES)
    properties = {name: _VALID_PROPERTIES[name] for name in required}
    assert _error_codes(properties) == []
    (optional,) = CONTRACT["boundaries"]["optional"]
    assert _error_codes({**properties, optional: "058"}) == []


@pytest.mark.parametrize("missing", sorted(_VALID_PROPERTIES))
def test_boundaries_require_every_contract_property(missing: str) -> None:
    assert missing in CONTRACT["boundaries"]["required"]
    properties = {k: v for k, v in _VALID_PROPERTIES.items() if k != missing}
    assert "confini_non_validi" in _error_codes(properties)


def _hazard_error_codes(match: str) -> list[str]:
    table = HAZARD_CSV.replace(",esatta,", f",{match},")
    _, report = check_sources(
        with_fields(hazard_table=table.encode("utf-8")), VOCABULARY
    )
    return [problem.code for problem in report.errors]


def test_hazard_match_values_are_the_contract_ones() -> None:
    for match in CONTRACT["values"]["corrispondenza"]:
        assert _hazard_error_codes(match) == [], match
    assert _hazard_error_codes("quasi_uguale") != []


def test_boundary_types_are_the_contract_ones() -> None:
    for kind in CONTRACT["values"]["tipo"]:
        assert _error_codes({**_VALID_PROPERTIES, "tipo": kind}) == [], kind
    assert _error_codes({**_VALID_PROPERTIES, "tipo": "regione"}) != []
