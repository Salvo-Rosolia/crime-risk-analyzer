"""The analysis routes use the executor of the active source set (#433).

With an active set (example or uploaded) the risk profiles must come from the
executor of that set, not from the default TERMINUS one. It is verified at
route level: the pipeline function receives the executor of the bound set.
"""

from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer import main as main_module
from crime_risk_analyzer.llm.client import get_llm_client
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.sources import routes
from crime_risk_analyzer.sources.context import default_set
from crime_risk_analyzer.sources.session import SessionStore

SID = "sessione-di-prova-AAAA"
H = "X-Session-Id"

_CENTER = {"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0}
_HASH = "a" * 64

#: (route, body, name of the pipeline function imported in main)
_ROUTES: list[tuple[str, dict[str, Any], str]] = [
    ("/analyze", _CENTER, "run_analysis_fast"),
    ("/analyze/baseline", _CENTER, "run_baseline"),
    (
        "/analyze/narrativa",
        {"citta": "Roma", "zona": "Monti", "contesto_hash": _HASH},
        "run_zone_narrative",
    ),
    (
        "/analyze/poi",
        {
            "citta": "Roma",
            "zona": "Monti",
            "poi_id": "node/1",
            "contesto_hash": _HASH,
        },
        "run_poi_narrative",
    ),
]


class _Marker:
    """Fake executor distinguishable by identity."""


class _Captured(Exception):
    pass


@pytest.fixture
def store() -> SessionStore:
    return SessionStore(ttl_seconds=100, max_sessions=2)


@pytest.fixture
def client(store: SessionStore) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[routes.get_sessions] = lambda: store
    app.dependency_overrides[get_llm_client] = lambda: object()
    yield TestClient(app, raise_server_exceptions=False)


async def _fake_area(*args: object, **kwargs: object) -> tuple[str, str, None]:
    """Area resolver without network: the pipeline is already fake."""
    return ("Roma", "Monti", None)


def _capturer(monkeypatch: pytest.MonkeyPatch, fn_name: str) -> dict[str, Any]:
    seen_args: dict[str, Any] = {}

    async def _fake_call(*args: object, **kwargs: Any) -> object:
        seen_args["executor"] = kwargs["executor"]
        raise _Captured

    monkeypatch.setattr(main_module, fn_name, _fake_call)
    return seen_args


@pytest.mark.parametrize(("route", "body", "fn_name"), _ROUTES)
def test_route_uses_the_active_set_executor(
    client: TestClient,
    store: SessionStore,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    body: dict[str, Any],
    fn_name: str,
) -> None:
    active = _Marker()
    store.activate(
        SID,
        replace(default_set(), id="esempio", kind="custom", executor=active),
        [],  # pyright: ignore[reportArgumentType]
    )
    seen_args = _capturer(monkeypatch, fn_name)
    if route in ("/analyze", "/analyze/baseline"):
        monkeypatch.setattr(main_module, "_resolve_area", _fake_area)

    client.post(route, json=body, headers={H: SID})

    assert seen_args["executor"] is active


@pytest.mark.parametrize(("route", "body", "fn_name"), _ROUTES)
def test_route_without_session_uses_the_default_executor(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    body: dict[str, Any],
    fn_name: str,
) -> None:
    seen_args = _capturer(monkeypatch, fn_name)
    if route in ("/analyze", "/analyze/baseline"):
        monkeypatch.setattr(main_module, "_resolve_area", _fake_area)

    client.post(route, json=body)

    assert seen_args["executor"] is default_set().executor
