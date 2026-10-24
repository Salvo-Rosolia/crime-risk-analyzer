"""API di caricamento fonti: upload, stato, ritorno al default, modelli (#416)."""

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
from tests.sources._fattorie import (
    DATI_CSV,
    HAZARD_CSV,
    NS,
    ONTOLOGIA_TTL,
    OSM_CSV,
    confini_json,
)

SID = "sessione-di-prova-AAAA"
SID2 = "sessione-di-prova-BBBB"
H = "X-Session-Id"


class Orologio:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock() -> Orologio:
    return Orologio()


@pytest.fixture
def client(clock: Orologio) -> Iterator[TestClient]:
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


def _files(**sostituzioni: bytes | None) -> dict[str, tuple[str, bytes, str]]:
    base: dict[str, bytes | None] = {
        "ontology": ONTOLOGIA_TTL.encode(),
        "osm_table": OSM_CSV.encode(),
        "data": DATI_CSV.encode(),
        "hazard_table": HAZARD_CSV.encode(),
        "boundaries": confini_json(),
    }
    base.update(sostituzioni)
    nomi = {"ontology": "mini.ttl"}
    return {
        k: (nomi.get(k, f"{k}.csv"), v, "application/octet-stream")
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
    client: TestClient, sid: str | None = SID, **sostituzioni: bytes | None
) -> Any:
    headers = {H: sid} if sid else {}
    return client.post(
        "/sources", files=_files(**sostituzioni), data=_VOCAB, headers=headers
    )


def test_stato_senza_intestazione_e_default(client: TestClient) -> None:
    r = client.get("/sources")
    assert r.status_code == 200
    assert r.json() == {"stato": "default", "scade_tra_secondi": None, "set": None}


def test_upload_attiva_il_set(client: TestClient) -> None:
    r = _upload(client)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["stato"] == "attivo"
    assert corpo["scade_tra_secondi"] == 100
    assert corpo["set"]["classi"] == 4
    assert corpo["set"]["selettori_osm"] == 2
    assert corpo["set"]["luoghi"] == ["Comune di Esempio"]
    assert isinstance(corpo["set"]["avvisi"], list)
    stato = client.get("/sources", headers={H: SID}).json()
    assert stato["stato"] == "attivo"


def test_upload_senza_confini_che_coprano_i_dati_422(client: TestClient) -> None:
    r = _upload(client, boundaries=None)
    assert r.status_code == 422
    assert r.json()["detail"]["errore"] == "fonti_non_valide"


def test_upload_con_alias_tipo_poi_ambigui_422(client: TestClient) -> None:
    ontologia = ONTOLOGIA_TTL.replace('"Ospedale"@it', '"Banca"@it')
    r = _upload(client, ontology=ontologia.encode())
    assert r.status_code == 422
    assert r.json()["detail"]["errore"] == "fonti_non_valide"
    testo = str(r.json()["detail"])
    assert "alias_tipo_poi_ambiguo" in testo
    assert "Banca" in testo
    assert "Ospedale" in testo
    # il set non e' stato attivato
    assert client.get("/sources", headers={H: SID}).json()["stato"] == "default"


def test_upload_senza_intestazione_422(client: TestClient) -> None:
    assert _upload(client, sid=None).status_code == 422


def test_upload_intestazione_malformata_422(client: TestClient) -> None:
    assert _upload(client, sid="corto").status_code == 422


def test_upload_con_errori_riporta_tutto_e_non_attiva(client: TestClient) -> None:
    r = _upload(client, osm_table=b"osm_tag,classe\namenity=bank,Inesistente\n")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["errore"] == "fonti_non_valide"
    assert detail["errors"][0]["code"] == "classe_assente_dall_ontologia"
    assert detail["errors"][0]["file"] == "osm_table"
    assert client.get("/sources", headers={H: SID}).json()["stato"] == "default"


def test_upload_fallito_non_toglie_il_set_gia_attivo(client: TestClient) -> None:
    assert _upload(client).status_code == 200
    assert _upload(client, osm_table=b"x,y\n").status_code == 422
    assert client.get("/sources", headers={H: SID}).json()["stato"] == "attivo"


def test_file_oltre_il_limite_e_respinto(client: TestClient) -> None:
    enorme = b"osm_tag,classe\n" + b"a" * (MAX_BYTES_CSV + 10)
    r = _upload(client, osm_table=enorme)
    assert r.status_code == 422
    codici = [e["code"] for e in r.json()["detail"]["errors"]]
    assert "file_troppo_grande" in codici


def test_vocabolario_non_valido_422(client: TestClient) -> None:
    r = client.post(
        "/sources",
        files=_files(),
        data={**_VOCAB, "namespace": "senza-iri"},
        headers={H: SID},
    )
    assert r.status_code == 422


def test_sessioni_diverse_non_si_vedono(client: TestClient) -> None:
    assert _upload(client, sid=SID).status_code == 200
    assert client.get("/sources", headers={H: SID2}).json()["stato"] == "default"
    assert client.get("/probe", headers={H: SID2}).json() == {"set": "default"}
    assert client.get("/probe", headers={H: SID}).json()["set"] != "default"


def test_ogni_caricamento_ha_un_set_id_nuovo(client: TestClient) -> None:
    _upload(client)
    primo = client.get("/probe", headers={H: SID}).json()["set"]
    _upload(client)
    secondo = client.get("/probe", headers={H: SID}).json()["set"]
    assert primo != secondo


def test_probe_senza_intestazione_e_default(client: TestClient) -> None:
    assert client.get("/probe").json() == {"set": "default"}


def test_intestazione_malformata_sulle_rotte_di_analisi_e_default(
    client: TestClient,
) -> None:
    assert client.get("/probe", headers={H: "x"}).json() == {"set": "default"}


def test_scadenza_stato_e_rotte_di_analisi(client: TestClient, clock: Orologio) -> None:
    _upload(client)
    clock.t = 200
    stato = client.get("/sources", headers={H: SID}).json()
    assert stato["stato"] == "scaduto"
    r = client.get("/probe", headers={H: SID})
    assert r.status_code == 410
    assert r.json()["detail"]["errore"] == "fonti_scadute"
    # lo stato persiste: ogni rotta di analisi risponde 410, GET /sources resta
    # "scaduto" (non si ricade sul default finche' l'utente non sceglie)
    assert client.get("/probe", headers={H: SID}).status_code == 410
    assert client.get("/sources", headers={H: SID}).json()["stato"] == "scaduto"


def test_scaduto_si_pulisce_con_delete(client: TestClient, clock: Orologio) -> None:
    _upload(client)
    clock.t = 200
    assert client.get("/probe", headers={H: SID}).status_code == 410
    assert client.delete("/sources", headers={H: SID}).json()["stato"] == "default"
    assert client.get("/probe", headers={H: SID}).json() == {"set": "default"}


def test_scaduto_si_pulisce_con_nuovo_upload(
    client: TestClient, clock: Orologio
) -> None:
    _upload(client)
    clock.t = 200
    assert client.get("/probe", headers={H: SID}).status_code == 410
    assert _upload(client).json()["stato"] == "attivo"
    assert client.get("/probe", headers={H: SID}).json()["set"] != "default"


def test_upload_non_valido_non_pulisce_lo_scaduto(
    client: TestClient, clock: Orologio
) -> None:
    _upload(client)
    clock.t = 200
    assert _upload(client, osm_table=b"x").status_code == 422
    assert client.get("/sources", headers={H: SID}).json()["stato"] == "scaduto"


def test_upload_supera_il_limite_sull_ontologia(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes, "MAX_BYTES_ONTOLOGIA", 100)
    r = _upload(client)
    assert r.status_code == 422
    assert r.json()["detail"]["errore"] == "fonti_non_valide"
    assert client.get("/sources", headers={H: SID}).json()["stato"] == "default"


def test_upload_supera_il_limite_sui_confini(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes, "MAX_BYTES_GEOJSON", 10)
    r = _upload(client)
    assert r.status_code == 422
    assert r.json()["detail"]["errore"] == "fonti_non_valide"


def test_content_length_oltre_il_tetto_413(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes, "MAX_BYTES_RICHIESTA", 50)
    r = _upload(client)
    assert r.status_code == 413
    assert r.json()["detail"]["errore"] == "richiesta_troppo_grande"
    assert client.get("/sources", headers={H: SID}).json()["stato"] == "default"


def test_troppi_file_nel_multipart_400(client: TestClient) -> None:
    files = _files()
    files["extra"] = ("x.csv", b"a", "text/csv")
    files["extra2"] = ("y.csv", b"a", "text/csv")
    r = client.post("/sources", files=files, data=_VOCAB, headers={H: SID})
    assert r.status_code == 400


def test_troppi_campi_nel_multipart_400(client: TestClient) -> None:
    data = {**_VOCAB, "vulnerability": [f"v{i}" for i in range(40)]}
    r = client.post("/sources", files=_files(), data=data, headers={H: SID})
    assert r.status_code == 400


def test_upload_concorrenti_oltre_il_tetto_503(client: TestClient) -> None:
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


def test_sessioni_concorrenti_leggono_il_proprio_set() -> None:
    import httpx

    app = FastAPI()
    register_exception_handlers(app)
    store = SessionStore(ttl_seconds=100, max_sessions=4)
    store.activate(SID, _custom("set-a"), [])
    store.activate(SID2, _custom("set-b"), [])
    app.dependency_overrides[routes.get_sessions] = lambda: store

    @app.get("/probe", dependencies=[Depends(routes.activate_session)])
    async def probe() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        await asyncio.sleep(0.01)  # cede il controllo alla richiesta concorrente
        return {"set": current_id()}

    async def _run() -> list[str]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            risposte = await asyncio.gather(
                c.get("/probe", headers={H: SID}),
                c.get("/probe", headers={H: SID2}),
                c.get("/probe"),
            )
        return [r.json()["set"] for r in risposte]

    assert asyncio.run(_run()) == ["set-a", "set-b", "default"]


def test_default_toglie_il_set(client: TestClient) -> None:
    _upload(client)
    r = client.delete("/sources", headers={H: SID})
    assert r.status_code == 200
    assert r.json()["stato"] == "default"
    assert client.get("/probe", headers={H: SID}).json() == {"set": "default"}


def test_default_senza_intestazione_422_e_idempotente(client: TestClient) -> None:
    assert client.delete("/sources").status_code == 422
    assert client.delete("/sources", headers={H: SID}).status_code == 200
    assert client.delete("/sources", headers={H: SID}).status_code == 200


def test_esempio_si_attiva_con_un_solo_comando(client: TestClient) -> None:
    r = client.post("/sources/example", headers={H: SID})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["stato"] == "attivo"
    assert corpo["scade_tra_secondi"] == 100
    assert corpo["set"]["kind"] == "example"
    assert corpo["set"]["selettori_osm"] > 0
    assert corpo["set"]["luoghi"] == [
        "Comune di Milano",
        "Comune di Roma",
        "Comune di Napoli",
    ]
    assert any(a["code"] == "etichetta_mancante" for a in corpo["set"]["avvisi"])
    assert client.get("/probe", headers={H: SID}).json() == {"set": "example"}
    assert client.get("/sources", headers={H: SID}).json()["set"]["kind"] == "example"


def test_esempio_senza_intestazione_o_malformata_422(client: TestClient) -> None:
    assert client.post("/sources/example").status_code == 422
    assert client.post("/sources/example", headers={H: "corto"}).status_code == 422


def test_esempio_vale_solo_per_la_sessione_che_lo_attiva(client: TestClient) -> None:
    client.post("/sources/example", headers={H: SID})
    assert client.get("/probe", headers={H: SID2}).json() == {"set": "default"}
    assert client.get("/sources", headers={H: SID2}).json()["stato"] == "default"


def test_esempio_sostituisce_un_set_caricato_e_delete_torna_al_default(
    client: TestClient,
) -> None:
    assert _upload(client).status_code == 200
    assert client.get("/sources", headers={H: SID}).json()["set"]["kind"] == "custom"
    assert client.post("/sources/example", headers={H: SID}).status_code == 200
    assert client.get("/probe", headers={H: SID}).json() == {"set": "example"}
    assert client.delete("/sources", headers={H: SID}).json()["stato"] == "default"
    assert client.get("/probe", headers={H: SID}).json() == {"set": "default"}


def test_esempio_riattivato_dopo_la_scadenza(
    client: TestClient, clock: Orologio
) -> None:
    client.post("/sources/example", headers={H: SID})
    clock.t = 101.0
    assert client.get("/sources", headers={H: SID}).json()["stato"] == "scaduto"
    assert client.post("/sources/example", headers={H: SID}).json()["stato"] == "attivo"


@pytest.mark.parametrize("nome", ["osm_table", "data", "hazard_table"])
def test_modelli_scaricabili(client: TestClient, nome: str) -> None:
    r = client.get(f"/sources/templates/{nome}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert f"modello_{nome}.csv" in r.headers["content-disposition"]
    assert r.text.splitlines()[0]


def test_modello_sconosciuto_422(client: TestClient) -> None:
    assert client.get("/sources/templates/boh").status_code == 422


def test_get_sessions_e_un_singleton_con_i_valori_di_config() -> None:
    routes.get_sessions.cache_clear()
    try:
        a = routes.get_sessions()
        assert a is routes.get_sessions()
        assert a.ttl_seconds == 3600
    finally:
        routes.get_sessions.cache_clear()


def test_app_vera_espone_le_rotte_e_il_cors_dell_intestazione() -> None:
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


def test_le_rotte_di_analisi_attivano_la_sessione() -> None:
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
