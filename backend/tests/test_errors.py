"""Tests for the central error handling layer (#21).

Contract (orchestrator.md, "Error handling"): domain exceptions are mapped to
explicit HTTP responses by a central exception handler, **not** by scattered
``try/except`` in the routers. Here we verify:
  * the error -> status map (zone 422, external services 503);
  * that the zone body carries error and message (without a list of
    suggestions);
  * that ``LLMError`` is **not** mapped to a generic handler (the structured
    data fallback is a decision of the orchestrator #18, and there is no
    automatic failover to Groq).

No city allowlist (#191): there is no dedicated ``400`` handler anymore; a
nonexistent citta/zona fails at geocoding as ``ZoneNotFoundError`` (422).

The tests mount a minimal app with routes that raise the exceptions, so the
handlers are tested in isolation without depending on the orchestrator.
"""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from crime_risk_analyzer.errors import register_exception_handlers
from crime_risk_analyzer.geocoding import GeocodingError, ZoneNotFoundError
from crime_risk_analyzer.llm.client import LLMError
from crime_risk_analyzer.overpass_client import OverpassError


async def _raise_zone() -> None:
    raise ZoneNotFoundError("Zona non trovata: 'Xyz' in 'Roma'")


async def _raise_geocoding() -> None:
    raise GeocodingError("Servizio di geocoding non raggiungibile")


async def _raise_overpass() -> None:
    raise OverpassError("Overpass timeout dopo retry")


async def _raise_llm() -> None:
    raise LLMError("Generazione Claude fallita")


def _make_client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_api_route("/raise/zone", _raise_zone)
    app.add_api_route("/raise/geocoding", _raise_geocoding)
    app.add_api_route("/raise/overpass", _raise_overpass)
    app.add_api_route("/raise/llm", _raise_llm)
    return TestClient(app, raise_server_exceptions=False)


def _get(client: TestClient, path: str) -> httpx.Response:
    return cast(httpx.Response, client.get(path))  # pyright: ignore[reportUnknownMemberType]


def test_zone_not_found_maps_to_422_without_suggestions() -> None:
    response = _get(_make_client(), "/raise/zone")

    assert response.status_code == 422
    body = response.json()
    # Simple error: error code + message, without a list of suggestions.
    assert body["detail"]["errore"] == "zona_non_geocodificabile"
    assert body["detail"]["messaggio"]
    assert "scenari_suggeriti" not in body["detail"]


def test_geocoding_service_error_maps_to_503() -> None:
    response = _get(_make_client(), "/raise/geocoding")

    assert response.status_code == 503


def test_overpass_error_maps_to_503() -> None:
    response = _get(_make_client(), "/raise/overpass")

    assert response.status_code == 503


def test_llm_error_is_not_mapped_to_a_generic_handler() -> None:
    # LLMError must NOT have a dedicated handler: the fallback (demo cache /
    # structured data only) is decided by the orchestrator #18, there is no Groq
    # failover. Without the orchestrator, the error stays unhandled -> 500 (raw
    # server error).
    response = _get(_make_client(), "/raise/llm")

    assert response.status_code == 500


def test_zone_not_found_is_subclass_of_geocoding_error_but_maps_to_422() -> None:
    # ZoneNotFoundError extends GeocodingError: the more specific handler (422)
    # must win over the generic one (503).
    assert issubclass(ZoneNotFoundError, GeocodingError)
    response = _get(_make_client(), "/raise/zone")
    assert response.status_code == 422


def test_register_returns_none_and_is_idempotent() -> None:
    app = FastAPI()
    assert register_exception_handlers(app) is None
    # Registering again must not raise (e.g. repeated startup in the tests).
    register_exception_handlers(app)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/raise/zone", 422),
        ("/raise/geocoding", 503),
        ("/raise/overpass", 503),
    ],
)
def test_error_map_matches_orchestrator_spec(path: str, expected: int) -> None:
    response = _get(_make_client(), path)
    assert response.status_code == expected


def test_create_app_registers_domain_handlers() -> None:
    # The real app must mount the central handlers: the handled domain types are
    # present in the Starlette exception_handlers map.
    from crime_risk_analyzer.main import create_app

    app = create_app()
    handlers = app.exception_handlers
    for exc_type in (
        ZoneNotFoundError,
        GeocodingError,
        OverpassError,
    ):
        assert exc_type in handlers
    # LLMError is NOT mounted (decision of the orchestrator #18, no Groq failover).
    assert LLMError not in handlers
