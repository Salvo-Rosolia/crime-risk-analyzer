"""Test diretti del modello :class:`PoiRiskProfile` (#118).

Finora il profilo era coperto solo indirettamente (via executor SPARQL e doppi di
test): questi test ne blindano il comportamento in isolamento — campi, default,
invarianti di dominio — cosi' una regressione sullo shape del modello diventa
rossa qui, non tre moduli piu' in la'.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crime_risk_analyzer.models.risk import PoiRiskProfile


def test_terminus_class_is_required() -> None:
    """``terminus_class`` non ha default: senza, il modello non e' costruibile."""
    with pytest.raises(ValidationError):
        PoiRiskProfile()  # pyright: ignore[reportCallIssue]


def test_defaults_are_empty_lists_not_none() -> None:
    """Assenza di rischio == lista vuota, mai ``None`` (contratto del modello):
    con la sola classe TERMINUS tutte le dimensioni sono ``[]`` e ``poi_name`` None."""
    profile = PoiRiskProfile(terminus_class="Bank")

    assert profile.poi_name is None
    assert profile.hazards == []
    assert profile.critical_events == []
    assert profile.vulnerabilities == []
    assert profile.stakeholders == []
    assert profile.sparql_paths == []


def test_default_lists_are_independent_instances() -> None:
    """``default_factory`` (non un default mutabile condiviso): mutare la lista di
    un'istanza NON deve toccare un'altra istanza. Blinda contro il classico bug
    del default mutabile condiviso a livello di classe."""
    a = PoiRiskProfile(terminus_class="Bank")
    b = PoiRiskProfile(terminus_class="Bank")

    a.hazards.append("Robbery")

    assert a.hazards == ["Robbery"]
    assert b.hazards == []
    assert a.hazards is not b.hazards


def test_preserves_all_populated_fields() -> None:
    """Ogni campo popolato viene conservato verbatim (nessuna normalizzazione)."""
    profile = PoiRiskProfile(
        poi_name="Banca Intesa Sanpaolo",
        terminus_class="Bank",
        hazards=["Robbery", "Theft"],
        critical_events=["Cash_theft"],
        vulnerabilities=["Unattended_entrance"],
        stakeholders=["Bank_employee"],
        sparql_paths=["Bank → havingHazard → Robbery"],
    )

    assert profile.poi_name == "Banca Intesa Sanpaolo"
    assert profile.terminus_class == "Bank"
    assert profile.hazards == ["Robbery", "Theft"]
    assert profile.critical_events == ["Cash_theft"]
    assert profile.vulnerabilities == ["Unattended_entrance"]
    assert profile.stakeholders == ["Bank_employee"]
    assert profile.sparql_paths == ["Bank → havingHazard → Robbery"]


def test_has_no_numeric_danger_scoring_field() -> None:
    """Vincolo legale (_project.md §Vincoli): nessuno scoring numerico di
    pericolosita'. Il modello espone solo insiemi qualitativi ancorati; questo
    test diventa rosso se qualcuno reintroduce un campo ``score``/``risk_level``."""
    assert set(PoiRiskProfile.model_fields) == {
        "poi_name",
        "terminus_class",
        "hazards",
        "critical_events",
        "vulnerabilities",
        "stakeholders",
        "sparql_paths",
    }


def test_serializes_to_dict_with_all_keys() -> None:
    """``model_dump`` espone lo shape completo (input grezzo del citation layer)."""
    dumped = PoiRiskProfile(terminus_class="Bank", hazards=["Robbery"]).model_dump()

    assert dumped["terminus_class"] == "Bank"
    assert dumped["hazards"] == ["Robbery"]
    assert dumped["critical_events"] == []
    assert dumped["poi_name"] is None
