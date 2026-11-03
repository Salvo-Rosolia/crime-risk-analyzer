"""Integration test of the lifespan warm-up and of the fail-fast on secrets (#111).

The ``lifespan`` of ``main.py`` pre-builds at startup the expensive or critical
resources exposed via ``Depends``: the ontology, the SPARQL executor (index of
the restrictions, the expensive and POI-independent part) and the LLM client.
So the first ``POST /analyze`` does not pay the lazy cost and a misconfig
(missing LLM key) fails right at startup (fail-fast), not at the first request.

Starlette note: only the use of ``with TestClient(app)`` enters the lifespan;
the other tests that call the client without a context manager do not activate
it, so they are not touched by the warm-up.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer.config import Settings, get_settings
from crime_risk_analyzer.istat import data as istat_data_mod
from crime_risk_analyzer.istat.data import IstatDataError, clear_cache
from crime_risk_analyzer.llm.client import LLMError, get_llm_client
from crime_risk_analyzer.main import app
from crime_risk_analyzer.ontology import get_ontology
from crime_risk_analyzer.sparql_module.query_executor import get_executor


@pytest.fixture(autouse=True)
def _clear_caches_fixture() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Isolates every test: DI provider caches cleaned before and after.

    Without a reset, the outcome would depend on the test order (a cache populated
    by a previous test would mask the warm-up or the fail-fast).
    """
    for cache in (get_settings, get_ontology, get_executor, get_llm_client):
        cache.cache_clear()
    yield
    for cache in (get_settings, get_ontology, get_executor, get_llm_client):
        cache.cache_clear()


def test_lifespan_warms_up_executor_and_llm_client() -> None:
    """At startup the lifespan builds the SPARQL executor and the LLM client (warm-up).

    The caches start empty (fixture): the only way for them to be populated while
    the lifespan is active is that the warm-up happened in the startup.
    Without warm-up ``currsize`` would stay 0 (real RED).
    """
    assert get_executor.cache_info().currsize == 0
    assert get_llm_client.cache_info().currsize == 0

    with TestClient(app):  # enters/exits the lifespan
        assert get_executor.cache_info().currsize == 1
        assert get_llm_client.cache_info().currsize == 1


def test_lifespan_fails_fast_without_llm_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the LLM key missing the app startup fails (fail-fast).

    It removes the key of the default provider (claude) only in this test and forces
    the recomputation of Settings/client: entering the lifespan must raise
    ``LLMError`` at startup, instead of letting the first ``/analyze`` degrade.
    """
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Without it, the key of a local ``backend/.env`` would fill the same Settings.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    get_llm_client.cache_clear()

    with pytest.raises(LLMError) as exc_info:
        with TestClient(app):  # the lifespan must raise during startup
            pass

    assert "ANTHROPIC_API_KEY" in str(exc_info.value)


def test_lifespan_fails_without_istat_data_with_the_switch_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review Focus 5: on, the missing data stops the startup."""
    monkeypatch.setenv("ISTAT_CONTEXT_ENABLED", "true")
    monkeypatch.setattr(istat_data_mod, "_DATA_DIR", tmp_path)
    get_settings.cache_clear()
    clear_cache()
    try:
        with pytest.raises(IstatDataError):
            with TestClient(app):
                pass
    finally:
        clear_cache()


def test_lifespan_starts_without_istat_data_with_the_switch_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ISTAT_CONTEXT_ENABLED", "false")
    monkeypatch.setattr(istat_data_mod, "_DATA_DIR", tmp_path)
    get_settings.cache_clear()
    clear_cache()
    try:
        with TestClient(app):
            pass
    finally:
        clear_cache()


def test_lifespan_preloads_the_istat_data_with_the_switch_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R9 (review 2): off, the grounding still computes the ISTAT rows; the data is
    loaded at startup (without failing), not at the first /analyze on the event
    loop."""
    monkeypatch.setenv("ISTAT_CONTEXT_ENABLED", "false")
    get_settings.cache_clear()
    clear_cache()
    try:
        with TestClient(app):
            assert istat_data_mod._outcome.cache_info().currsize == 1  # pyright: ignore[reportPrivateUsage]
    finally:
        clear_cache()
