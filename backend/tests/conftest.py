"""Configurazione condivisa dei test.

Prima che venga costruita qualsiasi ``Settings``, punta ``ONTOLOGY_PATH`` alla
fixture Turtle committata: il warm-up del ``lifespan`` (e ``get_ontology``)
trovano un grafo valido anche prima che il professore consegni l'ontologia
reale. ``setdefault`` non sovrascrive un valore già presente nell'ambiente.
"""

import os
from pathlib import Path

import pytest

_FIXTURE = Path(__file__).parent / "fixtures" / "ontology_sample.ttl"
os.environ.setdefault("ONTOLOGY_PATH", str(_FIXTURE))


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skippa i test ``integration`` (rete reale) salvo selezione esplicita.

    Si eseguono solo quando l'utente passa ``-m integration`` (o un'espressione
    che lo include); la suite di default resta offline e deterministica.
    """
    expr = config.getoption("-m")
    if isinstance(expr, str) and "integration" in expr:
        return
    skip = pytest.mark.skip(reason="test di integrazione: usa -m integration")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
