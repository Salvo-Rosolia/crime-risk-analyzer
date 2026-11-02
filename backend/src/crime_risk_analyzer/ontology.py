"""Runtime loading of the TERMINUS Crime ontology.

The ontology is a static Turtle file supplied by the supervisor, loaded once
into an ``rdflib`` graph and kept in memory for the whole session. Three
separate responsibilities: ``load_ontology`` (pure function), ``get_ontology``
(cached provider for dependency injection) and the fail-fast warm-up invoked
in the ``lifespan`` of ``main.py``.
"""

from functools import lru_cache
from pathlib import Path

from rdflib import Graph

from crime_risk_analyzer.config import get_settings


class OntologyLoadError(RuntimeError):
    """Ontology not loadable: missing file, malformed Turtle or empty graph."""


def load_ontology(path: str) -> Graph:
    """Loads and validates the ``.ttl`` ontology from ``path``.

    Pure function: no state, no cache. Raises :class:`OntologyLoadError`
    if the file does not exist, if the Turtle is malformed or if the graph is empty.
    """
    if not Path(path).is_file():
        raise OntologyLoadError(f"Ontologia non trovata: {path!r}")

    graph = Graph()
    try:
        graph.parse(path, format="turtle")
    except Exception as exc:  # rdflib raises several types on malformed Turtle
        raise OntologyLoadError(f"Ontologia .ttl malformata: {path!r}") from exc

    if len(graph) == 0:
        raise OntologyLoadError(f"Ontologia vuota (0 triple): {path!r}")

    return graph


@lru_cache
def get_ontology() -> Graph:
    """Cached provider of the ontology graph (singleton).

    Reads the path from :func:`get_settings`, loads only once and reuses the
    same graph. Injectable with ``Depends(get_ontology)`` and overridable in
    tests via ``get_ontology.cache_clear()``.
    """
    return load_ontology(get_settings().ontology_path)
