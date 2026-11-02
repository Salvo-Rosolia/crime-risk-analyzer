"""Tests for the TERMINUS Crime ontology loader."""

from pathlib import Path

import pytest
from rdflib import Graph

from crime_risk_analyzer.ontology import (
    OntologyLoadError,
    get_ontology,
    load_ontology,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ontology_sample.ttl"


def test_load_ontology_valid() -> None:
    """A valid .ttl fixture returns a non-empty Graph."""
    graph = load_ontology(str(FIXTURE))

    assert isinstance(graph, Graph)
    assert len(graph) > 0


def test_load_ontology_missing_file() -> None:
    """Missing file → OntologyLoadError with the path in the message."""
    with pytest.raises(OntologyLoadError, match="non trovata"):
        load_ontology("does/not/exist.ttl")


def test_load_ontology_malformed(tmp_path: Path) -> None:
    """Malformed Turtle → OntologyLoadError."""
    bad = tmp_path / "bad.ttl"
    bad.write_text("this is <not> valid turtle @@@", encoding="utf-8")

    with pytest.raises(OntologyLoadError, match="malformata"):
        load_ontology(str(bad))


def test_load_ontology_empty(tmp_path: Path) -> None:
    """Valid but empty Turtle (0 triples) → OntologyLoadError."""
    empty = tmp_path / "empty.ttl"
    empty.write_text("", encoding="utf-8")

    with pytest.raises(OntologyLoadError, match="vuota"):
        load_ontology(str(empty))


def test_get_ontology_cached() -> None:
    """get_ontology() always returns the same instance (lru_cache)."""
    get_ontology.cache_clear()

    first = get_ontology()
    second = get_ontology()

    assert isinstance(first, Graph)
    assert first is second
    assert len(first) > 0

    get_ontology.cache_clear()
