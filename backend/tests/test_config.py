"""Tests for the centralized configuration module."""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from crime_risk_analyzer.config import Settings, get_settings

# `_env_file` is a pydantic-settings runtime kwarg (`BaseSettings.__init__`
# accepts it via **values to disable loading the real `.env` and isolate the
# tests), but it is not exposed in the synthesized signature: pyright strict
# flags it as reportCallIssue. It is ignored on the single call, without
# weakening the type-checking elsewhere (same pattern as test_health.py).


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without env or .env the defaults are applied and the keys are None."""
    for var in (
        "ANTHROPIC_API_KEY",
        "GROQ_API_KEY",
        "ONTOLOGY_PATH",
        "LLM_PROVIDER",
        "CACHE_ENABLED",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.anthropic_api_key is None
    assert settings.groq_api_key is None
    assert settings.ontology_path == "ontology/terminus_crime_materialized.ttl"
    assert settings.llm_provider == "claude"
    assert settings.cache_enabled is True


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The values from the environment override the defaults and are typed."""
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("CACHE_ENABLED", "false")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.llm_provider == "groq"
    assert settings.cache_enabled is False


def test_invalid_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider outside the Literal raises ValidationError."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("value", ["0", "-1", "-0.5"])
def test_invalid_llm_timeout_seconds_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """llm_timeout_seconds <= 0 is rejected at load (must be > 0)."""
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("value", ["0", "-5"])
def test_invalid_llm_max_tokens_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """llm_max_tokens < 1 is rejected at load (at least 1 token)."""
    monkeypatch.setenv("LLM_MAX_TOKENS", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_valid_llm_timeout_and_max_tokens_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid values from env are accepted and typed."""
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("LLM_MAX_TOKENS", "2048")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.llm_timeout_seconds == 12.5
    assert settings.llm_max_tokens == 2048


def test_llm_request_token_budget_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """8700 keeps the real request under the 8,000 TPM of gpt-oss-120b on Groq.

    #345, D14.
    """
    monkeypatch.delenv("LLM_REQUEST_TOKEN_BUDGET", raising=False)

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.llm_request_token_budget == 8700


def test_llm_request_token_budget_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The total token cap of the LLM request can be overridden from env (#210)."""
    monkeypatch.setenv("LLM_REQUEST_TOKEN_BUDGET", "8000")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.llm_request_token_budget == 8000


@pytest.mark.parametrize("value", ["0", "-1", "-100"])
def test_invalid_llm_request_token_budget_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """llm_request_token_budget < 1 is rejected at load (at least 1 token, #210)."""
    monkeypatch.setenv("LLM_REQUEST_TOKEN_BUDGET", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_secrets_not_leaked() -> None:
    """SecretStr does not expose the value in repr/str; get_secret_value returns it."""
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        anthropic_api_key=SecretStr("sk-ant-supersecret"),
    )

    assert "sk-ant-supersecret" not in repr(settings)
    assert "sk-ant-supersecret" not in str(settings)
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-supersecret"


def test_get_settings_cached() -> None:
    """get_settings() always returns the same instance (lru_cache)."""
    get_settings.cache_clear()

    first = get_settings()
    second = get_settings()

    assert isinstance(first, Settings)
    assert first is second


def test_cors_allow_origins_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without env the default is the dev allowlist of the Angular frontend, never a
    wildcard."""
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.cors_allow_origins == ["http://localhost:4200"]
    # Constraint #106: never a wildcard in the allowlist (not even by default).
    assert "*" not in settings.cors_allow_origins


def test_cors_allow_origins_from_env_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """The allowlist is configurable from env as a JSON list.

    pydantic-settings convention: complex types (``list``) are read from the
    environment variable as JSON: a CSV would be rejected with ``SettingsError``.
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
    """A wildcard '*' in ANY element is rejected at load (#106: never '*').

    It shields the allowlist from the silent return of the wildcard from env,
    which would reopen the policy to any site.
    """
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_cors_empty_list_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty allowlist is rejected at load (it would effectively disable CORS)."""
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "[]")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("value", ['[""]', '["   "]', '["http://a.test", "  "]'])
def test_cors_blank_origin_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """An empty or whitespace-only origin is rejected at load."""
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_cors_origins_are_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """An origin surrounded by spaces is accepted and STORED trimmed.

    Without normalization the value with spaces would pass the validation but
    ``CORSMiddleware`` (exact match) would never make it match the browser's
    Origin header: it would fail safe, but silently.
    """
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", '["  http://localhost:4200  "]')

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.cors_allow_origins == ["http://localhost:4200"]


def test_geocoding_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without env or .env the geocoding defaults (#115) are applied."""
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
    """geocoding_min_delay_seconds <= 0 is rejected at load (must be > 0)."""
    monkeypatch.setenv("GEOCODING_MIN_DELAY_SECONDS", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("value", ["0", "-1", "-0.5"])
def test_invalid_geocoding_timeout_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """geocoding_timeout_seconds <= 0 is rejected at load (must be > 0)."""
    monkeypatch.setenv("GEOCODING_TIMEOUT_SECONDS", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("value", ["0", "-1", "-0.5"])
def test_invalid_geocoding_min_bbox_half_span_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """geocoding_min_bbox_half_span_deg <= 0 is rejected at load (must be > 0).

    A 0/negative value would degenerate the minimum floor into a null or inverted
    bbox at runtime (#204): better to fail at load.
    """
    monkeypatch.setenv("GEOCODING_MIN_BBOX_HALF_SPAN_DEG", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_geocoding_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The geocoding values from the environment override the defaults."""
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
    """An empty or whitespace-only country_codes is rejected at load (#115).

    An empty string would SILENTLY disable the Nominatim country filter (the
    parameter would be ignored), returning homonymous zones in the wrong country:
    better to fail at load with ``ValidationError``.
    """
    monkeypatch.setenv("GEOCODING_COUNTRY_CODES", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_geocoding_country_codes_multi_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nominatim accepts several country codes: the CSV "it,sm" stays valid."""
    monkeypatch.setenv("GEOCODING_COUNTRY_CODES", "it,sm")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.geocoding_country_codes == "it,sm"


def test_geocoding_country_codes_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stored value is normalized with strip() (edge spaces removed)."""
    monkeypatch.setenv("GEOCODING_COUNTRY_CODES", "  it  ")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.geocoding_country_codes == "it"


def test_search_radius_defaults() -> None:
    """Without env the search radius defaults are applied (#318)."""
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert settings.search_radius_min_m == 150.0
    assert settings.search_radius_max_m == 3000.0


def test_search_radius_min_ge_max_rejected() -> None:
    """search_radius_min_m >= max is rejected at load (#318)."""
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            search_radius_min_m=3000.0,
            search_radius_max_m=150.0,
        )


def test_istat_context_enabled_default_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ISTAT_CONTEXT_ENABLED", raising=False)
    assert Settings(_env_file=None).istat_context_enabled is True  # pyright: ignore[reportCallIssue]


def test_istat_context_enabled_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ISTAT_CONTEXT_ENABLED", "false")
    assert Settings(_env_file=None).istat_context_enabled is False  # pyright: ignore[reportCallIssue]


def _env_example_values() -> dict[str, str]:
    """Active (not commented) ``KEY=value`` pairs of ``backend/.env.example``."""
    text = (Path(__file__).resolve().parents[1] / ".env.example").read_text(
        encoding="utf-8"
    )
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def test_env_example_aligned_with_budget_and_istat_defaults() -> None:
    """R3 (review 2): the template must not suggest a budget beyond the TPM of the
    model in use nor forget the ISTAT switch."""
    values = _env_example_values()
    default = Settings.model_fields
    assert int(values["LLM_REQUEST_TOKEN_BUDGET"]) == (
        default["llm_request_token_budget"].default
    )
    assert values["ISTAT_CONTEXT_ENABLED"] == "true"
    assert default["istat_context_enabled"].default is True


def test_istat_model_selection_default_off_and_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#366: the "model chooses the voci" mode is opt-in (A/B with sentences)."""
    monkeypatch.delenv("ISTAT_SCELTA_MODELLO", raising=False)
    assert Settings(_env_file=None).istat_scelta_modello is False  # pyright: ignore[reportCallIssue]
    monkeypatch.setenv("ISTAT_SCELTA_MODELLO", "true")
    assert Settings(_env_file=None).istat_scelta_modello is True  # pyright: ignore[reportCallIssue]


def test_env_example_has_the_selection_switch_off() -> None:
    assert _env_example_values()["ISTAT_SCELTA_MODELLO"] == "false"
    assert Settings.model_fields["istat_scelta_modello"].default is False


# Fields intentionally absent from the template: none today. Add a name here
# only with a reason, otherwise document the variable in ``.env.example``.
_ENV_EXAMPLE_NOT_DOCUMENTED: frozenset[str] = frozenset()

# Secrets are documented with an empty value: they differ from the ``None`` default.
_ENV_EXAMPLE_VALUE_DIFFERS: frozenset[str] = frozenset(
    {"anthropic_api_key", "groq_api_key"}
)


def test_env_example_lists_every_setting() -> None:
    """Every ``Settings`` field appears in ``.env.example`` (#500)."""
    documented = set(_env_example_values())
    missing = sorted(
        name.upper()
        for name in Settings.model_fields
        if name not in _ENV_EXAMPLE_NOT_DOCUMENTED and name.upper() not in documented
    )
    assert not missing, f"missing from .env.example: {missing}"
    unknown = sorted(documented - {name.upper() for name in Settings.model_fields})
    assert not unknown, f".env.example lists unknown settings: {unknown}"


def test_env_example_values_match_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """The values in the template are the real defaults (no silent drift)."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    template = Path(__file__).resolve().parents[1] / ".env.example"
    loaded = Settings(_env_file=template)  # pyright: ignore[reportCallIssue]
    for name, field in Settings.model_fields.items():
        if name in _ENV_EXAMPLE_VALUE_DIFFERS:
            continue
        assert getattr(loaded, name) == field.default, name
