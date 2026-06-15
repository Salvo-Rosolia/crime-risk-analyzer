"""Configurazione condivisa dei test.

Prima che venga costruita qualsiasi ``Settings``, punta ``ONTOLOGY_PATH`` alla
fixture Turtle committata: il warm-up del ``lifespan`` (e ``get_ontology``)
trovano un grafo valido anche prima che il professore consegni l'ontologia
reale. ``setdefault`` non sovrascrive un valore già presente nell'ambiente.
"""

import os
from pathlib import Path

_FIXTURE = Path(__file__).parent / "fixtures" / "ontology_sample.ttl"
os.environ.setdefault("ONTOLOGY_PATH", str(_FIXTURE))
