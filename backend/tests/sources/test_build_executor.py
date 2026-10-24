"""``build_source_set``: executor sul vocabolario del set e ``kind`` (#417)."""

from crime_risk_analyzer.sources.build import build_source_set
from crime_risk_analyzer.sources.context import DEFAULT_ID
from crime_risk_analyzer.sources.parsing import ParsedSources, read_sources
from tests.sources._fattorie import VOCABOLARIO, file_validi


def _parsed() -> ParsedSources:
    parsed, _ = read_sources(file_validi(), VOCABOLARIO)
    return parsed


def test_l_executor_del_set_usa_il_vocabolario_caricato() -> None:
    profilo = build_source_set(_parsed()).executor.profile("Banca")
    assert profilo.hazards == ["Rapina"]
    assert profilo.sparql_paths == ["Banca → hasRisk → Rapina"]


def test_kind_predefinito_custom_con_id_nuovo() -> None:
    a, b = build_source_set(_parsed()), build_source_set(_parsed())
    assert a.kind == "custom"
    assert a.id != b.id
    assert a.id != DEFAULT_ID


def test_kind_example_ha_id_fisso() -> None:
    ss = build_source_set(_parsed(), kind="example")
    assert ss.kind == "example"
    assert ss.id == "example"
