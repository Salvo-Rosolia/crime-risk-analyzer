"""Tests for the health-check endpoint."""

from typing import cast

import httpx
from fastapi.testclient import TestClient

from crime_risk_analyzer.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    # `cast` + targeted ignore: Starlette TestClient inherits from httpx.Client but
    # with this combination of versions the type of `.get` is not resolved by pyright
    # strict (third-party stub defect). The result is anchored without weakening the
    # type-checking elsewhere in the project.
    response = cast(httpx.Response, client.get("/health"))  # pyright: ignore[reportUnknownMemberType]

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    # `ontology_triples` reflects the graph injected via Depends(get_ontology): the
    # test ontology has at least one triple.
    assert isinstance(payload["ontology_triples"], int)
    assert payload["ontology_triples"] > 0
    assert set(payload) == {"status", "ontology_triples"}


def test_lifespan_loads_ontology() -> None:
    """Starting the app via TestClient the lifespan loads the ontology (fail-fast).

    Strengthened version: it does not call ``get_ontology()`` by hand before
    entering the context, so the only way for the cache to be populated is that
    the warm-up happens in the ``lifespan``. Without warm-up ``currsize`` would
    stay 0 (real RED).

    The lifespan (post-#111) also warms the SPARQL executor and the LLM client: the
    cleanup of the DI caches is symmetric on all three (setup and teardown), so the
    test leaves no populated caches nor depends on the execution order (finding C1).
    """
    from fastapi.testclient import TestClient

    from crime_risk_analyzer.llm.client import get_llm_client
    from crime_risk_analyzer.main import app
    from crime_risk_analyzer.ontology import get_ontology
    from crime_risk_analyzer.sparql_module.query_executor import get_executor

    warmed_caches = (get_ontology, get_executor, get_llm_client)
    for cache in warmed_caches:
        cache.cache_clear()
    assert get_ontology.cache_info().currsize == 0
    with TestClient(app):  # enters/exits the lifespan
        # No explicit call: if the cache is populated, the lifespan did it.
        assert get_ontology.cache_info().currsize == 1
        graph = get_ontology()
        assert len(graph) > 0
    for cache in warmed_caches:
        cache.cache_clear()
