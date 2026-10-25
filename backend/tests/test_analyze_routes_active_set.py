"""Le rotte di analisi usano l'executor del set di fonti attivo (#433).

Con un set attivo (esempio o caricato) i profili di rischio devono venire
dall'executor di quel set, non da quello TERMINUS di default. Si verifica a
livello di rotta: la funzione di pipeline riceve l'executor del set legato.
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

_CENTRO = {"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0}
_HASH = "a" * 64

#: (rotta, body, nome della funzione di pipeline importata in main)
_ROTTE: list[tuple[str, dict[str, Any], str]] = [
    ("/analyze", _CENTRO, "run_analysis_fast"),
    ("/analyze/baseline", _CENTRO, "run_baseline"),
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
    """Executor fittizio distinguibile per identita'."""


class _Catturato(Exception):
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


async def _area_finta(*args: object, **kwargs: object) -> tuple[str, str, None]:
    """Resolver d'area senza rete: la pipeline e' gia' finta."""
    return ("Roma", "Monti", None)


def _catturatore(monkeypatch: pytest.MonkeyPatch, nome: str) -> dict[str, Any]:
    visti: dict[str, Any] = {}

    async def _finto(*args: object, **kwargs: Any) -> object:
        visti["executor"] = kwargs["executor"]
        raise _Catturato

    monkeypatch.setattr(main_module, nome, _finto)
    return visti


@pytest.mark.parametrize(("rotta", "body", "nome"), _ROTTE)
def test_rotta_usa_l_executor_del_set_attivo(
    client: TestClient,
    store: SessionStore,
    monkeypatch: pytest.MonkeyPatch,
    rotta: str,
    body: dict[str, Any],
    nome: str,
) -> None:
    attivo = _Marker()
    store.activate(
        SID,
        replace(default_set(), id="esempio", kind="custom", executor=attivo),
        [],  # pyright: ignore[reportArgumentType]
    )
    visti = _catturatore(monkeypatch, nome)
    if rotta in ("/analyze", "/analyze/baseline"):
        monkeypatch.setattr(main_module, "_resolve_area", _area_finta)

    client.post(rotta, json=body, headers={H: SID})

    assert visti["executor"] is attivo


@pytest.mark.parametrize(("rotta", "body", "nome"), _ROTTE)
def test_rotta_senza_sessione_usa_l_executor_di_default(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    rotta: str,
    body: dict[str, Any],
    nome: str,
) -> None:
    visti = _catturatore(monkeypatch, nome)
    if rotta in ("/analyze", "/analyze/baseline"):
        monkeypatch.setattr(main_module, "_resolve_area", _area_finta)

    client.post(rotta, json=body)

    assert visti["executor"] is default_set().executor
