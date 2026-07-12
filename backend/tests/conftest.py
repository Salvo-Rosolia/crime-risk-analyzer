"""Configurazione condivisa dei test.

Prima che venga costruita qualsiasi ``Settings``, punta ``ONTOLOGY_PATH`` alla
fixture Turtle committata: il warm-up del ``lifespan`` (e ``get_ontology``)
trovano un grafo valido anche prima che il professore consegni l'ontologia
reale. ``setdefault`` non sovrascrive un valore già presente nell'ambiente.

Il ``lifespan`` scalda anche il client LLM (fail-fast su chiave assente, #111):
senza una chiave l'avvio dell'app fallirebbe e ogni test che entra nel lifespan
via ``with TestClient(app)`` si romperebbe. Forniamo chiavi fittizie con lo
stesso ``setdefault`` usato per ``ONTOLOGY_PATH`` — nessuna rete: gli SDK
Anthropic/Groq non validano la chiave alla costruzione del client. Il test del
fail-fast rimuove la chiave in modo mirato (vedi ``test_lifespan.py``).
"""

import os
from pathlib import Path

import pytest

_FIXTURE = Path(__file__).parent / "fixtures" / "ontology_sample.ttl"
os.environ.setdefault("ONTOLOGY_PATH", str(_FIXTURE))
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")
os.environ.setdefault("GROQ_API_KEY", "gsk-test-dummy")


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
