"""Test dell'endpoint di health-check."""

from typing import cast

import httpx
from fastapi.testclient import TestClient

from crime_risk_analyzer.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    # `cast` + ignore puntuale: Starlette TestClient eredita da httpx.Client ma
    # con questa combinazione di versioni il tipo di `.get` non è risolto da
    # pyright strict (difetto di stub di terze parti). Si ancora il risultato
    # senza indebolire il type-checking altrove nel progetto.
    response = cast(httpx.Response, client.get("/health"))  # pyright: ignore[reportUnknownMemberType]

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    # `ontology_triples` riflette il grafo iniettato via Depends(get_ontology):
    # l'ontologia di test ha almeno una tripla.
    assert isinstance(payload["ontology_triples"], int)
    assert payload["ontology_triples"] > 0
    assert set(payload) == {"status", "ontology_triples"}


def test_lifespan_loads_ontology() -> None:
    """Avviando l'app via TestClient il lifespan carica l'ontologia (fail-fast).

    Versione rafforzata: non chiama ``get_ontology()`` a mano prima di entrare nel
    contesto, così l'unico modo perché la cache risulti popolata è che il warm-up
    avvenga nel ``lifespan``. Senza warm-up ``currsize`` resterebbe 0 (RED reale).
    """
    from fastapi.testclient import TestClient

    from crime_risk_analyzer.main import app
    from crime_risk_analyzer.ontology import get_ontology

    get_ontology.cache_clear()
    assert get_ontology.cache_info().currsize == 0
    with TestClient(app):  # entra/esce dal lifespan
        # Nessuna chiamata esplicita: se la cache è popolata, l'ha fatto il lifespan.
        assert get_ontology.cache_info().currsize == 1
        graph = get_ontology()
        assert len(graph) > 0
    get_ontology.cache_clear()
