"""Test della fixture Turtle ridotta ma fedele al pattern OWL reale (#78).

La fixture ``fixtures/ontology_sample.ttl`` e' un estratto minimale ma fedele
dell'ontologia TERMINUS Crime ENEA (Minardi et al., file reale
``ontology/terminus-crime.owl``, ghost/gitignored). Serve a CI/test senza
dipendere dall'ontologia reale completa
ed e' la base su cui #76 costruira' l'executor SPARQL: per questo i nomi
(namespace, classi, property) e l'idioma delle restrizioni DEVONO combaciare con
quelli reali, non inventati.

Questi test verificano *proprieta' semantiche del grafo* (triple, restrizioni
raggiungibili via il pattern reale e via ``rdfs:subClassOf*``), non il testo del
Turtle: rdflib non garantisce un ordinamento stabile dei blank node. NON
implementano l'executor SPARQL #76 — qui si verifica solo a livello di grafo che
il pattern atteso sia presente ed estraibile con la forma di query canonica
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
    """Filler raggiungibili da ``poi`` per la property ``prop``.

    Usa la forma di query canonica di ``backend/sparql.md``: chiusura
    ``rdfs:subClassOf*`` sulla classe POI seguita dal pattern a ``owl:Restriction``
    (``owl:onProperty`` + ``owl:someValuesFrom``). E' la stessa forma che #76
    implementera' parametrizzata; qui resta inline come verifica del grafo.
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
    """La fixture e' Turtle valido, caricabile dal loader di produzione."""
    graph = load_ontology(str(FIXTURE))

    assert isinstance(graph, Graph)
    assert len(graph) > 0


def test_fixture_size_in_acceptance_range() -> None:
    """50-100 triple: minimale ma completa nel pattern (AC #78)."""
    graph = load_ontology(str(FIXTURE))

    assert 50 <= len(graph) <= 100


def test_uses_real_enea_namespace() -> None:
    """Le entita' usano l'IRI ENEA reale, non un placeholder."""
    graph = load_ontology(str(FIXTURE))
    subjects = {str(s) for s in graph.subjects(RDF.type, OWL.Class)}

    assert _term("Bank") in subjects
    assert all(
        "example.org" not in s and "untitled-ontology-34" not in s for s in subjects
    )


def test_poi_classes_typed_as_system() -> None:
    """I POI sono ``rdfs:subClassOf tc:System`` (tipizzazione reale, #79)."""
    graph = load_ontology(str(FIXTURE))
    system = TERMINUS["System"]

    for poi in ("Bank", "Archaeological_site", "Petrol_station"):
        assert (TERMINUS[poi], RDFS.subClassOf, system) in graph


def test_bank_hazard_via_restriction() -> None:
    """Da ``Bank`` si raggiunge ``Bank_robbery`` via owl:Restriction su havingHazard."""
    graph = load_ontology(str(FIXTURE))

    hazards = _restriction_fillers(graph, "Bank", "havingHazard")

    assert _term("Bank_robbery") in hazards


def test_archaeological_site_hazards_via_restriction() -> None:
    """Secondo POI: ``Archaeological_site`` → due hazard via restrizione."""
    graph = load_ontology(str(FIXTURE))

    hazards = _restriction_fillers(graph, "Archaeological_site", "havingHazard")

    assert _term("Terrorist_attack") in hazards
    assert _term("Theft_of_ancient_artifacts") in hazards


def test_petrol_station_banknote_acceptor_theft() -> None:
    """``Banknote_acceptor_theft`` e' un hazard del suo POI reale (Petrol_station).

    Divergenza tracciata: spec/issue lo associavano a ``Bank``, ma nell'ontologia
    reale e' un ``havingHazard`` di ``Petrol_station`` (gli hazard di Bank sono
    Bank_robbery, ATM_removal, ...). La fixture resta fedele al grafo reale.
    """
    graph = load_ontology(str(FIXTURE))

    hazards = _restriction_fillers(graph, "Petrol_station", "havingHazard")

    assert _term("Banknote_acceptor_theft") in hazards


def test_second_object_property_isvulnerableto() -> None:
    """Copertura della seconda object property sul POI: ``isVulnerableTo``."""
    graph = load_ontology(str(FIXTURE))

    vulns = _restriction_fillers(graph, "Bank", "isVulnerableTo")

    assert _term("Poor_surveillance") in vulns


def test_havingvulnerability_present_on_system_aspect() -> None:
    """La property ``havingVulnerability`` e' presente (sul System_aspect reale).

    Nel pattern reale ``havingVulnerability`` lega un ``System_aspect`` (es.
    Bank_branch) a una Vulnerability, mentre il POI usa ``isVulnerableTo``.
    """
    graph = load_ontology(str(FIXTURE))

    vulns = _restriction_fillers(graph, "Bank_branch", "havingVulnerability")

    assert _term("Poor_surveillance") in vulns


def test_transitive_subclassof_hazard_hierarchy() -> None:
    """Gerarchia reale ``Banknote_acceptor_theft → Theft → Anthropic_hazard``.

    Base per il test di ereditarieta' transitiva (``subClassOf*``) di #76.
    """
    graph = load_ontology(str(FIXTURE))

    ancestors = set(
        graph.transitive_objects(TERMINUS["Banknote_acceptor_theft"], RDFS.subClassOf)
    )

    assert TERMINUS["Theft"] in ancestors
    assert TERMINUS["Anthropic_hazard"] in ancestors


def test_no_invented_rdfs_labels() -> None:
    """L'ontologia reale non ha rdfs:label: la fixture non ne inventa."""
    graph = load_ontology(str(FIXTURE))

    labels = list(graph.triples((None, RDFS.label, None)))

    assert labels == []


def test_hazard_typed_as_anthropic_hazard() -> None:
    """Gli hazard sono tipizzati con il loro parent reale ``Anthropic_hazard``."""
    graph = load_ontology(str(FIXTURE))
    anthropic = TERMINUS["Anthropic_hazard"]

    assert (TERMINUS["Bank_robbery"], RDFS.subClassOf, anthropic) in graph
    assert (TERMINUS["Terrorist_attack"], RDFS.subClassOf, anthropic) in graph


def test_restriction_not_direct_triple() -> None:
    """I rischi NON sono triple dirette ``?poi tc:havingHazard ?h`` (forma reale)."""
    graph = load_ontology(str(FIXTURE))

    direct = list(graph.triples((TERMINUS["Bank"], TERMINUS["havingHazard"], None)))

    assert direct == []
    # ...ma l'hazard resta raggiungibile via restrizione.
    assert _restriction_fillers(graph, "Bank", "havingHazard") != set()


def test_no_unused_object_property_named_uri() -> None:
    """Guard: l'URI di havingHazard usato e' esattamente quello ENEA reale."""
    assert TERMINUS["havingHazard"] == URIRef(_term("havingHazard"))
