"""Tests for the reduced Turtle fixture, faithful to the real OWL pattern (#78).

The ``fixtures/ontology_sample.ttl`` fixture is a minimal but faithful excerpt
of the ENEA TERMINUS Crime ontology (Minardi et al., real file
``ontology/terminus-crime.owl``, ghost/gitignored). It serves CI/tests without
depending on the full real ontology and is the basis on which #76 will build the
SPARQL executor: for this reason the names (namespace, classes, properties) and
the restriction idiom MUST match the real ones, not invented ones.

These tests verify *semantic properties of the graph* (triples, restrictions
reachable via the real pattern and via ``rdfs:subClassOf*``), not the Turtle
text: rdflib does not guarantee a stable ordering of blank nodes. They do NOT
implement the SPARQL executor #76 — here we only check, at graph level, that
the expected pattern is present and extractable with the canonical query shape
(``backend/sparql.md``).
"""

from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from crime_risk_analyzer.ontology import load_ontology
from crime_risk_analyzer.ontology_namespaces import TERMINUS, TERMINUS_IRI

FIXTURE = Path(__file__).parent / "fixtures" / "ontology_sample.ttl"


def _term(name: str) -> str:
    return f"{TERMINUS_IRI}#{name}"


def _restriction_fillers(graph: Graph, poi: str, prop: str) -> set[str]:
    """Fillers reachable from ``poi`` for the property ``prop``.

    Uses the canonical query shape from ``backend/sparql.md``: the
    ``rdfs:subClassOf*`` closure on the POI class followed by the
    ``owl:Restriction`` pattern (``owl:onProperty`` + ``owl:someValuesFrom``).
    It is the same shape that #76 will implement in parametrized form; here it
    stays inline as a graph check.
    """
    rows = graph.query(
        """
        SELECT DISTINCT ?filler WHERE {
            ?poi rdfs:subClassOf* ?c .
            ?c rdfs:subClassOf ?r .
            ?r a owl:Restriction ;
               owl:onProperty ?prop ;
               owl:someValuesFrom ?filler .
        }
        """,
        initNs={"rdfs": RDFS, "owl": OWL},
        initBindings={"poi": TERMINUS[poi], "prop": TERMINUS[prop]},
    )
    return {str(row.filler) for row in rows}  # type: ignore[attr-defined]


def test_fixture_loads_with_production_loader() -> None:
    """The fixture is valid Turtle, loadable by the production loader."""
    graph = load_ontology(str(FIXTURE))

    assert isinstance(graph, Graph)
    assert len(graph) > 0


def test_fixture_size_in_acceptance_range() -> None:
    """50-100 triples: minimal but complete in the pattern (AC #78)."""
    graph = load_ontology(str(FIXTURE))

    assert 50 <= len(graph) <= 100


def test_uses_real_enea_namespace() -> None:
    """The entities use the real ENEA IRI, not a placeholder."""
    graph = load_ontology(str(FIXTURE))
    subjects = {str(s) for s in graph.subjects(RDF.type, OWL.Class)}

    assert _term("Bank") in subjects
    assert all(
        "example.org" not in s and "untitled-ontology-34" not in s for s in subjects
    )


def test_poi_classes_typed_as_system() -> None:
    """POIs are ``rdfs:subClassOf tc:System`` (real typing, #79)."""
    graph = load_ontology(str(FIXTURE))
    system = TERMINUS["System"]

    for poi in ("Bank", "Archaeological_site", "Petrol_station"):
        assert (TERMINUS[poi], RDFS.subClassOf, system) in graph


def test_bank_hazard_via_restriction() -> None:
    """``Bank_robbery`` is reachable from ``Bank`` via owl:Restriction/havingHazard."""
    graph = load_ontology(str(FIXTURE))

    hazards = _restriction_fillers(graph, "Bank", "havingHazard")

    assert _term("Bank_robbery") in hazards


def test_archaeological_site_hazards_via_restriction() -> None:
    """Second POI: ``Archaeological_site`` → two hazards via restriction."""
    graph = load_ontology(str(FIXTURE))

    hazards = _restriction_fillers(graph, "Archaeological_site", "havingHazard")

    assert _term("Terrorist_attack") in hazards
    assert _term("Theft_of_ancient_artifacts") in hazards


def test_petrol_station_banknote_acceptor_theft() -> None:
    """``Banknote_acceptor_theft`` is a hazard of its real POI (Petrol_station).

    Tracked divergence: the spec/issue associated it with ``Bank``, but in the
    real ontology it is a ``havingHazard`` of ``Petrol_station`` (Bank's hazards
    are Bank_robbery, ATM_removal, ...). The fixture stays faithful to the real
    graph.
    """
    graph = load_ontology(str(FIXTURE))

    hazards = _restriction_fillers(graph, "Petrol_station", "havingHazard")

    assert _term("Banknote_acceptor_theft") in hazards


def test_second_object_property_isvulnerableto() -> None:
    """Coverage of the second object property on the POI: ``isVulnerableTo``."""
    graph = load_ontology(str(FIXTURE))

    vulns = _restriction_fillers(graph, "Bank", "isVulnerableTo")

    assert _term("Poor_surveillance") in vulns


def test_havingvulnerability_present_on_system_aspect() -> None:
    """The ``havingVulnerability`` property is present (on the real System_aspect).

    In the real pattern ``havingVulnerability`` links a ``System_aspect`` (e.g.
    Bank_branch) to a Vulnerability, while the POI uses ``isVulnerableTo``.
    """
    graph = load_ontology(str(FIXTURE))

    vulns = _restriction_fillers(graph, "Bank_branch", "havingVulnerability")

    assert _term("Poor_surveillance") in vulns


def test_transitive_subclassof_hazard_hierarchy() -> None:
    """Real hierarchy ``Banknote_acceptor_theft → Theft → Anthropic_hazard``.

    Basis for the transitive inheritance (``subClassOf*``) test of #76.
    """
    graph = load_ontology(str(FIXTURE))

    ancestors = set(
        graph.transitive_objects(TERMINUS["Banknote_acceptor_theft"], RDFS.subClassOf)
    )

    assert TERMINUS["Theft"] in ancestors
    assert TERMINUS["Anthropic_hazard"] in ancestors


def test_no_invented_rdfs_labels() -> None:
    """The real ontology has no rdfs:label: the fixture does not invent any."""
    graph = load_ontology(str(FIXTURE))

    labels = list(graph.triples((None, RDFS.label, None)))

    assert labels == []


def test_hazard_typed_as_anthropic_hazard() -> None:
    """Hazards are typed with their real parent ``Anthropic_hazard``."""
    graph = load_ontology(str(FIXTURE))
    anthropic = TERMINUS["Anthropic_hazard"]

    assert (TERMINUS["Bank_robbery"], RDFS.subClassOf, anthropic) in graph
    assert (TERMINUS["Terrorist_attack"], RDFS.subClassOf, anthropic) in graph


def test_restriction_not_direct_triple() -> None:
    """Risks are NOT direct triples ``?poi tc:havingHazard ?h`` (real shape)."""
    graph = load_ontology(str(FIXTURE))

    direct = list(graph.triples((TERMINUS["Bank"], TERMINUS["havingHazard"], None)))

    assert direct == []
    # ...but the hazard is still reachable via restriction.
    assert _restriction_fillers(graph, "Bank", "havingHazard") != set()


def test_no_unused_object_property_named_uri() -> None:
    """Guard: the havingHazard URI used is exactly the real ENEA one."""
    assert TERMINUS["havingHazard"] == URIRef(_term("havingHazard"))
