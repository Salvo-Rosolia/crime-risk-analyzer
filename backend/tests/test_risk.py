"""Direct tests for the :class:`PoiRiskProfile` model (#118).

So far the profile was covered only indirectly (via the SPARQL executor and test
doubles): these tests lock down its behaviour in isolation — fields, defaults,
domain invariants — so that a regression in the model shape turns red here, not
three modules further down.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crime_risk_analyzer.models.risk import PoiRiskProfile


def test_ontology_class_is_required() -> None:
    """``ontology_class`` has no default: without it, the model cannot be built."""
    with pytest.raises(ValidationError):
        PoiRiskProfile()  # pyright: ignore[reportCallIssue]


def test_defaults_are_empty_lists_not_none() -> None:
    """No risk == empty list, never ``None`` (model contract): with only the
    TERMINUS class every dimension is ``[]`` and ``poi_name`` is None."""
    profile = PoiRiskProfile(ontology_class="Bank")

    assert profile.poi_name is None
    assert profile.hazards == []
    assert profile.critical_events == []
    assert profile.vulnerabilities == []
    assert profile.stakeholders == []
    assert profile.sparql_paths == []


def test_default_lists_are_independent_instances() -> None:
    """``default_factory`` (not a shared mutable default): mutating one
    instance's list must NOT touch another instance. Guards against the classic
    bug of a mutable default shared at class level."""
    a = PoiRiskProfile(ontology_class="Bank")
    b = PoiRiskProfile(ontology_class="Bank")

    a.hazards.append("Robbery")

    assert a.hazards == ["Robbery"]
    assert b.hazards == []
    assert a.hazards is not b.hazards


def test_preserves_all_populated_fields() -> None:
    """Every populated field is preserved verbatim (no normalization)."""
    profile = PoiRiskProfile(
        poi_name="Banca Intesa Sanpaolo",
        ontology_class="Bank",
        hazards=["Robbery", "Theft"],
        critical_events=["Cash_theft"],
        vulnerabilities=["Unattended_entrance"],
        stakeholders=["Bank_employee"],
        sparql_paths=["Bank → havingHazard → Robbery"],
    )

    assert profile.poi_name == "Banca Intesa Sanpaolo"
    assert profile.ontology_class == "Bank"
    assert profile.hazards == ["Robbery", "Theft"]
    assert profile.critical_events == ["Cash_theft"]
    assert profile.vulnerabilities == ["Unattended_entrance"]
    assert profile.stakeholders == ["Bank_employee"]
    assert profile.sparql_paths == ["Bank → havingHazard → Robbery"]


def test_has_no_numeric_danger_scoring_field() -> None:
    """Legal constraint (_project.md §Vincoli): no numeric danger scoring.
    The model exposes only anchored qualitative sets; this test turns red if
    someone reintroduces a ``score``/``risk_level`` field."""
    assert set(PoiRiskProfile.model_fields) == {
        "poi_name",
        "ontology_class",
        "hazards",
        "critical_events",
        "vulnerabilities",
        "stakeholders",
        "sparql_paths",
    }


def test_serializes_to_dict_with_all_keys() -> None:
    """``model_dump`` exposes the full shape (raw input of the citation layer)."""
    dumped = PoiRiskProfile(ontology_class="Bank", hazards=["Robbery"]).model_dump()

    assert dumped["ontology_class"] == "Bank"
    assert dumped["hazards"] == ["Robbery"]
    assert dumped["critical_events"] == []
    assert dumped["poi_name"] is None
