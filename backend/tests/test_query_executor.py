"""Test dell'executor SPARQL sul pattern OWL restriction (#76).

Tutti i test girano sulla fixture ridotta ma fedele ``fixtures/ontology_sample.ttl``
(#78), caricata col loader di produzione. La fixture e' verificata classe-per-classe
contro l'ontologia reale ``ontology/terminus-crime.owl`` (ghost): namespace, nomi di
classe/property e idioma ``owl:Restriction`` combaciano col reale.

Si verifica il contratto pubblico di
:mod:`crime_risk_analyzer.sparql_module.query_executor`: l'indice
:class:`RiskQueryExecutor` si costruisce una volta sul grafo, poi ``profile(classe)``
restituisce hazard / critical event / vulnerabilita' / stakeholder estratti via il
pattern a restrizione + ``rdfs:subClassOf*`` (ereditarieta' transitiva), con
``sparql_path`` come citazione lineare a un salto per il citation layer.
"""

from pathlib import Path

import pytest

from crime_risk_analyzer.ontology import load_ontology
from crime_risk_analyzer.sparql_module.query_executor import (
    PoiRiskProfile,
    RiskQueryExecutor,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ontology_sample.ttl"


@pytest.fixture(scope="module")
def executor() -> RiskQueryExecutor:
    """Executor costruito una volta sul grafo della fixture (build-once)."""
    return RiskQueryExecutor(load_ontology(str(FIXTURE)))


# --- Bank: caso principale -------------------------------------------------


def test_bank_hazards_at_least_two_real_values(executor: RiskQueryExecutor) -> None:
    """``Bank`` -> hazard reali >=2: ``Bank_robbery`` e ``Customer_robbery``."""
    profile = executor.profile("Bank")

    assert "Bank_robbery" in profile.hazards
    assert "Customer_robbery" in profile.hazards
    assert len(profile.hazards) >= 2


def test_bank_critical_events(executor: RiskQueryExecutor) -> None:
    """``Bank`` -> critical event reale ``Hostages`` via havingCriticalEvent."""
    profile = executor.profile("Bank")

    assert "Hostages" in profile.critical_events


def test_bank_vulnerabilities_via_is_vulnerable_to(
    executor: RiskQueryExecutor,
) -> None:
    """``Bank`` -> vulnerabilita' via ``isVulnerableTo`` (property POI reale)."""
    profile = executor.profile("Bank")

    assert "Poor_surveillance" in profile.vulnerabilities
    assert "Bank_in_isolated_area" in profile.vulnerabilities


def test_bank_stakeholders_via_having_performer(executor: RiskQueryExecutor) -> None:
    """``Bank`` -> stakeholder reale ``Bank_customer`` via havingPerformer."""
    profile = executor.profile("Bank")

    assert "Bank_customer" in profile.stakeholders


def test_bank_terminus_class_echoed(executor: RiskQueryExecutor) -> None:
    """Il profilo riporta la classe TERMINUS interrogata."""
    profile = executor.profile("Bank")

    assert profile.terminus_class == "Bank"


# --- Archaeological_site ---------------------------------------------------


def test_archaeological_site_hazards(executor: RiskQueryExecutor) -> None:
    """``Archaeological_site`` -> Terrorist_attack + Theft_of_ancient_artifacts."""
    profile = executor.profile("Archaeological_site")

    assert "Terrorist_attack" in profile.hazards
    assert "Theft_of_ancient_artifacts" in profile.hazards


def test_archaeological_site_stakeholder_and_vulnerability(
    executor: RiskQueryExecutor,
) -> None:
    """``Archaeological_site`` -> stakeholder ``Visitor`` e vuln. isolata."""
    profile = executor.profile("Archaeological_site")

    assert "Visitor" in profile.stakeholders
    assert "Archaeological_site_in_isolated_area" in profile.vulnerabilities


# --- Petrol_station --------------------------------------------------------


def test_petrol_station_banknote_acceptor_theft(executor: RiskQueryExecutor) -> None:
    """``Petrol_station`` -> ``Banknote_acceptor_theft`` (home reale, NON Bank)."""
    profile = executor.profile("Petrol_station")

    assert "Banknote_acceptor_theft" in profile.hazards


def test_banknote_acceptor_theft_not_on_bank(executor: RiskQueryExecutor) -> None:
    """Divergenza riconciliata: ``Banknote_acceptor_theft`` NON e' un hazard di Bank."""
    profile = executor.profile("Bank")

    assert "Banknote_acceptor_theft" not in profile.hazards


# --- Ereditarieta' transitiva subClassOf* ----------------------------------


def test_transitive_inheritance_does_not_leak_ancestor_classes(
    executor: RiskQueryExecutor,
) -> None:
    """Gli hazard sono i *filler* delle restrizioni, non gli antenati di classe.

    La gerarchia reale ``Banknote_acceptor_theft -> Theft -> Anthropic_hazard``
    serve a chiudere ``subClassOf*`` sulle CLASSI POI, non a promuovere i parent
    degli hazard a hazard: ``Theft``/``Anthropic_hazard`` non devono comparire.
    """
    profile = executor.profile("Petrol_station")

    assert "Banknote_acceptor_theft" in profile.hazards
    assert "Theft" not in profile.hazards
    assert "Anthropic_hazard" not in profile.hazards


# --- Vulnerabilita': UNION isVulnerableTo + havingVulnerability -------------


def test_system_aspect_having_vulnerability_collected(
    executor: RiskQueryExecutor,
) -> None:
    """Sul ``System_aspect`` (Bank_branch) la vuln. arriva via ``havingVulnerability``.

    La query delle vulnerabilita' raccoglie ENTRAMBE le property (isVulnerableTo
    a livello POI + havingVulnerability a livello System_aspect) per non perdere
    filler.
    """
    profile = executor.profile("Bank_branch")

    assert "Poor_surveillance" in profile.vulnerabilities


# --- Casi vuoti senza eccezioni --------------------------------------------


def test_generic_urban_poi_returns_empty_without_exception(
    executor: RiskQueryExecutor,
) -> None:
    """``GenericUrbanPOI`` (fallback non mappato) -> tutto vuoto, nessuna eccezione."""
    profile = executor.profile("GenericUrbanPOI")

    assert profile.hazards == []
    assert profile.critical_events == []
    assert profile.vulnerabilities == []
    assert profile.stakeholders == []
    assert profile.sparql_paths == []


def test_nonexistent_class_returns_empty_without_exception(
    executor: RiskQueryExecutor,
) -> None:
    """Classe inesistente nell'ontologia -> profilo vuoto, nessuna eccezione."""
    profile = executor.profile("Klingon_embassy")

    assert profile.hazards == []
    assert profile.critical_events == []
    assert profile.vulnerabilities == []
    assert profile.stakeholders == []


# --- sparql_path: citazione lineare a un salto -----------------------------


def test_sparql_path_is_single_hop_citation(executor: RiskQueryExecutor) -> None:
    """``sparql_path``: una voce per filler, forma ``Classe → property → entita``.

    Glyph arrow Unicode "→" (U+2192), byte-identico allo schema canonico di
    ``sparql.md`` / ``orchestrator.md`` / ``grounding.md`` (citation layer #24).
    """
    profile = executor.profile("Bank")

    assert "Bank → havingHazard → Bank_robbery" in profile.sparql_paths
    assert "Bank → havingCriticalEvent → Hostages" in profile.sparql_paths
    assert "Bank → havingPerformer → Bank_customer" in profile.sparql_paths
    assert "Bank → isVulnerableTo → Poor_surveillance" in profile.sparql_paths


def test_sparql_path_uses_unicode_arrow_not_ascii(
    executor: RiskQueryExecutor,
) -> None:
    """Separatore arrow Unicode "→", mai l'ASCII "->" (byte-consistency citation)."""
    profile = executor.profile("Bank")

    assert profile.sparql_paths  # non vuoto
    assert all("→" in path and "->" not in path for path in profile.sparql_paths)


def test_sparql_path_count_matches_bank_fillers(executor: RiskQueryExecutor) -> None:
    """Per Bank (nessun filler condiviso tra le vuln-property) un path per filler."""
    profile = executor.profile("Bank")

    total = (
        len(profile.hazards)
        + len(profile.critical_events)
        + len(profile.vulnerabilities)
        + len(profile.stakeholders)
    )
    assert len(profile.sparql_paths) == total


# --- Contratto del modello -------------------------------------------------


def test_profile_is_pydantic_model_with_expected_fields(
    executor: RiskQueryExecutor,
) -> None:
    """L'output e' un :class:`PoiRiskProfile` con i campi dello schema sparql.md."""
    profile = executor.profile("Bank")

    assert isinstance(profile, PoiRiskProfile)
    dumped = profile.model_dump()
    assert set(dumped) == {
        "poi_name",
        "terminus_class",
        "hazards",
        "critical_events",
        "vulnerabilities",
        "stakeholders",
        "sparql_paths",
    }


def test_poi_name_optional_passthrough(executor: RiskQueryExecutor) -> None:
    """``poi_name`` opzionale: se fornito viene riportato nel profilo."""
    profile = executor.profile("Bank", poi_name="Banca Intesa Sanpaolo")

    assert profile.poi_name == "Banca Intesa Sanpaolo"


# --- Build-once: l'indice non ricarica/ri-indicizza per richiesta ----------


def test_executor_reuses_index_across_profiles(executor: RiskQueryExecutor) -> None:
    """Lo stesso executor risponde a piu' POI senza ricostruire l'indice."""
    bank = executor.profile("Bank")
    petrol = executor.profile("Petrol_station")

    assert bank.terminus_class == "Bank"
    assert petrol.terminus_class == "Petrol_station"
    assert bank.hazards != petrol.hazards
