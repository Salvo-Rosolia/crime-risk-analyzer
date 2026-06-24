"""Test della single source of truth per IRI/namespace dell'ontologia (#75).

Il modulo :mod:`crime_risk_analyzer.ontology_namespaces` e' l'unica sorgente
di verita' dell'IRI ENEA reale, condivisa tra tool offline (#74), loader runtime
e futuro executor SPARQL (#76). Questi test bloccano l'IRI atteso e il contratto
del :class:`rdflib.Namespace` (item access e attribute access producono lo stesso
:class:`~rdflib.URIRef`), su cui #76 costruira' i termini delle query.
"""

from rdflib import Namespace, URIRef

from crime_risk_analyzer.ontology_namespaces import (
    TERMINUS,
    TERMINUS_IRI,
    TERMINUS_PREFIX,
)

EXPECTED_IRI = "http://www.enea-terin-sen-apic.it/TERMINUS-crime-v01"


def test_terminus_iri_is_real_enea_iri() -> None:
    """``TERMINUS_IRI`` e' l'IRI ENEA reale, senza il ``#`` finale."""
    assert TERMINUS_IRI == EXPECTED_IRI
    assert not TERMINUS_IRI.endswith("#")


def test_terminus_prefix_is_tc() -> None:
    """Il prefisso leggibile legato all'IRI ENEA e' ``tc``."""
    assert TERMINUS_PREFIX == "tc"


def test_terminus_namespace_is_rdflib_namespace_with_hash() -> None:
    """``TERMINUS`` e' un :class:`rdflib.Namespace` su ``{IRI}#``."""
    assert isinstance(TERMINUS, Namespace)
    assert str(TERMINUS) == f"{EXPECTED_IRI}#"


def test_terminus_term_resolution_item_and_attribute() -> None:
    """Item access e attribute access danno lo stesso URIRef ``{IRI}#term``."""
    expected = URIRef(f"{EXPECTED_IRI}#havingHazard")
    assert TERMINUS["havingHazard"] == expected
    assert TERMINUS.havingHazard == expected
