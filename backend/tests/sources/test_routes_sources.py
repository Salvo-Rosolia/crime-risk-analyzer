"""Source loading API: upload, status, return to default, templates (#416)."""

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from crime_risk_analyzer import zone_context_cache as cache
from crime_risk_analyzer.errors import register_exception_handlers
from crime_risk_analyzer.sources import routes
from crime_risk_analyzer.sources.context import current_id
from crime_risk_analyzer.sources.limits import MAX_BYTES_CSV
from crime_risk_analyzer.sources.session import SessionStore
from tests.sources._factories import (
    DATA_CSV,
    HAZARD_CSV,
    NS,
    ONTOLOGY_TTL,
    OSM_CSV,
    boundaries_json,
)

SID = "test-session-AAAAAA"
SID2 = "test-session-BBBBBB"
H = "X-Session-Id"


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def client(clock: Clock) -> Iterator[TestClient]:
    cache.clear()
    store = SessionStore(ttl_seconds=100, max_sessions=4, clock=clock)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_sessions] = lambda: store

    @app.get("/probe", dependencies=[Depends(routes.activate_session)])
    async def probe() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"set": current_id()}

    yield TestClient(app)


def _files(**replacements: bytes | None) -> dict[str, tuple[str, bytes, str]]:
    base: dict[str, bytes | None] = {
        "ontology": ONTOLOGY_TTL.encode(),
        "osm_table": OSM_CSV.encode(),
        "data": DATA_CSV.encode(),
        "hazard_table": HAZARD_CSV.encode(),
        "boundaries": boundaries_json(),
    }
    base.update(replacements)
    names = {"ontology": "mini.ttl"}
    return {
        k: (names.get(k, f"{k}.csv"), v, "application/octet-stream")
        for k, v in base.items()
        if v is not None
    }


_VOCAB: dict[str, Any] = {
    "namespace": NS,
    "hazard": "hasRisk",
    "critical_event": "hasEvent",
    "performer": "hasActor",
    "vulnerability": ["isFragileTo", "hasWeakness"],
}


def _upload(
    client: TestClient, sid: str | None = SID, **replacements: bytes | None
) -> Any:
    headers = {H: sid} if sid else {}
    return client.post(
        "/sources", files=_files(**replacements), data=_VOCAB, headers=headers
    )


def test_status_without_header_is_default(client: TestClient) -> None:
    r = client.get("/sources")
    assert r.status_code == 200
    assert r.json() == {
        "stato": "default",
        "scade_tra_secondi": None,
        "set": None,
        "source_set_id": "default",
    }


def test_status_is_not_shared_cacheable_across_sessions(client: TestClient) -> None:
    """#469: the body depends on X-Session-Id, so shared caches must not reuse it."""
    for headers in ({}, {H: SID}):
        r = client.get("/sources", headers=headers)
        assert r.headers["Vary"] == "X-Session-Id"
        assert r.headers["Cache-Control"] == "private"


def test_upload_activates_the_set(client: TestClient) -> None:
    r = _upload(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stato"] == "attivo"
    assert body["scade_tra_secondi"] == 100
    assert body["set"]["classi"] == 4
    assert body["set"]["selettori_osm"] == 2
    assert body["set"]["luoghi"] == ["Comune di Esempio"]
    assert isinstance(body["set"]["avvisi"], list)
    status = client.get("/sources", headers={H: SID}).json()
    assert status["stato"] == "attivo"


def test_upload_without_boundaries_covering_the_data_422(client: TestClient) -> None:
    r = _upload(client, boundaries=None)
    assert r.status_code == 422
    assert r.json()["detail"]["errore"] == "fonti_non_valide"


def test_upload_with_ambiguous_poi_type_aliases_422(client: TestClient) -> None:
    ontology_ttl = ONTOLOGY_TTL.replace('"Ospedale"@it', '"Banca"@it')
    r = _upload(client, ontology=ontology_ttl.encode())
    assert r.status_code == 422
    assert r.json()["detail"]["errore"] == "fonti_non_valide"
    text = str(r.json()["detail"])
    assert "alias_tipo_poi_ambiguo" in text
    assert "Banca" in text
    assert "Ospedale" in text
    # the set was not activated
    assert client.get("/sources", headers={H: SID}).json()["stato"] == "default"


def test_upload_without_header_422(client: TestClient) -> None:
    assert _upload(client, sid=None).status_code == 422


def test_upload_malformed_header_422(client: TestClient) -> None:
    assert _upload(client, sid="corto").status_code == 422


def test_upload_with_errors_reports_everything_and_does_not_activate(
    client: TestClient,
) -> None:
    r = _upload(client, osm_table=b"osm_tag,classe\namenity=bank,Inesistente\n")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["errore"] == "fonti_non_valide"
    assert detail["errors"][0]["code"] == "classe_assente_dall_ontologia"
    assert detail["errors"][0]["file"] == "osm_table"
    assert client.get("/sources", headers={H: SID}).json()["stato"] == "default"


def test_failed_upload_does_not_remove_the_already_active_set(
    client: TestClient,
) -> None:
    assert _upload(client).status_code == 200
    assert _upload(client, osm_table=b"x,y\n").status_code == 422
    assert client.get("/sources", headers={H: SID}).json()["stato"] == "attivo"


def test_file_over_the_limit_is_rejected(client: TestClient) -> None:
    huge = b"osm_tag,classe\n" + b"a" * (MAX_BYTES_CSV + 10)
    r = _upload(client, osm_table=huge)
    assert r.status_code == 422
    codes = [e["code"] for e in r.json()["detail"]["errors"]]
    assert "file_troppo_grande" in codes


def test_invalid_vocabulary_422(client: TestClient) -> None:
    r = client.post(
        "/sources",
        files=_files(),
        data={**_VOCAB, "namespace": "senza-iri"},
        headers={H: SID},
    )
    assert r.status_code == 422


def test_different_sessions_do_not_see_each_other(client: TestClient) -> None:
    assert _upload(client, sid=SID).status_code == 200
    assert client.get("/sources", headers={H: SID2}).json()["stato"] == "default"
    assert client.get("/probe", headers={H: SID2}).json() == {"set": "default"}
    assert client.get("/probe", headers={H: SID}).json()["set"] != "default"


def test_status_exposes_the_id_of_the_set_in_use(client: TestClient) -> None:
    """#473: the id in the body is the one the server binds to the session."""
    upload = _upload(client).json()
    status = client.get("/sources", headers={H: SID}).json()
    probe = client.get("/probe", headers={H: SID}).json()["set"]
    assert upload["source_set_id"] == status["source_set_id"] == probe
    assert status["source_set_id"] != "default"
    # stable across reads, different for another session and after a new upload
    assert client.get("/sources", headers={H: SID}).json() == status
    assert (
        client.get("/sources", headers={H: SID2}).json()["source_set_id"] == "default"
    )
    assert _upload(client).json()["source_set_id"] != status["source_set_id"]


def test_status_id_is_default_after_expiry_and_reset(
    client: TestClient, clock: Clock
) -> None:
    _upload(client)
    clock.t = 200
    expired = client.get("/sources", headers={H: SID}).json()
    assert expired["stato"] == "scaduto"
    assert expired["source_set_id"] == "default"
    reset = client.delete("/sources", headers={H: SID}).json()
    assert reset["source_set_id"] == "default"


def test_status_id_of_the_example_set(client: TestClient) -> None:
    r = client.post("/sources/example", headers={H: SID}).json()
    assert r["source_set_id"] == "example"


def test_every_upload_has_a_new_set_id(client: TestClient) -> None:
    _upload(client)
    first = client.get("/probe", headers={H: SID}).json()["set"]
    _upload(client)
    second = client.get("/probe", headers={H: SID}).json()["set"]
    assert first != second


def test_probe_without_header_is_default(client: TestClient) -> None:
    assert client.get("/probe").json() == {"set": "default"}


def test_malformed_header_on_analysis_routes_is_default(
    client: TestClient,
) -> None:
    assert client.get("/probe", headers={H: "x"}).json() == {"set": "default"}


def test_expiry_status_and_analysis_routes(client: TestClient, clock: Clock) -> None:
    _upload(client)
    clock.t = 200
    status = client.get("/sources", headers={H: SID}).json()
    assert status["stato"] == "scaduto"
    r = client.get("/probe", headers={H: SID})
    assert r.status_code == 410
    assert r.json()["detail"]["errore"] == "fonti_scadute"
    # the state persists: every analysis route answers 410, GET /sources stays
    # "scaduto" (it does not fall back to the default until the user chooses)
    assert client.get("/probe", headers={H: SID}).status_code == 410
    assert client.get("/sources", headers={H: SID}).json()["stato"] == "scaduto"


def test_expired_state_is_cleared_with_delete(client: TestClient, clock: Clock) -> None:
    _upload(client)
    clock.t = 200
    assert client.get("/probe", headers={H: SID}).status_code == 410
    assert client.delete("/sources", headers={H: SID}).json()["stato"] == "default"
    assert client.get("/probe", headers={H: SID}).json() == {"set": "default"}


def test_expired_state_is_cleared_with_new_upload(
    client: TestClient, clock: Clock
) -> None:
    _upload(client)
    clock.t = 200
    assert client.get("/probe", headers={H: SID}).status_code == 410
    assert _upload(client).json()["stato"] == "attivo"
    assert client.get("/probe", headers={H: SID}).json()["set"] != "default"


def test_invalid_upload_does_not_clear_the_expired_state(
    client: TestClient, clock: Clock
) -> None:
    _upload(client)
    clock.t = 200
    assert _upload(client, osm_table=b"x").status_code == 422
    assert client.get("/sources", headers={H: SID}).json()["stato"] == "scaduto"


def test_upload_exceeds_the_ontology_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes, "MAX_BYTES_ONTOLOGY", 100)
    r = _upload(client)
    assert r.status_code == 422
    assert r.json()["detail"]["errore"] == "fonti_non_valide"
    assert client.get("/sources", headers={H: SID}).json()["stato"] == "default"


def test_upload_exceeds_the_boundaries_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes, "MAX_BYTES_GEOJSON", 10)
    r = _upload(client)
    assert r.status_code == 422
    assert r.json()["detail"]["errore"] == "fonti_non_valide"


def test_content_length_over_the_cap_413(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes, "MAX_BYTES_REQUEST", 50)
    r = _upload(client)
    assert r.status_code == 413
    assert r.json()["detail"]["errore"] == "richiesta_troppo_grande"
    assert client.get("/sources", headers={H: SID}).json()["stato"] == "default"


def test_too_many_files_in_the_multipart_400(client: TestClient) -> None:
    files = _files()
    files["extra"] = ("x.csv", b"a", "text/csv")
    files["extra2"] = ("y.csv", b"a", "text/csv")
    r = client.post("/sources", files=files, data=_VOCAB, headers={H: SID})
    assert r.status_code == 400


def test_too_many_fields_in_the_multipart_400(client: TestClient) -> None:
    data = {**_VOCAB, "vulnerability": [f"v{i}" for i in range(40)]}
    r = client.post("/sources", files=_files(), data=data, headers={H: SID})
    assert r.status_code == 400


def test_concurrent_uploads_over_the_cap_503(client: TestClient) -> None:
    gate = routes.get_upload_gate()
    assert gate.limit >= 1
    for _ in range(gate.limit):
        asyncio.run(gate.semaphore.acquire())
    try:
        r = _upload(client)
        assert r.status_code == 503
        assert r.json()["detail"]["errore"] == "caricamento_occupato"
        assert r.headers["retry-after"]
    finally:
        for _ in range(gate.limit):
            gate.semaphore.release()
    assert _upload(client).status_code == 200


def test_concurrent_sessions_read_their_own_set() -> None:
    import httpx

    app = FastAPI()
    register_exception_handlers(app)
    store = SessionStore(ttl_seconds=100, max_sessions=4)
    store.activate(SID, _custom("set-a"), [])
    store.activate(SID2, _custom("set-b"), [])
    app.dependency_overrides[routes.get_sessions] = lambda: store

    @app.get("/probe", dependencies=[Depends(routes.activate_session)])
    async def probe() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        await asyncio.sleep(0.01)  # yields control to the concurrent request
        return {"set": current_id()}

    async def _run() -> list[str]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            responses = await asyncio.gather(
                c.get("/probe", headers={H: SID}),
                c.get("/probe", headers={H: SID2}),
                c.get("/probe"),
            )
        return [r.json()["set"] for r in responses]

    assert asyncio.run(_run()) == ["set-a", "set-b", "default"]


def test_default_removes_the_set(client: TestClient) -> None:
    _upload(client)
    r = client.delete("/sources", headers={H: SID})
    assert r.status_code == 200
    assert r.json()["stato"] == "default"
    assert client.get("/probe", headers={H: SID}).json() == {"set": "default"}


def test_default_without_header_422_and_idempotent(client: TestClient) -> None:
    assert client.delete("/sources").status_code == 422
    assert client.delete("/sources", headers={H: SID}).status_code == 200
    assert client.delete("/sources", headers={H: SID}).status_code == 200


def test_example_activates_with_a_single_command(client: TestClient) -> None:
    r = client.post("/sources/example", headers={H: SID})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stato"] == "attivo"
    assert body["scade_tra_secondi"] == 100
    assert body["set"]["kind"] == "example"
    assert body["set"]["selettori_osm"] > 0
    assert body["set"]["luoghi"] == [
        "Comune di Milano",
        "Comune di Roma",
        "Comune di Napoli",
    ]
    assert any(a["code"] == "etichetta_mancante" for a in body["set"]["avvisi"])
    assert client.get("/probe", headers={H: SID}).json() == {"set": "example"}
    assert client.get("/sources", headers={H: SID}).json()["set"]["kind"] == "example"


def test_example_without_or_with_malformed_header_422(client: TestClient) -> None:
    assert client.post("/sources/example").status_code == 422
    assert client.post("/sources/example", headers={H: "corto"}).status_code == 422


def test_example_applies_only_to_the_session_that_activates_it(
    client: TestClient,
) -> None:
    client.post("/sources/example", headers={H: SID})
    assert client.get("/probe", headers={H: SID2}).json() == {"set": "default"}
    assert client.get("/sources", headers={H: SID2}).json()["stato"] == "default"


def test_example_replaces_an_uploaded_set_and_delete_returns_to_default(
    client: TestClient,
) -> None:
    assert _upload(client).status_code == 200
    assert client.get("/sources", headers={H: SID}).json()["set"]["kind"] == "custom"
    assert client.post("/sources/example", headers={H: SID}).status_code == 200
    assert client.get("/probe", headers={H: SID}).json() == {"set": "example"}
    assert client.delete("/sources", headers={H: SID}).json()["stato"] == "default"
    assert client.get("/probe", headers={H: SID}).json() == {"set": "default"}


def test_example_reactivated_after_expiry(client: TestClient, clock: Clock) -> None:
    client.post("/sources/example", headers={H: SID})
    clock.t = 101.0
    assert client.get("/sources", headers={H: SID}).json()["stato"] == "scaduto"
    assert client.post("/sources/example", headers={H: SID}).json()["stato"] == "attivo"


@pytest.mark.parametrize("name", ["osm_table", "data", "hazard_table"])
def test_downloadable_templates(client: TestClient, name: str) -> None:
    r = client.get(f"/sources/templates/{name}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert f"modello_{name}.csv" in r.headers["content-disposition"]
    assert r.text.splitlines()[0]


def test_unknown_template_422(client: TestClient) -> None:
    assert client.get("/sources/templates/boh").status_code == 422


def test_get_sessions_is_a_singleton_with_the_config_values() -> None:
    routes.get_sessions.cache_clear()
    try:
        a = routes.get_sessions()
        assert a is routes.get_sessions()
        assert a.ttl_seconds == 3600
    finally:
        routes.get_sessions.cache_clear()


def test_real_app_exposes_the_routes_and_the_header_cors() -> None:
    from crime_risk_analyzer.main import create_app

    app = create_app()
    http = TestClient(app)
    assert http.get("/sources/templates/data").status_code == 200
    pre = http.options(
        "/sources",
        headers={
            "Origin": "http://localhost:4200",
            "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": "x-session-id",
        },
    )
    assert pre.status_code == 200
    assert "DELETE" in pre.headers["access-control-allow-methods"]
    assert "x-session-id" in pre.headers["access-control-allow-headers"].lower()


def test_analysis_routes_activate_the_session() -> None:
    from crime_risk_analyzer.main import create_app

    store = SessionStore(ttl_seconds=100, max_sessions=2)
    app = create_app()
    app.dependency_overrides[routes.get_sessions] = lambda: store
    http = TestClient(app)
    store.activate(SID, _custom_set(), [])
    store._entries[SID].expires_at = -1.0  # pyright: ignore[reportPrivateUsage]
    r = http.post(
        "/analyze/baseline",
        json={"citta": "Roma", "zona": "Monti"},
        headers={H: SID},
    )
    assert r.status_code == 410


def _custom(id_: str) -> Any:
    import dataclasses

    from crime_risk_analyzer.sources.context import default_set

    return dataclasses.replace(default_set(), id=id_, kind="custom")


def _custom_set() -> Any:
    return _custom("custom-x")
