"""Test della materializzazione OWL (RDF/XML) -> Turtle (#74).

I test NON dipendono dal file .owl reale da 1.6MB (gitignored, assente in CI):
usano una fixture OWL piccola e tracciata (``fixtures/ontology_small.owl``) con
una classe ``Bank`` che porta DUE ``owl:Restriction`` su rdfs:subClassOf
(``havingHazard someValuesFrom Bank_robbery`` e ``isVulnerableTo someValuesFrom
Robbery_vulnerability``), come nel pattern reale a piu' blank node annidati. Si
verificano proprieta' semantiche (triple, query SPARQL, binding di prefisso),
non il testo esatto del Turtle: rdflib non garantisce un ordinamento stabile
dei blank node.
"""

from pathlib import Path

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDFS

from crime_risk_analyzer.ontology import load_ontology
from crime_risk_analyzer.ontology_materialize import (
    TERMINUS_IRI,
    TERMINUS_PREFIX,
    MaterializeError,
    main,
    materialize_owl_to_ttl,
)

FIXTURE_OWL = Path(__file__).parent / "fixtures" / "ontology_small.owl"
FIXTURE_EMPTY_OWL = Path(__file__).parent / "fixtures" / "ontology_empty.owl"


def test_materialize_produces_valid_reloadable_ttl(tmp_path: Path) -> None:
    """La conversione produce un TTL valido, ricaricabile dal loader."""
    out = tmp_path / "out.ttl"

    result = materialize_owl_to_ttl(str(FIXTURE_OWL), str(out))

    assert result == str(out)
    assert out.is_file()
    # Ricaricabile col loader di produzione (Turtle valido, non vuoto).
    graph = load_ontology(str(out))
    assert len(graph) > 0


def test_restriction_pattern_survives_round_trip(tmp_path: Path) -> None:
    """Entrambe le restrizioni su Bank sopravvivono al round-trip.

    La classe Bank porta DUE blank node ``owl:Restriction`` annidati su
    rdfs:subClassOf, su property diverse. Query SPARQL parametrizzate sul TTL
    prodotto: la classe Bank deve risultare legata sia all'hazard Bank_robbery
    (havingHazard) sia alla vulnerabilita' Robbery_vulnerability
    (isVulnerableTo).

    NB: l'ereditarieta' transitiva su subClassOf* (es. hazard ereditati dalle
    superclassi) e' semantica di *query a runtime* e NON e' un goal di #74
    (pura conversione sintattica) — la materializza la copre la story #76.
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
    # Asserzione negativa: POI non porta una restrizione havingHazard propria
    # (l'ereditarieta' subClassOf* e' semantica di query — non-goal di #74, #76).
    assert f"{TERMINUS_IRI}#POI" not in hazards


def test_terminus_prefix_is_bound(tmp_path: Path) -> None:
    """Il prefisso ``tc`` e' legato all'IRI ENEA reale nel TTL prodotto.

    Asserzione *semantica* sui binding di namespace dopo reload, non sul testo
    del Turtle (coerente col docstring del modulo di test).
    """
    out = tmp_path / "out.ttl"
    materialize_owl_to_ttl(str(FIXTURE_OWL), str(out))

    graph = Graph()
    graph.parse(str(out), format="turtle")
    namespaces = dict(graph.namespaces())

    assert namespaces.get(TERMINUS_PREFIX) == URIRef(f"{TERMINUS_IRI}#")


def test_misleading_default_namespace_not_bound(tmp_path: Path) -> None:
    """Nessun namespace del TTL prodotto punta a untitled-ontology-34.

    Verifica *semantica* sui binding (non sul testo). Vale perche' nella fixture
    nessuna entita' usa il namespace legacy ``untitled-ontology-34`` e rdflib
    non emette prefissi inutilizzati — vedi commento in ``materialize_owl_to_ttl``.
    """
    out = tmp_path / "out.ttl"
    materialize_owl_to_ttl(str(FIXTURE_OWL), str(out))

    graph = Graph()
    graph.parse(str(out), format="turtle")

    assert not any(
        "untitled-ontology-34" in str(ns) for _prefix, ns in graph.namespaces()
    )


def test_missing_source_raises(tmp_path: Path) -> None:
    """Sorgente inesistente -> MaterializeError con il path nel messaggio."""
    out = tmp_path / "out.ttl"
    with pytest.raises(MaterializeError, match="non trovato"):
        materialize_owl_to_ttl("does/not/exist.owl", str(out))


def test_malformed_owl_raises(tmp_path: Path) -> None:
    """XML rotto -> MaterializeError che cita il parse RDF/XML fallito."""
    bad = tmp_path / "bad.owl"
    bad.write_text("<rdf:RDF><owl:Class rdf:about='x'>", encoding="utf-8")
    out = tmp_path / "out.ttl"

    with pytest.raises(MaterializeError, match="RDF/XML"):
        materialize_owl_to_ttl(str(bad), str(out))


def test_empty_graph_raises(tmp_path: Path) -> None:
    """OWL valido ma 0 triple -> MaterializeError (contratto simmetrico al loader)."""
    out = tmp_path / "out.ttl"

    with pytest.raises(MaterializeError, match="vuot"):
        materialize_owl_to_ttl(str(FIXTURE_EMPTY_OWL), str(out))
    # Nessun output scritto se il grafo e' vuoto (fallimento prima della serialize).
    assert not out.exists()


def test_cli_main_ok(tmp_path: Path) -> None:
    """CLI: con --src/--out validi scrive il TTL e ritorna exit code 0."""
    out = tmp_path / "cli.ttl"

    code = main(["--src", str(FIXTURE_OWL), "--out", str(out)])

    assert code == 0
    assert out.is_file()
    assert len(load_ontology(str(out))) > 0


def test_cli_main_missing_source_returns_1(tmp_path: Path) -> None:
    """CLI: sorgente mancante -> exit code 1 (nessuna eccezione propagata)."""
    code = main(["--src", "does/not/exist.owl", "--out", str(tmp_path / "x.ttl")])

    assert code == 1
