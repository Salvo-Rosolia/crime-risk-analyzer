"""Test del loader dell'ontologia TERMINUS Crime."""

from pathlib import Path

from rdflib import Graph

from crime_risk_analyzer.ontology import load_ontology

FIXTURE = Path(__file__).parent / "fixtures" / "ontology_sample.ttl"


def test_load_ontology_valid() -> None:
    """Con una fixture .ttl valida ritorna un Graph non vuoto."""
    graph = load_ontology(str(FIXTURE))

    assert isinstance(graph, Graph)
    assert len(graph) > 0
