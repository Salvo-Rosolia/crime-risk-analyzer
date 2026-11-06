"""Session store with source sets and expiry (#416)."""

import dataclasses
from typing import Any, cast

import pytest

from crime_risk_analyzer import zone_context_cache as cache
from crime_risk_analyzer.sources.context import bind, bind_session, default_set
from crime_risk_analyzer.sources.model import SourceSet
from crime_risk_analyzer.sources.session import (
    SessionStore,
    SourcesExpiredError,
    is_valid_session_id,
)
from crime_risk_analyzer.zone_context_cache import ZoneContext

SID = "abcdefghij" * 3 + "kl"
SID2 = "klmnopqrst" * 3 + "uv"


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _set(id_: str) -> SourceSet:
    return dataclasses.replace(default_set(), id=id_, kind="custom")


def _ctx() -> ZoneContext:
    return ZoneContext(retrieval=cast(Any, {}), grounded=cast(Any, {}))


def _store(ttl: float = 100.0, maximum: int = 2) -> tuple[SessionStore, Clock]:
    clock = Clock()
    return SessionStore(ttl_seconds=ttl, max_sessions=maximum, clock=clock), clock


def test_session_id_format() -> None:
    ok = "abcDEF012345_-xyz9876QWERTYuiopAB"
    assert is_valid_session_id(ok)
    assert not is_valid_session_id("corto")
    assert not is_valid_session_id("a" * 129)
    assert not is_valid_session_id(ok[:31] + " ")
    assert not is_valid_session_id(ok[:31] + "\n")
    assert not is_valid_session_id(ok[:31] + "è")


def test_no_set_means_nothing() -> None:
    store, _ = _store()
    assert store.get(SID) is None
    assert store.remaining_seconds(SID) is None


def test_activate_and_read() -> None:
    store, _ = _store()
    x = _set("x")
    store.activate(SID, x, [])
    entry = store.get(SID)
    assert entry is not None and entry.source_set is x
    assert store.get(SID2) is None


def test_expires_after_ttl_then_reports_expired() -> None:
    store, clock = _store(ttl=100)
    store.activate(SID, _set("x"), [])
    clock.t = 99
    assert store.get(SID) is not None
    clock.t = 99 + 101  # the access at 99 renewed the expiry (sliding window)
    with pytest.raises(SourcesExpiredError):
        store.get(SID)
    with pytest.raises(SourcesExpiredError):  # the state persists (#416)
        store.get(SID)
    assert store.was_expired(SID)


def test_new_upload_clears_the_expired_state() -> None:
    store, clock = _store(ttl=100)
    store.activate(SID, _set("x"), [])
    clock.t = 101
    with pytest.raises(SourcesExpiredError):
        store.get(SID)
    store.activate(SID, _set("y"), [])
    assert not store.was_expired(SID)
    entry = store.get(SID)
    assert entry is not None and entry.source_set.id == "y"


def test_access_renews_the_expiry() -> None:
    store, clock = _store(ttl=100)
    store.activate(SID, _set("x"), [])
    clock.t = 90
    assert store.get(SID) is not None
    clock.t = 180
    assert store.get(SID) is not None


def test_peek_does_not_renew() -> None:
    store, clock = _store(ttl=100)
    store.activate(SID, _set("x"), [])
    clock.t = 90
    assert store.remaining_seconds(SID) == 10
    clock.t = 101
    assert store.remaining_seconds(SID) is None


def test_expired_state_visible_without_consuming() -> None:
    store, clock = _store(ttl=100)
    store.activate(SID, _set("x"), [])
    clock.t = 101
    assert store.was_expired(SID)
    assert store.was_expired(SID)


def test_reset_returns_to_default_and_clears_the_expired_state() -> None:
    store, clock = _store(ttl=100)
    store.activate(SID, _set("x"), [])
    clock.t = 101
    store.reset(SID)
    assert not store.was_expired(SID)
    assert store.get(SID) is None


def test_new_upload_replaces_and_clears_the_cache_of_the_old_one() -> None:
    store, _ = _store()
    cache.clear()
    old = _set("vecchio")
    store.activate(SID, old, [])
    with bind_session(SID), bind(old):
        cache.put("Roma", "Monti", _ctx(), now=0.0)
    store.activate(SID, _set("nuovo"), [])
    with bind_session(SID), bind(old):
        assert cache.get("Roma", "Monti", now=1.0) is None
    entry = store.get(SID)
    assert entry is not None and entry.source_set.id == "nuovo"


def test_session_cap_evicts_the_oldest() -> None:
    store, clock = _store(maximum=2)
    store.activate(SID, _set("1"), [])
    clock.t = 1
    store.activate(SID2, _set("2"), [])
    clock.t = 2
    store.activate("c" * 24, _set("3"), [])
    with pytest.raises(SourcesExpiredError):
        store.get(SID)  # evicted: the user must know
    assert store.get(SID2) is not None
    assert store.get("c" * 24) is not None
    assert store.count() == 2


def test_cap_eviction_empties_the_zone_cache_of_the_evicted_set() -> None:
    store, clock = _store(maximum=1)
    cache.clear()
    old, new = _set("vecchio"), _set("nuovo")
    store.activate(SID, old, [])
    with bind_session(SID), bind(old):
        cache.put("Roma", "Monti", _ctx(), now=0.0)
    clock.t = 1
    store.activate(SID2, new, [])  # cap 1: SID gets evicted
    with bind_session(SID2), bind(new):
        cache.put("Roma", "Monti", _ctx(), now=0.0)
    with bind_session(SID), bind(old):
        assert cache.get("Roma", "Monti", now=1.0) is None
    with bind_session(SID2), bind(new):
        assert cache.get("Roma", "Monti", now=1.0) is not None


def test_ttl_exposed() -> None:
    store, _ = _store(ttl=42)
    assert store.ttl_seconds == 42


def test_remembered_expiries_are_bounded() -> None:
    store, clock = _store(ttl=1, maximum=1000)
    for i in range(300):
        store.activate(f"{i:016d}", _set(str(i)), [])
    clock.t = 5
    assert store.count() == 0
    assert not store.was_expired(f"{0:016d}")  # the oldest one has been forgotten
    assert store.was_expired(f"{299:016d}")
