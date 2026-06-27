"""Unit sui provider DI dell'orchestratore (#18)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.llm.client import LLMClient, LLMError, get_llm_client
from crime_risk_analyzer.sparql_module.query_executor import (
    RiskQueryExecutor,
    get_executor,
)


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    yield
    get_settings.cache_clear()
    get_llm_client.cache_clear()
    get_executor.cache_clear()


def test_get_executor_returns_cached_executor() -> None:
    get_executor.cache_clear()
    ex = get_executor()
    assert isinstance(ex, RiskQueryExecutor)
    assert get_executor() is ex


def test_get_llm_client_builds_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    get_settings.cache_clear()
    get_llm_client.cache_clear()
    client = get_llm_client()
    assert isinstance(client, LLMClient)
    assert client.provider == "claude"


def test_get_llm_client_raises_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    get_llm_client.cache_clear()
    with pytest.raises(LLMError):
        get_llm_client()
