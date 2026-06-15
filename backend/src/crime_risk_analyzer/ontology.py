"""Caricamento dell'ontologia TERMINUS Crime a runtime.

L'ontologia è un file Turtle statico fornito dal relatore, caricato una volta
in un grafo ``rdflib`` e mantenuto in memoria per tutta la sessione. Tre
responsabilità separate: ``load_ontology`` (funzione pura), ``get_ontology``
(provider cached per la dependency injection) e il warm-up fail-fast invocato
nel ``lifespan`` di ``main.py``.
"""

from functools import lru_cache
from pathlib import Path

from rdflib import Graph

from crime_risk_analyzer.config import get_settings


class OntologyLoadError(RuntimeError):
    """Ontologia non caricabile: file mancante, Turtle malformato o grafo vuoto."""


def load_ontology(path: str) -> Graph:
    """Carica e valida l'ontologia ``.ttl`` da ``path``.

    Funzione pura: nessuno stato, nessuna cache. Solleva :class:`OntologyLoadError`
    se il file non esiste, se il Turtle è malformato o se il grafo è vuoto.
    """
    if not Path(path).is_file():
        raise OntologyLoadError(f"Ontologia non trovata: {path!r}")

    graph = Graph()
    try:
        graph.parse(path, format="turtle")
    except Exception as exc:  # rdflib solleva diversi tipi su Turtle malformato
        raise OntologyLoadError(f"Ontologia .ttl malformata: {path!r}") from exc

    if len(graph) == 0:
        raise OntologyLoadError(f"Ontologia vuota (0 triple): {path!r}")

    return graph


@lru_cache
def get_ontology() -> Graph:
    """Provider cached del grafo ontologico (singleton).

    Legge il path da :func:`get_settings`, carica una sola volta e riusa lo
    stesso grafo. Iniettabile con ``Depends(get_ontology)`` e overridabile nei
    test via ``get_ontology.cache_clear()``.
    """
    return load_ontology(get_settings().ontology_path)
