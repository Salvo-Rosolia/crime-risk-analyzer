"""Test dell'endpoint ``GET /cities``.

Le citta garantite (Roma, Milano, Napoli) sono testate end-to-end per spec
(orchestrator.md); le altre sono best-effort e non vengono assertite a una a una
per non legare il test all'elenco esatto.
"""

from typing import cast

import httpx
from fastapi.testclient import TestClient

from crime_risk_analyzer.main import app

client = TestClient(app)

# `cast` + ignore puntuale: il tipo di `.get` di TestClient non e risolto da
# pyright strict con questa combinazione di versioni (difetto di stub di terze
# parti). Stesso pattern gia adottato in test_health.py.


def test_cities_returns_supported_list() -> None:
    response = cast(httpx.Response, client.get("/cities"))  # pyright: ignore[reportUnknownMemberType]

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    # Le tre citta garantite devono sempre essere presenti.
    for city in ("Roma", "Milano", "Napoli"):
        assert city in payload
