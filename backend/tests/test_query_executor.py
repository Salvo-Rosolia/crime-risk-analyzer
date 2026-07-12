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

import logging
from pathlib import Path

import pytest
from rdflib import Graph

from crime_risk_analyzer.ontology import load_ontology
from crime_risk_analyzer.ontology_namespaces import TERMINUS
from crime_risk_analyzer.sparql_module.query_executor import (
    PoiRiskProfile,
    RiskQueryExecutor,
)

QUERY_EXECUTOR_LOGGER = "crime_risk_analyzer.sparql_module.query_executor"

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


# --- Osservabilita': filler non-URIRef scartato (#116) ---------------------


def _graph_with_anonymous_union_filler() -> Graph:
    """Grafo minimale con un filler anonimo (BNode) da ``owl:unionOf``.

    ``UnionPlace`` ha una restrizione il cui ``owl:someValuesFrom`` punta a una
    classe anonima ``owl:unionOf`` (un BNode, non una ``URIRef``): e' esattamente
    il drift di ontologia che #116 vuole rendere osservabile invece di scartare
    in silenzio. ``GoodPlace`` porta invece un filler ``URIRef`` regolare, per
    verificare che il ramo valido resti intatto (nessun filler perso).

    Il prefisso ``tc:`` e' derivato dal namespace TERMINUS canonico (non
    hardcodato) per evitare drift dell'IRI.
    """
    turtle = f"""
    @prefix tc:   <{TERMINUS}> .
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

    tc:GoodPlace a owl:Class ;
        rdfs:subClassOf [ a owl:Restriction ;
            owl:onProperty tc:havingHazard ;
            owl:someValuesFrom tc:Bank_robbery ] .

    tc:UnionPlace a owl:Class ;
        rdfs:subClassOf [ a owl:Restriction ;
            owl:onProperty tc:havingHazard ;
            owl:someValuesFrom [ a owl:Class ;
                owl:unionOf ( tc:Bank_robbery tc:Terrorist_attack ) ] ] .
    """
    graph = Graph()
    graph.parse(data=turtle, format="turtle")
    return graph


def test_non_uriref_filler_logs_warning_and_is_discarded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un filler non-URIRef (BNode da unionOf) viene scartato MA con un WARNING.

    Comportamento invariato rispetto a prima (l'elemento resta fuori
    dall'indice); si aggiunge SOLO l'osservabilita': un ``owl:someValuesFrom`` su
    nodo anonimo non deve piu' sparire in silenzio mascherando un drift.
    """
    graph = _graph_with_anonymous_union_filler()

    with caplog.at_level(logging.WARNING, logger=QUERY_EXECUTOR_LOGGER):
        executor = RiskQueryExecutor(graph)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, "atteso esattamente un WARNING per il filler anonimo"

    message = warnings[0].getMessage()
    # Contesto sufficiente a diagnosticare quale triple / quale valore:
    assert "non-URIRef" in message  # il motivo dello scarto
    assert "UnionPlace" in message  # quale classe/triple
    assert "havingHazard" in message  # quale property
    assert "BNode" in message  # il tipo del valore offensivo (quale valore)

    # Comportamento invariato: il filler anonimo NON entra nell'indice...
    assert executor.profile("UnionPlace").hazards == []
    # ...mentre il ramo valido (filler URIRef) resta intatto.
    assert "Bank_robbery" in executor.profile("GoodPlace").hazards


def test_all_uriref_restrictions_emit_no_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Nessun WARNING quando tutti i termini delle restrizioni sono ``URIRef``.

    Sulla fixture reale (tutti filler ``URIRef``) l'indicizzazione resta
    silenziosa: il log e' un segnale di drift dell'ontologia, non rumore di
    routine a ogni startup.
    """
    with caplog.at_level(logging.WARNING, logger=QUERY_EXECUTOR_LOGGER):
        RiskQueryExecutor(load_ontology(str(FIXTURE)))

    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []
