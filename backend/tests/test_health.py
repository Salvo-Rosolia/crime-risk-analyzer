"""Test dell'endpoint di health-check."""

from typing import cast

import httpx
from fastapi.testclient import TestClient

from crime_risk_analyzer.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    # `cast` + ignore puntuale: Starlette TestClient eredita da httpx.Client ma
    # con questa combinazione di versioni il tipo di `.get` non è risolto da
    # pyright strict (difetto di stub di terze parti). Si ancora il risultato
    # senza indebolire il type-checking altrove nel progetto.
    response = cast(httpx.Response, client.get("/health"))  # pyright: ignore[reportUnknownMemberType]

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
