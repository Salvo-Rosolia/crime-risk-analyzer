"""``build_source_set``: executor on the set vocabulary and ``kind`` (#417)."""

from crime_risk_analyzer.sources.build import build_source_set
from crime_risk_analyzer.sources.context import DEFAULT_ID
from crime_risk_analyzer.sources.parsing import ParsedSources, read_sources
from tests.sources._factories import VOCABULARY, valid_files


def _parsed() -> ParsedSources:
    parsed, _ = read_sources(valid_files(), VOCABULARY)
    return parsed


def test_set_executor_uses_the_loaded_vocabulary() -> None:
    profile = build_source_set(_parsed()).executor.profile("Banca")
    assert profile.hazards == ["Rapina"]
    assert profile.sparql_paths == ["Banca → hasRisk → Rapina"]


def test_default_kind_is_custom_with_new_id() -> None:
    a, b = build_source_set(_parsed()), build_source_set(_parsed())
    assert a.kind == "custom"
    assert a.id != b.id
    assert a.id != DEFAULT_ID


def test_example_kind_has_fixed_id() -> None:
    ss = build_source_set(_parsed(), kind="example")
    assert ss.kind == "example"
    assert ss.id == "example"
