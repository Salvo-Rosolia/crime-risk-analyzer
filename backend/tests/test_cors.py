"""Tests for the CORSMiddleware (#106).

The middleware is DEFENSE IN DEPTH for a client on an origin different from
the API one; why the frontend does not depend on it today is explained next to
``add_middleware`` in main.py (which routes go through the ``ng serve`` proxy
is told only by ``frontend/proxy.config.json``). Option A: EXPLICIT allowlist
from ``Settings``, never the ``*`` wildcard (constraint #106),
``allow_credentials=False`` (stateless API).

``cast`` + targeted ignore on the ``TestClient`` methods: their type is not
resolved by pyright strict with this combination of versions (same pattern as
test_health.py / test_cities.py).
"""

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.main import app, create_app

client = TestClient(app)

_ALLOWED_ORIGIN = "http://localhost:4200"
_DISALLOWED_ORIGIN = "http://evil.example"
_ACAO = "access-control-allow-origin"
_ACAM = "access-control-allow-methods"


def test_cors_reflects_allowlisted_origin_on_health() -> None:
    """GET /health with an allowlisted origin -> ACAO equal to that origin."""
    response = cast(
        httpx.Response,
        client.get("/health", headers={"Origin": _ALLOWED_ORIGIN}),  # pyright: ignore[reportUnknownMemberType]
    )

    assert response.status_code == 200
    assert response.headers[_ACAO] == _ALLOWED_ORIGIN
    # Constraint #106: the reflected value must NEVER be the wildcard.
    assert response.headers[_ACAO] != "*"


def test_cors_preflight_options_analyze_allows_post() -> None:
    """OPTIONS preflight on /analyze from an allowlisted origin -> POST among the
    methods.

    The preflight is intercepted by the middleware before routing: it touches
    neither the orchestrator nor the dependencies (ontology/LLM), so it is
    deterministic.
    """
    response = cast(
        httpx.Response,
        client.options(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            headers={
                "Origin": _ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        ),
    )

    assert response.status_code == 200
    assert response.headers[_ACAO] == _ALLOWED_ORIGIN
    assert response.headers[_ACAO] != "*"
    assert "POST" in response.headers[_ACAM]


def test_cors_does_not_reflect_non_allowlisted_origin() -> None:
    """GET /health from a NON-allowlisted origin -> no ACAO for that origin.

    The request arrives anyway (CORS is browser-side enforcement), but the server
    does not emit the header, so the browser would block the read.
    """
    response = cast(
        httpx.Response,
        client.get("/health", headers={"Origin": _DISALLOWED_ORIGIN}),  # pyright: ignore[reportUnknownMemberType]
    )

    assert response.status_code == 200
    # The hostile origin is not reflected and no wildcard appears.
    assert response.headers.get(_ACAO) != _DISALLOWED_ORIGIN
    assert response.headers.get(_ACAO) != "*"


def test_cors_preflight_rejects_non_allowlisted_origin() -> None:
    """Preflight from a NON-allowlisted origin -> ACAO absent/not reflected."""
    response = cast(
        httpx.Response,
        client.options(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            headers={
                "Origin": _DISALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        ),
    )

    assert response.headers.get(_ACAO) != _DISALLOWED_ORIGIN
    assert response.headers.get(_ACAO) != "*"


def test_cors_allowlist_is_config_driven(monkeypatch: pytest.MonkeyPatch) -> None:
    """It is the CONFIG that drives the middleware allowlist, not a hardcode.

    Defense against the false green: if ``create_app`` fixed
    ``allow_origins=["http://localhost:4200"]`` (the default), the tests using the
    default origin would pass anyway. Here the allowlisted origin is NON-default:
    it is reflected only if the middleware really reads
    ``settings.cors_allow_origins``, while the default must NOT be anymore.

    The ``get_settings`` cache is emptied beforehand (to make a ``Settings`` be
    rebuilt from the env) and restored in teardown, so the test does not pollute
    the others (which share the module app built with the default).
    """
    custom_origin = "https://app.example.org"
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", f'["{custom_origin}"]')
    get_settings.cache_clear()
    try:
        fresh_client = TestClient(create_app())
        allowed = cast(
            httpx.Response,
            fresh_client.get("/health", headers={"Origin": custom_origin}),  # pyright: ignore[reportUnknownMemberType]
        )
        assert allowed.headers[_ACAO] == custom_origin
        assert allowed.headers[_ACAO] != "*"

        # The default, if it were hardcoded, would be unmasked: it must not be
        # reflected.
        defaulted = cast(
            httpx.Response,
            fresh_client.get("/health", headers={"Origin": _ALLOWED_ORIGIN}),  # pyright: ignore[reportUnknownMemberType]
        )
        assert defaulted.headers.get(_ACAO) != _ALLOWED_ORIGIN
    finally:
        get_settings.cache_clear()
