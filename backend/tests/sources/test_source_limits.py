"""Limits on the loaded sources: OSM selectors, session header, ids (#498)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from crime_risk_analyzer import overpass_client
from crime_risk_analyzer.errors import register_exception_handlers
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.sources import routes
from crime_risk_analyzer.sources.limits import MAX_OSM_SELECTORS
from crime_risk_analyzer.sources.parsing import check_sources
from crime_risk_analyzer.sources.session import (
    SESSION_ID_MIN_LENGTH,
    SessionStore,
    is_valid_session_id,
)
from tests.sources._factories import VOCABULARY, with_fields
from tests.sources.test_routes_sources import _VOCAB, _files  # pyright: ignore[reportPrivateUsage]

H = "X-Session-Id"
GOOD_SID = "0123456789abcdef0123456789abcdef"


# --- OSM selector cap ---


def _osm_csv(n: int) -> bytes:
    rows = "".join(f"amenity=a{i},Banca\n" for i in range(n))
    return ("osm_tag,classe\n" + rows).encode()


def test_osm_table_at_the_selector_cap_is_accepted() -> None:
    _, report = check_sources(
        with_fields(osm_table=_osm_csv(MAX_OSM_SELECTORS)), VOCABULARY
    )
    assert "troppe_righe" not in [p.code for p in report.errors]


def test_osm_table_above_the_selector_cap_is_rejected() -> None:
    parsed, report = check_sources(
        with_fields(osm_table=_osm_csv(MAX_OSM_SELECTORS + 1)), VOCABULARY
    )
    assert parsed is None
    assert "troppe_righe" in [p.code for p in report.errors]


def test_overpass_query_refuses_more_selectors_than_the_cap() -> None:
    selectors = [f"amenity=a{i}" for i in range(MAX_OSM_SELECTORS + 1)]
    with pytest.raises(ValueError, match="selector"):
        overpass_client._build_query(  # pyright: ignore[reportPrivateUsage]
            Bbox(41.8, 12.4, 41.9, 12.5), selectors
        )


def test_overpass_query_accepts_exactly_the_cap() -> None:
    selectors = [f"amenity=a{i}" for i in range(MAX_OSM_SELECTORS)]
    query = overpass_client._build_query(  # pyright: ignore[reportPrivateUsage]
        Bbox(41.8, 12.4, 41.9, 12.5), selectors
    )
    assert query.count("relation[") == MAX_OSM_SELECTORS


def test_default_selectors_fit_in_the_cap() -> None:
    from crime_risk_analyzer.sparql_module.osm_mapping import OSM_SELECTORS

    assert len(OSM_SELECTORS) <= MAX_OSM_SELECTORS


# --- header checked before the multipart ---


@pytest.fixture
def client() -> TestClient:
    store = SessionStore(ttl_seconds=100, max_sessions=4)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_sessions] = lambda: store
    return TestClient(app)


def _spy_form(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    from starlette.requests import Request

    calls: list[int] = []
    original = Request.form

    def _spy(self: Request, *a: Any, **k: Any) -> Any:
        calls.append(1)
        return original(self, *a, **k)

    monkeypatch.setattr(Request, "form", _spy)
    return calls


@pytest.mark.parametrize(
    "sid", [None, "corto", "x" * 31, "bad id with spaces!!!!!!!!!!!!!!!!!!!"]
)
def test_upload_with_bad_header_never_reads_the_multipart(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, sid: str | None
) -> None:
    calls = _spy_form(monkeypatch)
    headers = {H: sid} if sid else {}
    r = client.post("/sources", files=_files(), data=_VOCAB, headers=headers)
    assert r.status_code == 422
    assert calls == []


def test_upload_with_bad_header_wins_over_multipart_limits(
    client: TestClient,
) -> None:
    """Too many fields would be a 400 if the form were read first."""
    data = {f"f{i}": "x" for i in range(50)}
    r = client.post("/sources", files=_files(), data=data)
    assert r.status_code == 422


def test_upload_with_good_header_still_reads_the_multipart(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _spy_form(monkeypatch)
    client.post("/sources", files=_files(), data=_VOCAB, headers={H: GOOD_SID})
    assert calls


# --- session id format ---


def test_session_id_minimum_length_is_32() -> None:
    assert SESSION_ID_MIN_LENGTH == 32
    ok = "0123456789abcdefghij0123456789ab"
    assert is_valid_session_id(ok)
    assert not is_valid_session_id(ok[:31])
    assert is_valid_session_id(ok * 4)
    assert not is_valid_session_id(ok * 4 + "x")
    assert is_valid_session_id("0123456789abcdef0123456789abcdef")  # UUID, no dashes


@pytest.mark.parametrize("weak", ["0" * 32, "ab" * 16, "0123" * 8, "a" * 128])
def test_trivially_guessable_session_ids_are_rejected(weak: str) -> None:
    assert not is_valid_session_id(weak)


def test_weak_id_is_422_on_every_route_that_takes_the_header(
    client: TestClient,
) -> None:
    weak = {H: "0" * 32}
    assert client.post("/sources/example", headers=weak).status_code == 422
    assert client.delete("/sources", headers=weak).status_code == 422
    assert client.get("/sources", headers=weak).status_code == 422
    r = client.post("/sources", files=_files(), data=_VOCAB, headers=weak)
    assert r.status_code == 422
