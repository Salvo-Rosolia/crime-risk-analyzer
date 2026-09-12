"""Test endpoint GET /geocode (#318)."""

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer import geocoding
from crime_risk_analyzer.main import app

client = TestClient(app)


def _fake_geocode_found(query: str) -> tuple[float, float] | None:
    return (41.9, 12.5)


def _fake_geocode_not_found(query: str) -> tuple[float, float] | None:
    return None


def test_geocode_successo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(geocoding, "geocode_freeform", _fake_geocode_found)
    response = cast(
        httpx.Response, client.get("/geocode", params={"query": "Duomo di Milano"})
    )  # pyright: ignore[reportUnknownMemberType]
    assert response.status_code == 200
    assert response.json() == {"lat": 41.9, "lon": 12.5}


def test_geocode_non_trovato(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(geocoding, "geocode_freeform", _fake_geocode_not_found)
    response = cast(httpx.Response, client.get("/geocode", params={"query": "xyzxyz"}))  # pyright: ignore[reportUnknownMemberType]
    assert response.status_code == 404
