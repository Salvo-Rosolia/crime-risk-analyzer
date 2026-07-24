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


@pytest.mark.parametrize("value", ["0", "-1", "-0.5"])
def test_invalid_llm_timeout_seconds_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """llm_timeout_seconds <= 0 e' respinto al load (deve essere > 0)."""
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("value", ["0", "-5"])
def test_invalid_llm_max_tokens_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """llm_max_tokens < 1 e' respinto al load (almeno 1 token)."""
    monkeypatch.setenv("LLM_MAX_TOKENS", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_valid_llm_timeout_and_max_tokens_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valori validi da env vengono accettati e tipizzati."""
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("LLM_MAX_TOKENS", "2048")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.llm_timeout_seconds == 12.5
    assert settings.llm_max_tokens == 2048


def test_llm_request_token_budget_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Senza env il tetto totale di token della richiesta LLM ha il default (#210).

    10000 sta sotto il TPM del provider (Groq free = 12000) e lascia ~2000 di
    margine per l'errore di stima: la richiesta densa reale non sfora piu' il TPM.
    """
    monkeypatch.delenv("LLM_REQUEST_TOKEN_BUDGET", raising=False)

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.llm_request_token_budget == 10000


def test_llm_request_token_budget_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Il tetto totale di token della richiesta LLM e' sovrascrivibile da env (#210)."""
    monkeypatch.setenv("LLM_REQUEST_TOKEN_BUDGET", "8000")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.llm_request_token_budget == 8000


@pytest.mark.parametrize("value", ["0", "-1", "-100"])
def test_invalid_llm_request_token_budget_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """llm_request_token_budget < 1 e' respinto al load (almeno 1 token, #210)."""
    monkeypatch.setenv("LLM_REQUEST_TOKEN_BUDGET", value)

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


def test_cors_allow_origins_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Senza env il default e' l'allowlist dev del frontend Angular, mai wildcard."""
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.cors_allow_origins == ["http://localhost:4200"]
    # Vincolo #106: mai wildcard nell'allowlist (nemmeno di default).
    assert "*" not in settings.cors_allow_origins


def test_cors_allow_origins_from_env_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """L'allowlist e' configurabile da env come lista JSON.

    Come per ``supported_cities`` (stessa convenzione pydantic-settings), i tipi
    complessi (``list``) sono letti dalla variabile d'ambiente come JSON: una CSV
    verrebbe respinta con ``SettingsError``.
    """
    monkeypatch.setenv(
        "CORS_ALLOW_ORIGINS",
        '["https://app.example.org", "https://staging.example.org"]',
    )

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.cors_allow_origins == [
        "https://app.example.org",
        "https://staging.example.org",
    ]


@pytest.mark.parametrize(
    "value", ['["*"]', '["http://localhost:4200", "*"]', '["https://*.evil.test"]']
)
def test_cors_wildcard_rejected(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Un wildcard '*' in QUALUNQUE elemento e' respinto al load (#106: mai '*').

    Blinda l'allowlist contro il rientro silenzioso del wildcard da env, che
    riaprirebbe la policy a qualunque sito.
    """
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_cors_empty_list_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un'allowlist vuota e' respinta al load (disabiliterebbe di fatto il CORS)."""
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "[]")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("value", ['[""]', '["   "]', '["http://a.test", "  "]'])
def test_cors_blank_origin_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Un'origine vuota o di soli spazi e' respinta al load."""
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_cors_origins_are_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un'origine circondata da spazi e' accettata e MEMORIZZATA trimmata.

    Senza normalizzazione il valore con spazi passerebbe la validazione ma
    ``CORSMiddleware`` (match esatto) non lo farebbe mai combaciare con l'header
    Origin del browser: fallirebbe in sicurezza, ma in silenzio.
    """
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", '["  http://localhost:4200  "]')

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.cors_allow_origins == ["http://localhost:4200"]


def test_geocoding_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Senza env ne' .env i default di geocoding (#115) sono applicati."""
    for var in (
        "GEOCODING_MIN_DELAY_SECONDS",
        "GEOCODING_TIMEOUT_SECONDS",
        "GEOCODING_COUNTRY_CODES",
        "GEOCODING_MIN_BBOX_HALF_SPAN_DEG",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.geocoding_min_delay_seconds == 1.1
    assert settings.geocoding_timeout_seconds == 10.0
    assert settings.geocoding_country_codes == "it"
    assert settings.geocoding_min_bbox_half_span_deg == 0.0045


@pytest.mark.parametrize("value", ["0", "-1", "-0.5"])
def test_invalid_geocoding_min_delay_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """geocoding_min_delay_seconds <= 0 e' respinto al load (deve essere > 0)."""
    monkeypatch.setenv("GEOCODING_MIN_DELAY_SECONDS", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("value", ["0", "-1", "-0.5"])
def test_invalid_geocoding_timeout_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """geocoding_timeout_seconds <= 0 e' respinto al load (deve essere > 0)."""
    monkeypatch.setenv("GEOCODING_TIMEOUT_SECONDS", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("value", ["0", "-1", "-0.5"])
def test_invalid_geocoding_min_bbox_half_span_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """geocoding_min_bbox_half_span_deg <= 0 e' respinto al load (deve essere > 0).

    Un valore 0/negativo degenererebbe il pavimento minimo in un bbox nullo o
    invertito a runtime (#204): meglio fallire al caricamento.
    """
    monkeypatch.setenv("GEOCODING_MIN_BBOX_HALF_SPAN_DEG", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_geocoding_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """I valori di geocoding da environment sovrascrivono i default."""
    monkeypatch.setenv("GEOCODING_MIN_DELAY_SECONDS", "0.5")
    monkeypatch.setenv("GEOCODING_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("GEOCODING_COUNTRY_CODES", "it,sm")
    monkeypatch.setenv("GEOCODING_MIN_BBOX_HALF_SPAN_DEG", "0.02")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.geocoding_min_delay_seconds == 0.5
    assert settings.geocoding_timeout_seconds == 20.0
    assert settings.geocoding_country_codes == "it,sm"
    assert settings.geocoding_min_bbox_half_span_deg == 0.02


@pytest.mark.parametrize("value", ["", "   "])
def test_geocoding_country_codes_blank_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Un country_codes vuoto o di soli spazi e' respinto al load (#115).

    Una stringa vuota disattiverebbe SILENZIOSAMENTE il filtro nazione di
    Nominatim (il parametro verrebbe ignorato), restituendo zone omonime nella
    nazione sbagliata: meglio fallire al caricamento con ``ValidationError``.
    """
    monkeypatch.setenv("GEOCODING_COUNTRY_CODES", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_geocoding_country_codes_multi_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nominatim accetta piu' codici nazione: la CSV "it,sm" resta valida."""
    monkeypatch.setenv("GEOCODING_COUNTRY_CODES", "it,sm")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.geocoding_country_codes == "it,sm"


def test_geocoding_country_codes_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Il valore memorizzato e' normalizzato con strip() (spazi ai bordi rimossi)."""
    monkeypatch.setenv("GEOCODING_COUNTRY_CODES", "  it  ")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.geocoding_country_codes == "it"
