"""Tests for the single source of truth for the ontology IRI/namespace (#75).

The :mod:`crime_risk_analyzer.ontology_namespaces` module is the only source
of truth for the real ENEA IRI, shared by the offline tool (#74), the runtime
loader and the future SPARQL executor (#76). These tests pin the expected IRI
and the :class:`rdflib.Namespace` contract (item access and attribute access
produce the same :class:`~rdflib.URIRef`), on which #76 will build the query
terms.
"""

from rdflib import Namespace, URIRef

from crime_risk_analyzer.ontology_namespaces import (
    TERMINUS,
    TERMINUS_IRI,
    TERMINUS_PREFIX,
)

EXPECTED_IRI = "http://www.enea-terin-sen-apic.it/TERMINUS-crime-v01"


def test_terminus_iri_is_real_enea_iri() -> None:
    """``TERMINUS_IRI`` is the real ENEA IRI, without the trailing ``#``."""
    assert TERMINUS_IRI == EXPECTED_IRI
    assert not TERMINUS_IRI.endswith("#")


def test_terminus_prefix_is_tc() -> None:
    """The readable prefix bound to the ENEA IRI is ``tc``."""
    assert TERMINUS_PREFIX == "tc"


def test_terminus_namespace_is_rdflib_namespace_with_hash() -> None:
    """``TERMINUS`` is a :class:`rdflib.Namespace` over ``{IRI}#``."""
    assert isinstance(TERMINUS, Namespace)
    assert str(TERMINUS) == f"{EXPECTED_IRI}#"


def test_terminus_term_resolution_item_and_attribute() -> None:
    """Item access and attribute access give the same URIRef ``{IRI}#term``."""
    expected = URIRef(f"{EXPECTED_IRI}#havingHazard")
    assert TERMINUS["havingHazard"] == expected
    assert TERMINUS.havingHazard == expected
