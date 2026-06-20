"""Test del layer di gestione errori centrale (#21).

Contratto (orchestrator.md §"Gestione errori"): le eccezioni di dominio vengono
mappate a risposte HTTP esplicite da un exception handler centrale, **non** da
``try/except`` sparsi nei router. Qui si verifica:
  * la mappa errore -> status (zona 422, citta' 400, servizi esterni 503);
  * che il body porti i suggerimenti previsti (scenari per la zona, citta'
    supportate per la citta');
  * che ``LLMError`` **non** sia mappato a un handler generico (il fallback
    cache/dati-strutturati e' decisione dell'orchestrator #18, e non c'e' alcun
    failover automatico su Groq).

I test montano un'app minimale con rotte che sollevano le eccezioni, cosi' si
testano gli handler in isolamento senza dipendere dall'orchestrator (non ancora
implementato).
"""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from crime_risk_analyzer.errors import (
    CityNotFoundError,
    register_exception_handlers,
)
from crime_risk_analyzer.geocoding import GeocodingError, ZoneNotFoundError
from crime_risk_analyzer.llm.client import LLMError
from crime_risk_analyzer.overpass_client import OverpassError


async def _raise_zone() -> None:
    raise ZoneNotFoundError("Zona non trovata: 'Xyz' in 'Roma'")


async def _raise_geocoding() -> None:
    raise GeocodingError("Servizio di geocoding non raggiungibile")


async def _raise_city() -> None:
    raise CityNotFoundError("Atlantide", supported=["Roma", "Milano", "Napoli"])


async def _raise_overpass() -> None:
    raise OverpassError("Overpass timeout dopo retry")


async def _raise_llm() -> None:
    raise LLMError("Generazione Claude fallita")


def _make_client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_api_route("/raise/zone", _raise_zone)
    app.add_api_route("/raise/geocoding", _raise_geocoding)
    app.add_api_route("/raise/city", _raise_city)
    app.add_api_route("/raise/overpass", _raise_overpass)
    app.add_api_route("/raise/llm", _raise_llm)
    return TestClient(app, raise_server_exceptions=False)


def _get(client: TestClient, path: str) -> httpx.Response:
    return cast(httpx.Response, client.get(path))  # pyright: ignore[reportUnknownMemberType]


def test_zone_not_found_maps_to_422_with_suggested_scenarios() -> None:
    response = _get(_make_client(), "/raise/zone")

    assert response.status_code == 422
    body = response.json()
    # Lo Stato Errore del frontend riusa la lista /scenarios come suggerimenti.
    assert "scenari_suggeriti" in body["detail"]
    assert len(body["detail"]["scenari_suggeriti"]) > 0


def test_city_not_found_maps_to_400_with_supported_cities() -> None:
    response = _get(_make_client(), "/raise/city")

    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["citta_supportate"] == ["Roma", "Milano", "Napoli"]


def test_geocoding_service_error_maps_to_503() -> None:
    response = _get(_make_client(), "/raise/geocoding")

    assert response.status_code == 503


def test_overpass_error_maps_to_503() -> None:
    response = _get(_make_client(), "/raise/overpass")

    assert response.status_code == 503


def test_llm_error_is_not_mapped_to_a_generic_handler() -> None:
    # LLMError NON deve avere un handler dedicato: il ripiego (cache demo / solo
    # dati strutturati) e' deciso dall'orchestrator #18, non c'e' failover Groq.
    # Senza orchestrator, l'errore resta non gestito -> 500 (server error grezzo).
    response = _get(_make_client(), "/raise/llm")

    assert response.status_code == 500


def test_zone_not_found_is_subclass_of_geocoding_error_but_maps_to_422() -> None:
    # ZoneNotFoundError estende GeocodingError: l'handler piu' specifico (422)
    # deve vincere su quello generico (503).
    assert issubclass(ZoneNotFoundError, GeocodingError)
    response = _get(_make_client(), "/raise/zone")
    assert response.status_code == 422


def test_city_not_found_carries_supported_cities() -> None:
    err = CityNotFoundError("Atlantide", supported=["Roma"])
    assert err.city == "Atlantide"
    assert err.supported == ["Roma"]


def test_city_not_found_defaults_supported_to_empty() -> None:
    err = CityNotFoundError("Atlantide")
    assert err.supported == []


def test_register_returns_none_and_is_idempotent() -> None:
    app = FastAPI()
    assert register_exception_handlers(app) is None
    # Re-registrare non deve sollevare (es. avvio ripetuto nei test).
    register_exception_handlers(app)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/raise/zone", 422),
        ("/raise/city", 400),
        ("/raise/geocoding", 503),
        ("/raise/overpass", 503),
    ],
)
def test_error_map_matches_orchestrator_spec(path: str, expected: int) -> None:
    response = _get(_make_client(), path)
    assert response.status_code == expected


def test_create_app_registers_domain_handlers() -> None:
    # L'app reale deve montare gli handler centrali: i tipi di dominio gestiti
    # sono presenti nella mappa exception_handlers di Starlette.
    from crime_risk_analyzer.main import create_app

    app = create_app()
    handlers = app.exception_handlers
    for exc_type in (
        ZoneNotFoundError,
        GeocodingError,
        CityNotFoundError,
        OverpassError,
    ):
        assert exc_type in handlers
    # LLMError NON e' montato (decisione dell'orchestrator #18, no failover Groq).
    assert LLMError not in handlers
