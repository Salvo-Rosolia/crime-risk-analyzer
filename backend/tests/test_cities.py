"""Tests for the ``GET /cities`` endpoint.

The guaranteed cities (Roma, Milano, Napoli) are tested end-to-end per spec
(orchestrator.md); the others are best-effort and are not asserted one by one,
so as not to tie the test to the exact list.
"""

from typing import cast

import httpx
from fastapi.testclient import TestClient

from crime_risk_analyzer.main import app

client = TestClient(app)

# `cast` + targeted ignore: the type of TestClient's `.get` is not resolved by
# pyright strict with this combination of versions (third-party stub defect).
# Same pattern already adopted in test_health.py.


def test_cities_returns_supported_list() -> None:
    response = cast(httpx.Response, client.get("/cities"))  # pyright: ignore[reportUnknownMemberType]

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    # The three guaranteed cities must always be present.
    for city in ("Roma", "Milano", "Napoli"):
        assert city in payload
