"""Integration test del warm-up nel lifespan e del fail-fast sui segreti (#111).

Il ``lifespan`` di ``main.py`` pre-costruisce a startup le risorse costose o
critiche esposte via ``Depends``: l'ontologia, l'executor SPARQL (indice delle
restrizioni, parte costosa e POI-indipendente) e il client LLM. Cosi' la prima
``POST /analyze`` non paga il costo lazy e un misconfig (chiave LLM assente)
fallisce subito all'avvio (fail-fast), non alla prima richiesta.

Nota Starlette: solo l'uso di ``with TestClient(app)`` entra nel lifespan; gli
altri test che chiamano il client senza context manager non lo attivano, quindi
non sono toccati dal warm-up.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.llm.client import LLMError, get_llm_client
from crime_risk_analyzer.main import app
from crime_risk_analyzer.ontology import get_ontology
from crime_risk_analyzer.sparql_module.query_executor import get_executor


@pytest.fixture(autouse=True)
def _clear_di_caches() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Isola ogni test: cache dei provider DI pulite prima e dopo.

    Senza reset, l'esito dipenderebbe dall'ordine dei test (una cache popolata
    da un test precedente maschererebbe il warm-up o il fail-fast).
    """
    for cache in (get_settings, get_ontology, get_executor, get_llm_client):
        cache.cache_clear()
    yield
    for cache in (get_settings, get_ontology, get_executor, get_llm_client):
        cache.cache_clear()


def test_lifespan_warms_up_executor_and_llm_client() -> None:
    """All'avvio il lifespan costruisce executor SPARQL e client LLM (warm-up).

    Le cache partono vuote (fixture): l'unico modo perche' risultino popolate
    mentre il lifespan e' attivo e' che il warm-up sia avvenuto nello startup.
    Senza warm-up ``currsize`` resterebbe 0 (RED reale).
    """
    assert get_executor.cache_info().currsize == 0
    assert get_llm_client.cache_info().currsize == 0

    with TestClient(app):  # entra/esce dal lifespan
        assert get_executor.cache_info().currsize == 1
        assert get_llm_client.cache_info().currsize == 1


def test_lifespan_fails_fast_without_llm_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con la chiave LLM assente l'avvio dell'app fallisce (fail-fast).

    Rimuove la chiave del provider di default (claude) solo in questo test e
    forza il ricalcolo di Settings/client: entrare nel lifespan deve sollevare
    ``LLMError`` all'avvio, invece di lasciar degradare la prima ``/analyze``.
    """
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    get_llm_client.cache_clear()

    with pytest.raises(LLMError) as exc_info:
        with TestClient(app):  # il lifespan deve sollevare in fase di startup
            pass

    assert "ANTHROPIC_API_KEY" in str(exc_info.value)
