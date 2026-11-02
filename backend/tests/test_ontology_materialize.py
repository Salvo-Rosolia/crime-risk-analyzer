"""Tests for the OWL (RDF/XML) -> Turtle materialization (#74).

The tests do NOT depend on the real 1.6MB .owl file (gitignored, absent in CI):
they use a small tracked OWL fixture (``fixtures/ontology_small.owl``) with a
``Bank`` class carrying TWO ``owl:Restriction`` on rdfs:subClassOf
(``havingHazard someValuesFrom Bank_robbery`` and ``isVulnerableTo someValuesFrom
Robbery_vulnerability``), as in the real pattern with several nested blank nodes.
They check semantic properties (triples, SPARQL queries, prefix bindings), not
the exact Turtle text: rdflib does not guarantee a stable ordering of blank
nodes.
"""

from pathlib import Path

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDFS

from crime_risk_analyzer.ontology import load_ontology
from crime_risk_analyzer.ontology_materialize import (
    MaterializeError,
    main,
    materialize_owl_to_ttl,
)
from crime_risk_analyzer.ontology_namespaces import TERMINUS_IRI, TERMINUS_PREFIX

FIXTURE_OWL = Path(__file__).parent / "fixtures" / "ontology_small.owl"
FIXTURE_EMPTY_OWL = Path(__file__).parent / "fixtures" / "ontology_empty.owl"


def test_materialize_produces_valid_reloadable_ttl(tmp_path: Path) -> None:
    """The conversion produces a valid TTL, reloadable by the loader."""
    out = tmp_path / "out.ttl"

    result = materialize_owl_to_ttl(str(FIXTURE_OWL), str(out))

    assert result == str(out)
    assert out.is_file()
    # Reloadable with the production loader (valid, non-empty Turtle).
    graph = load_ontology(str(out))
    assert len(graph) > 0


def test_restriction_pattern_survives_round_trip(tmp_path: Path) -> None:
    """Both restrictions on Bank survive the round-trip.

    The Bank class carries TWO nested ``owl:Restriction`` blank nodes on
    rdfs:subClassOf, on different properties. Parametrized SPARQL queries on the
    produced TTL: the Bank class must be linked both to the Bank_robbery hazard
    (havingHazard) and to the Robbery_vulnerability vulnerability
    (isVulnerableTo).

    NB: transitive inheritance over subClassOf* (e.g. hazards inherited from
    superclasses) is *runtime query* semantics and NOT a goal of #74 (pure
    syntactic conversion) — it is covered by story #76.
    """
    out = tmp_path / "out.ttl"
    materialize_owl_to_ttl(str(FIXTURE_OWL), str(out))

    graph = Graph()
    graph.parse(str(out), format="turtle")

    def fillers(prop: str) -> set[str]:
        query = graph.query(
            """
            SELECT ?cls ?filler WHERE {
                ?cls rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty ?prop ;
                    owl:someValuesFrom ?filler
                ] .
            }
            """,
            initNs={"rdfs": RDFS, "owl": OWL},
            initBindings={"prop": URIRef(f"{TERMINUS_IRI}#{prop}")},
        )
        return {str(row.filler) for row in query}  # type: ignore[attr-defined]

    hazards = fillers("havingHazard")
    vulnerabilities = fillers("isVulnerableTo")

    assert f"{TERMINUS_IRI}#Bank_robbery" in hazards
    assert f"{TERMINUS_IRI}#Robbery_vulnerability" in vulnerabilities
    # Negative assertion: POI carries no havingHazard restriction of its own
    # (subClassOf* inheritance is query semantics — non-goal of #74, #76).
    assert f"{TERMINUS_IRI}#POI" not in hazards


def test_terminus_prefix_is_bound(tmp_path: Path) -> None:
    """The ``tc`` prefix is bound to the real ENEA IRI in the produced TTL.

    *Semantic* assertion on the namespace bindings after reload, not on the
    Turtle text (consistent with the test module docstring).
    """
    out = tmp_path / "out.ttl"
    materialize_owl_to_ttl(str(FIXTURE_OWL), str(out))

    graph = Graph()
    graph.parse(str(out), format="turtle")
    namespaces = dict(graph.namespaces())

    assert namespaces.get(TERMINUS_PREFIX) == URIRef(f"{TERMINUS_IRI}#")


def test_misleading_default_namespace_not_bound(tmp_path: Path) -> None:
    """No namespace of the produced TTL points to untitled-ontology-34.

    *Semantic* check on the bindings (not on the text). It holds because in the
    fixture no entity uses the legacy ``untitled-ontology-34`` namespace and
    rdflib does not emit unused prefixes — see the comment in
    ``materialize_owl_to_ttl``.
    """
    out = tmp_path / "out.ttl"
    materialize_owl_to_ttl(str(FIXTURE_OWL), str(out))

    graph = Graph()
    graph.parse(str(out), format="turtle")

    assert not any(
        "untitled-ontology-34" in str(ns) for _prefix, ns in graph.namespaces()
    )


def test_missing_source_raises(tmp_path: Path) -> None:
    """Missing source -> MaterializeError with the path in the message."""
    out = tmp_path / "out.ttl"
    with pytest.raises(MaterializeError, match="non trovato"):
        materialize_owl_to_ttl("does/not/exist.owl", str(out))


def test_malformed_owl_raises(tmp_path: Path) -> None:
    """Broken XML -> MaterializeError mentioning the failed RDF/XML parse."""
    bad = tmp_path / "bad.owl"
    bad.write_text("<rdf:RDF><owl:Class rdf:about='x'>", encoding="utf-8")
    out = tmp_path / "out.ttl"

    with pytest.raises(MaterializeError, match="RDF/XML"):
        materialize_owl_to_ttl(str(bad), str(out))


def test_empty_graph_raises(tmp_path: Path) -> None:
    """Valid OWL but 0 triples -> MaterializeError (contract symmetric to loader)."""
    out = tmp_path / "out.ttl"

    with pytest.raises(MaterializeError, match="vuot"):
        materialize_owl_to_ttl(str(FIXTURE_EMPTY_OWL), str(out))
    # No output written if the graph is empty (failure before serialize).
    assert not out.exists()


def test_cli_main_ok(tmp_path: Path) -> None:
    """CLI: with valid --src/--out it writes the TTL and returns exit code 0."""
    out = tmp_path / "cli.ttl"

    code = main(["--src", str(FIXTURE_OWL), "--out", str(out)])

    assert code == 0
    assert out.is_file()
    assert len(load_ontology(str(out))) > 0


def test_cli_main_missing_source_returns_1(tmp_path: Path) -> None:
    """CLI: missing source -> exit code 1 (no exception propagated)."""
    code = main(["--src", "does/not/exist.owl", "--out", str(tmp_path / "x.ttl")])

    assert code == 1
