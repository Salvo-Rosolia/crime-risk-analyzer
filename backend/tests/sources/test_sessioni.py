"""Archivio delle sessioni con set di fonti e scadenza (#416)."""

import dataclasses
from typing import Any, cast

import pytest

from crime_risk_analyzer import zone_context_cache as cache
from crime_risk_analyzer.sources.context import bind, default_set
from crime_risk_analyzer.sources.model import SourceSet
from crime_risk_analyzer.sources.session import (
    SessionStore,
    SourcesExpiredError,
    is_valid_session_id,
)
from crime_risk_analyzer.zone_context_cache import ZoneContext

SID = "a" * 24
SID2 = "b" * 24


class Orologio:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _set(id_: str) -> SourceSet:
    return dataclasses.replace(default_set(), id=id_, kind="custom")


def _ctx() -> ZoneContext:
    return ZoneContext(retrieval=cast(Any, {}), grounded=cast(Any, {}))


def _store(ttl: float = 100.0, massimo: int = 2) -> tuple[SessionStore, Orologio]:
    clock = Orologio()
    return SessionStore(ttl_seconds=ttl, max_sessions=massimo, clock=clock), clock


def test_formato_id_sessione() -> None:
    assert is_valid_session_id("abcDEF012345_-xyz9876")
    assert not is_valid_session_id("corto")
    assert not is_valid_session_id("a" * 129)
    assert not is_valid_session_id("a" * 15 + " ")
    assert not is_valid_session_id("a" * 15 + "\n")
    assert not is_valid_session_id("a" * 15 + "è")


def test_senza_set_niente() -> None:
    store, _ = _store()
    assert store.get(SID) is None
    assert store.remaining_seconds(SID) is None


def test_attiva_e_legge() -> None:
    store, _ = _store()
    x = _set("x")
    store.activate(SID, x, [])
    entry = store.get(SID)
    assert entry is not None and entry.source_set is x
    assert store.get(SID2) is None


def test_scade_dopo_il_ttl_e_poi_segnala_scaduto() -> None:
    store, clock = _store(ttl=100)
    store.activate(SID, _set("x"), [])
    clock.t = 99
    assert store.get(SID) is not None
    clock.t = 99 + 101  # l'accesso a 99 ha rinnovato la scadenza (finestra mobile)
    with pytest.raises(SourcesExpiredError):
        store.get(SID)
    with pytest.raises(SourcesExpiredError):  # lo stato persiste (#416)
        store.get(SID)
    assert store.was_expired(SID)


def test_nuovo_caricamento_pulisce_lo_scaduto() -> None:
    store, clock = _store(ttl=100)
    store.activate(SID, _set("x"), [])
    clock.t = 101
    with pytest.raises(SourcesExpiredError):
        store.get(SID)
    store.activate(SID, _set("y"), [])
    assert not store.was_expired(SID)
    entry = store.get(SID)
    assert entry is not None and entry.source_set.id == "y"


def test_accesso_rinnova_la_scadenza() -> None:
    store, clock = _store(ttl=100)
    store.activate(SID, _set("x"), [])
    clock.t = 90
    assert store.get(SID) is not None
    clock.t = 180
    assert store.get(SID) is not None


def test_peek_non_rinnova() -> None:
    store, clock = _store(ttl=100)
    store.activate(SID, _set("x"), [])
    clock.t = 90
    assert store.remaining_seconds(SID) == 10
    clock.t = 101
    assert store.remaining_seconds(SID) is None


def test_stato_scaduto_visibile_senza_consumare() -> None:
    store, clock = _store(ttl=100)
    store.activate(SID, _set("x"), [])
    clock.t = 101
    assert store.was_expired(SID)
    assert store.was_expired(SID)


def test_reset_torna_al_default_e_pulisce_lo_scaduto() -> None:
    store, clock = _store(ttl=100)
    store.activate(SID, _set("x"), [])
    clock.t = 101
    store.reset(SID)
    assert not store.was_expired(SID)
    assert store.get(SID) is None


def test_nuovo_caricamento_sostituisce_e_pulisce_la_cache_del_vecchio() -> None:
    store, _ = _store()
    cache.clear()
    vecchio = _set("vecchio")
    store.activate(SID, vecchio, [])
    with bind(vecchio):
        cache.put("Roma", "Monti", _ctx(), now=0.0)
    store.activate(SID, _set("nuovo"), [])
    with bind(vecchio):
        assert cache.get("Roma", "Monti", now=1.0) is None
    entry = store.get(SID)
    assert entry is not None and entry.source_set.id == "nuovo"


def test_tetto_di_sessioni_sfratta_la_piu_vecchia() -> None:
    store, clock = _store(massimo=2)
    store.activate(SID, _set("1"), [])
    clock.t = 1
    store.activate(SID2, _set("2"), [])
    clock.t = 2
    store.activate("c" * 24, _set("3"), [])
    with pytest.raises(SourcesExpiredError):
        store.get(SID)  # sfrattata: l'utente lo deve sapere
    assert store.get(SID2) is not None
    assert store.get("c" * 24) is not None
    assert store.count() == 2


def test_sfratto_per_tetto_svuota_la_cache_di_zona_del_set_sfrattato() -> None:
    store, clock = _store(massimo=1)
    cache.clear()
    vecchio, nuovo = _set("vecchio"), _set("nuovo")
    store.activate(SID, vecchio, [])
    with bind(vecchio):
        cache.put("Roma", "Monti", _ctx(), now=0.0)
    with bind(nuovo):
        cache.put("Roma", "Monti", _ctx(), now=0.0)
    clock.t = 1
    store.activate(SID2, nuovo, [])  # tetto 1: SID viene sfrattata
    with bind(vecchio):
        assert cache.get("Roma", "Monti", now=1.0) is None
    with bind(nuovo):
        assert cache.get("Roma", "Monti", now=1.0) is not None


def test_ttl_esposto() -> None:
    store, _ = _store(ttl=42)
    assert store.ttl_seconds == 42


def test_le_scadenze_ricordate_sono_limitate() -> None:
    store, clock = _store(ttl=1, massimo=1000)
    for i in range(300):
        store.activate(f"{i:016d}", _set(str(i)), [])
    clock.t = 5
    assert store.count() == 0
    assert not store.was_expired(f"{0:016d}")  # la piu' vecchia e' stata dimenticata
    assert store.was_expired(f"{299:016d}")
