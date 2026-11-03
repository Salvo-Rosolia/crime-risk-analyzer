"""Tests for the SPARQL executor on the OWL restriction pattern (#76).

All tests run on the reduced but faithful fixture ``fixtures/ontology_sample.ttl``
(#78), loaded with the production loader. The fixture is verified class by class
against the real ontology ``ontology/terminus-crime.owl`` (ghost): namespace,
class/property names and the ``owl:Restriction`` idiom match the real ones.

It checks the public contract of
:mod:`crime_risk_analyzer.sparql_module.query_executor`: the
:class:`RiskQueryExecutor` index is built once on the graph, then
``profile(class)`` returns hazards / critical events / vulnerabilities /
stakeholders extracted via the restriction pattern + ``rdfs:subClassOf*``
(transitive inheritance), with ``sparql_path`` as a single-hop linear citation
for the citation layer.
"""

import logging
from dataclasses import replace
from pathlib import Path

import pytest
from rdflib import Graph

from crime_risk_analyzer.ontology import load_ontology
from crime_risk_analyzer.ontology_namespaces import TERMINUS
from crime_risk_analyzer.sources.vocabulary import (
    TERMINUS_VOCABULARY,
    OntologyVocabulary,
)
from crime_risk_analyzer.sparql_module.query_executor import (
    InvalidIriError,
    PoiRiskProfile,
    RiskQueryExecutor,
)

QUERY_EXECUTOR_LOGGER = "crime_risk_analyzer.sparql_module.query_executor"

FIXTURE = Path(__file__).parent / "fixtures" / "ontology_sample.ttl"


@pytest.fixture(scope="module")
def executor() -> RiskQueryExecutor:
    """Executor built once on the fixture graph (build-once)."""
    return RiskQueryExecutor(load_ontology(str(FIXTURE)))


# --- Bank: main case -------------------------------------------------


def test_bank_hazards_at_least_two_real_values(executor: RiskQueryExecutor) -> None:
    """``Bank`` -> real hazards >=2: ``Bank_robbery`` and ``Customer_robbery``."""
    profile = executor.profile("Bank")

    assert "Bank_robbery" in profile.hazards
    assert "Customer_robbery" in profile.hazards
    assert len(profile.hazards) >= 2


def test_bank_critical_events(executor: RiskQueryExecutor) -> None:
    """``Bank`` -> real critical event ``Hostages`` via havingCriticalEvent."""
    profile = executor.profile("Bank")

    assert "Hostages" in profile.critical_events


def test_bank_vulnerabilities_via_is_vulnerable_to(
    executor: RiskQueryExecutor,
) -> None:
    """``Bank`` -> vulnerabilities via ``isVulnerableTo`` (real POI property)."""
    profile = executor.profile("Bank")

    assert "Poor_surveillance" in profile.vulnerabilities
    assert "Bank_in_isolated_area" in profile.vulnerabilities


def test_bank_stakeholders_via_having_performer(executor: RiskQueryExecutor) -> None:
    """``Bank`` -> real stakeholder ``Bank_customer`` via havingPerformer."""
    profile = executor.profile("Bank")

    assert "Bank_customer" in profile.stakeholders


def test_bank_ontology_class_echoed(executor: RiskQueryExecutor) -> None:
    """The profile reports the TERMINUS class queried."""
    profile = executor.profile("Bank")

    assert profile.ontology_class == "Bank"


# --- Archaeological_site ---------------------------------------------------


def test_archaeological_site_hazards(executor: RiskQueryExecutor) -> None:
    """``Archaeological_site`` -> Terrorist_attack + Theft_of_ancient_artifacts."""
    profile = executor.profile("Archaeological_site")

    assert "Terrorist_attack" in profile.hazards
    assert "Theft_of_ancient_artifacts" in profile.hazards


def test_archaeological_site_stakeholder_and_vulnerability(
    executor: RiskQueryExecutor,
) -> None:
    """``Archaeological_site`` -> stakeholder ``Visitor`` and isolated-area vuln."""
    profile = executor.profile("Archaeological_site")

    assert "Visitor" in profile.stakeholders
    assert "Archaeological_site_in_isolated_area" in profile.vulnerabilities


# --- Petrol_station --------------------------------------------------------


def test_petrol_station_banknote_acceptor_theft(executor: RiskQueryExecutor) -> None:
    """``Petrol_station`` -> ``Banknote_acceptor_theft`` (real home, NOT Bank)."""
    profile = executor.profile("Petrol_station")

    assert "Banknote_acceptor_theft" in profile.hazards


def test_banknote_acceptor_theft_not_on_bank(executor: RiskQueryExecutor) -> None:
    """Reconciled divergence: ``Banknote_acceptor_theft`` is NOT a Bank hazard."""
    profile = executor.profile("Bank")

    assert "Banknote_acceptor_theft" not in profile.hazards


# --- Transitive inheritance subClassOf* ------------------------------------


def test_transitive_inheritance_does_not_leak_ancestor_classes(
    executor: RiskQueryExecutor,
) -> None:
    """Hazards are the *fillers* of the restrictions, not the class ancestors.

    The real hierarchy ``Banknote_acceptor_theft -> Theft -> Anthropic_hazard``
    serves to close ``subClassOf*`` on the POI CLASSES, not to promote the
    parents of hazards to hazards: ``Theft``/``Anthropic_hazard`` must not
    appear.
    """
    profile = executor.profile("Petrol_station")

    assert "Banknote_acceptor_theft" in profile.hazards
    assert "Theft" not in profile.hazards
    assert "Anthropic_hazard" not in profile.hazards


# --- Vulnerabilities: UNION isVulnerableTo + havingVulnerability ------------


def test_system_aspect_having_vulnerability_collected(
    executor: RiskQueryExecutor,
) -> None:
    """On the ``System_aspect`` (Bank_branch) the vuln comes via havingVulnerability.

    The vulnerabilities query collects BOTH properties (isVulnerableTo at POI
    level + havingVulnerability at System_aspect level) so as not to lose
    fillers.
    """
    profile = executor.profile("Bank_branch")

    assert "Poor_surveillance" in profile.vulnerabilities


# --- Empty cases without exceptions ----------------------------------------


def test_generic_urban_poi_returns_empty_without_exception(
    executor: RiskQueryExecutor,
) -> None:
    """``GenericUrbanPOI`` (unmapped fallback) -> all empty, no exception."""
    profile = executor.profile("GenericUrbanPOI")

    assert profile.hazards == []
    assert profile.critical_events == []
    assert profile.vulnerabilities == []
    assert profile.stakeholders == []
    assert profile.sparql_paths == []


def test_nonexistent_class_returns_empty_without_exception(
    executor: RiskQueryExecutor,
) -> None:
    """Class not in the ontology -> empty profile, no exception."""
    profile = executor.profile("Klingon_embassy")

    assert profile.hazards == []
    assert profile.critical_events == []
    assert profile.vulnerabilities == []
    assert profile.stakeholders == []


# --- sparql_path: single-hop linear citation -------------------------------


def test_sparql_path_is_single_hop_citation(executor: RiskQueryExecutor) -> None:
    """``sparql_path``: one entry per filler, shape ``Class → property → entity``.

    Unicode arrow glyph "→" (U+2192), byte-identical to the canonical schema of
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
    """Unicode arrow separator "→", never the ASCII "->" (citation byte-consistency)."""
    profile = executor.profile("Bank")

    assert profile.sparql_paths  # not empty
    assert all("→" in path and "->" not in path for path in profile.sparql_paths)


def test_sparql_path_count_matches_bank_fillers(executor: RiskQueryExecutor) -> None:
    """For Bank (no filler shared between the vuln properties) one path per filler."""
    profile = executor.profile("Bank")

    total = (
        len(profile.hazards)
        + len(profile.critical_events)
        + len(profile.vulnerabilities)
        + len(profile.stakeholders)
    )
    assert len(profile.sparql_paths) == total


# --- Model contract --------------------------------------------------------


def test_profile_is_pydantic_model_with_expected_fields(
    executor: RiskQueryExecutor,
) -> None:
    """The output is a :class:`PoiRiskProfile` with the sparql.md schema fields."""
    profile = executor.profile("Bank")

    assert isinstance(profile, PoiRiskProfile)
    dumped = profile.model_dump()
    assert set(dumped) == {
        "poi_name",
        "ontology_class",
        "hazards",
        "critical_events",
        "vulnerabilities",
        "stakeholders",
        "sparql_paths",
    }


def test_poi_name_optional_passthrough(executor: RiskQueryExecutor) -> None:
    """Optional ``poi_name``: if provided it is reported in the profile."""
    profile = executor.profile("Bank", poi_name="Banca Intesa Sanpaolo")

    assert profile.poi_name == "Banca Intesa Sanpaolo"


# --- Build-once: the index does not reload/re-index per request ------------


def test_executor_reuses_index_across_profiles(executor: RiskQueryExecutor) -> None:
    """The same executor answers several POIs without rebuilding the index."""
    bank = executor.profile("Bank")
    petrol = executor.profile("Petrol_station")

    assert bank.ontology_class == "Bank"
    assert petrol.ontology_class == "Petrol_station"
    assert bank.hazards != petrol.hazards


# --- Observability: non-URIRef filler discarded (#116) ---------------------


def _graph_with_anonymous_union_filler() -> Graph:
    """Minimal graph with an anonymous filler (BNode) from ``owl:unionOf``.

    ``UnionPlace`` has a restriction whose ``owl:someValuesFrom`` points to an
    anonymous ``owl:unionOf`` class (a BNode, not a ``URIRef``): it is exactly
    the ontology drift that #116 wants to make observable instead of silently
    discarding. ``GoodPlace`` instead carries a regular ``URIRef`` filler, to
    verify that the valid branch stays intact (no filler lost).

    The ``tc:`` prefix is derived from the canonical TERMINUS namespace (not
    hardcoded) to avoid IRI drift.
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
    """A non-URIRef filler (BNode from unionOf) is discarded BUT with a WARNING.

    Behaviour unchanged from before (the element stays out of the index); ONLY
    observability is added: an ``owl:someValuesFrom`` on an anonymous node must
    no longer vanish silently, masking a drift.
    """
    graph = _graph_with_anonymous_union_filler()

    with caplog.at_level(logging.WARNING, logger=QUERY_EXECUTOR_LOGGER):
        executor = RiskQueryExecutor(graph)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, "expected exactly one WARNING for the anonymous filler"

    message = warnings[0].getMessage()
    # Enough context to diagnose which triple / which value:
    assert "non-URIRef" in message  # the reason for the discard
    assert "UnionPlace" in message  # which class/triple
    assert "havingHazard" in message  # which property
    assert "BNode" in message  # the type of the offending value (which value)

    # Behaviour unchanged: the anonymous filler does NOT enter the index...
    assert executor.profile("UnionPlace").hazards == []
    # ...while the valid branch (URIRef filler) stays intact.
    assert "Bank_robbery" in executor.profile("GoodPlace").hazards


def test_all_uriref_restrictions_emit_no_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No WARNING when all the restriction terms are ``URIRef``.

    On the real fixture (all ``URIRef`` fillers) the indexing stays silent: the
    log is a signal of ontology drift, not routine noise at every startup.
    """
    with caplog.at_level(logging.WARNING, logger=QUERY_EXECUTOR_LOGGER):
        RiskQueryExecutor(load_ontology(str(FIXTURE)))

    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


# --- Configurable namespace and properties (#412) --------------------------

ALT_NS = "http://example.org/other#"


def _alt_graph(ns: str = ALT_NS) -> Graph:
    """Fictitious ontology with namespace and property names different from TERMINUS."""
    turtle = f"""
    @prefix o:    <{ns}> .
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

    o:Parent a owl:Class ;
        rdfs:subClassOf [ a owl:Restriction ;
            owl:onProperty o:hasHazard ; owl:someValuesFrom o:Fire ] .
    o:Shop a owl:Class ;
        rdfs:subClassOf o:Parent ,
        [ a owl:Restriction ;
            owl:onProperty o:hasEvent ; owl:someValuesFrom o:Looting ] ,
        [ a owl:Restriction ;
            owl:onProperty o:hasActor ; owl:someValuesFrom o:Gang ] ,
        [ a owl:Restriction ;
            owl:onProperty o:weakTo ; owl:someValuesFrom o:NoAlarm ] ,
        [ a owl:Restriction ;
            owl:onProperty o:weakAspect ; owl:someValuesFrom o:Glass ] ,
        [ a owl:Restriction ;
            owl:onProperty o:ignored ; owl:someValuesFrom o:Noise ] .
    """
    graph = Graph()
    graph.parse(data=turtle, format="turtle")
    return graph


def _alt_vocabulary(namespace: str = ALT_NS) -> OntologyVocabulary:
    return OntologyVocabulary(
        namespace=namespace,
        hazard="hasHazard",
        critical_event="hasEvent",
        performer="hasActor",
        vulnerability=("weakTo", "weakAspect"),
    )


def test_custom_namespace_and_properties() -> None:
    executor = RiskQueryExecutor(_alt_graph(), vocabulary=_alt_vocabulary())

    profile = executor.profile("Shop")

    assert profile.hazards == ["Fire"]  # inherited from Parent
    assert profile.critical_events == ["Looting"]
    assert profile.stakeholders == ["Gang"]
    assert profile.vulnerabilities == ["Glass", "NoAlarm"]
    assert "Shop → hasEvent → Looting" in profile.sparql_paths
    assert not any("ignored" in p for p in profile.sparql_paths)


def test_custom_namespace_with_slash_separator() -> None:
    ns = "http://example.org/other/"
    executor = RiskQueryExecutor(_alt_graph(ns), vocabulary=_alt_vocabulary(ns))

    assert executor.profile("Shop").hazards == ["Fire"]


def test_default_properties_unchanged_on_alt_namespace_graph() -> None:
    """With the TERMINUS default, a graph with another namespace produces no fillers."""
    executor = RiskQueryExecutor(_alt_graph())

    assert executor.profile("Shop").hazards == []


def test_default_vocabulary_is_terminus() -> None:
    assert RiskQueryExecutor(Graph())._vocabulary == TERMINUS_VOCABULARY  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    "namespace",
    [
        "",
        "not an iri#",
        "relative/path#",
        "http://example.org/a b#",
        "http://example.org/<x>#",
        'http://example.org/"x"#',
        "http://example.org/{x}#",
        "http://example.org/x",  # does not end with # or /
        "http://example.org/x\n#",
    ],
)
def test_invalid_namespace_rejected_before_query(namespace: str) -> None:
    with pytest.raises(InvalidIriError):
        RiskQueryExecutor(Graph(), vocabulary=_alt_vocabulary(namespace))


@pytest.mark.parametrize(
    "name",
    [
        "",
        "has hazard",
        "has>Hazard",
        'a"b',
        "a{b}",
        "a|b",
        "a^b",
        "a`b",
        "a\\b",
        "a#b",
        "a/b",
        "a?b",
        "a\tb",
        "a\nb",
        "x> } DELETE WHERE { ?s ?p ?o",
    ],
)
@pytest.mark.parametrize("slot", ["hazard", "critical_event", "performer", "vuln"])
def test_invalid_property_name_rejected_before_query(name: str, slot: str) -> None:
    base = _alt_vocabulary()
    if slot == "vuln":
        vocabulary = replace(base, vulnerability=("weakTo", name))
    else:
        vocabulary = replace(base, **{slot: name})
    with pytest.raises(InvalidIriError):
        RiskQueryExecutor(Graph(), vocabulary=vocabulary)


def test_invalid_iri_error_is_value_error() -> None:
    assert issubclass(InvalidIriError, ValueError)


def test_empty_vulnerability_rejected() -> None:
    """``vulnerability=()`` is rejected up front (at least one property is needed)."""
    vocabulary = replace(_alt_vocabulary(), vulnerability=())
    with pytest.raises(InvalidIriError, match="vulnerabilita"):
        RiskQueryExecutor(Graph(), vocabulary=vocabulary)


def test_same_property_in_two_slots_is_not_rejected_and_fills_both() -> None:
    """Real behaviour: the same property in two slots is NOT rejected.

    ``problems()`` does not check for duplicates; the index maps the IRI to the
    local name and ``profile`` reads each slot by name. Here ``hasActor`` is
    assigned to both hazard and performer: the ``Gang`` filler appears in both
    lists and the real hazard ``Fire`` (``hasHazard``) is no longer read.
    """
    vocabulary = replace(_alt_vocabulary(), hazard="hasActor")
    assert vocabulary.problems() == []

    profile = RiskQueryExecutor(_alt_graph(), vocabulary=vocabulary).profile("Shop")

    assert profile.stakeholders == ["Gang"]
    assert profile.hazards == ["Gang"]


def test_non_uriref_filler_on_custom_property_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A BNode filler on a custom risk property is discarded with a WARNING."""
    turtle = f"""
    @prefix o:    <{ALT_NS}> .
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

    o:Shop a owl:Class ;
        rdfs:subClassOf [ a owl:Restriction ;
            owl:onProperty o:hasHazard ; owl:someValuesFrom o:Fire ] ,
        [ a owl:Restriction ;
            owl:onProperty o:hasEvent ;
            owl:someValuesFrom [ a owl:Class ;
                owl:unionOf ( o:Looting o:Riot ) ] ] .
    """
    graph = Graph()
    graph.parse(data=turtle, format="turtle")

    with caplog.at_level(logging.WARNING, logger=QUERY_EXECUTOR_LOGGER):
        executor = RiskQueryExecutor(graph, vocabulary=_alt_vocabulary())
    records = [r for r in caplog.records if r.levelno == logging.WARNING]

    assert len(records) == 1
    message = records[0].getMessage()
    assert "non-URIRef" in message
    assert "hasEvent" in message
    assert "BNode" in message
    profile = executor.profile("Shop")
    assert profile.critical_events == []
    assert profile.hazards == ["Fire"]
