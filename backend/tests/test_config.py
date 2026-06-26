"""Test del modulo di configurazione centralizzata."""

import pytest
from pydantic import SecretStr, ValidationError

from crime_risk_analyzer.config import Settings, get_settings

# `_env_file` è un kwarg runtime di pydantic-settings (`BaseSettings.__init__`
# lo accetta via **values per disattivare il caricamento del `.env` reale e
# isolare i test), ma non è esposto nella firma sintetizzata: pyright strict lo
# segnala come reportCallIssue. Si ignora puntualmente sulla singola chiamata,
# senza indebolire il type-checking altrove (stesso pattern di test_health.py).


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Senza env né .env i default sono applicati e le key sono None."""
    for var in (
        "ANTHROPIC_API_KEY",
        "GROQ_API_KEY",
        "ONTOLOGY_PATH",
        "LLM_PROVIDER",
        "CACHE_ENABLED",
        "DEFAULT_CITY",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.anthropic_api_key is None
    assert settings.groq_api_key is None
    assert settings.ontology_path == "ontology/terminus_crime_materialized.ttl"
    assert settings.llm_provider == "claude"
    assert settings.cache_enabled is True
    assert settings.default_city == "Roma"


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """I valori da environment sovrascrivono i default e sono tipizzati."""
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("CACHE_ENABLED", "false")
    monkeypatch.setenv("DEFAULT_CITY", "Milano")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.llm_provider == "groq"
    assert settings.cache_enabled is False
    assert settings.default_city == "Milano"


def test_invalid_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un provider fuori dal Literal solleva ValidationError."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_secrets_not_leaked() -> None:
    """SecretStr non espone il valore in repr/str; get_secret_value lo restituisce."""
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        anthropic_api_key=SecretStr("sk-ant-supersecret"),
    )

    assert "sk-ant-supersecret" not in repr(settings)
    assert "sk-ant-supersecret" not in str(settings)
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-supersecret"


def test_get_settings_cached() -> None:
    """get_settings() restituisce sempre la stessa istanza (lru_cache)."""
    get_settings.cache_clear()

    first = get_settings()
    second = get_settings()

    assert isinstance(first, Settings)
    assert first is second
