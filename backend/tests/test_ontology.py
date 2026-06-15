"""Test del loader dell'ontologia TERMINUS Crime."""

from pathlib import Path

import pytest
from rdflib import Graph

from crime_risk_analyzer.ontology import OntologyLoadError, load_ontology

FIXTURE = Path(__file__).parent / "fixtures" / "ontology_sample.ttl"


def test_load_ontology_valid() -> None:
    """Con una fixture .ttl valida ritorna un Graph non vuoto."""
    graph = load_ontology(str(FIXTURE))

    assert isinstance(graph, Graph)
    assert len(graph) > 0


def test_load_ontology_missing_file() -> None:
    """File inesistente → OntologyLoadError con il path nel messaggio."""
    with pytest.raises(OntologyLoadError, match="non trovata"):
        load_ontology("does/not/exist.ttl")


def test_load_ontology_malformed(tmp_path: Path) -> None:
    """Turtle malformato → OntologyLoadError."""
    bad = tmp_path / "bad.ttl"
    bad.write_text("this is <not> valid turtle @@@", encoding="utf-8")

    with pytest.raises(OntologyLoadError, match="malformata"):
        load_ontology(str(bad))


def test_load_ontology_empty(tmp_path: Path) -> None:
    """Turtle valido ma vuoto (0 triple) → OntologyLoadError."""
    empty = tmp_path / "empty.ttl"
    empty.write_text("", encoding="utf-8")

    with pytest.raises(OntologyLoadError, match="vuota"):
        load_ontology(str(empty))
