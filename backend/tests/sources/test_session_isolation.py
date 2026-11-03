"""Zone cache and fingerprint do not mix different sessions (#416)."""

import dataclasses
from typing import Any, cast

from crime_risk_analyzer import zone_context_cache as cache
from crime_risk_analyzer.context_fingerprint import active_sources_id, fingerprint
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.sources.context import bind, current_id, default_set
from crime_risk_analyzer.sources.model import SourceSet
from crime_risk_analyzer.zone_context_cache import ZoneContext


def _other_set(id_: str) -> SourceSet:
    return dataclasses.replace(default_set(), id=id_, kind="custom")


def _ctx(marker: str) -> ZoneContext:
    return ZoneContext(
        retrieval=cast(Any, {"citta": "Roma", "zona": marker, "pois": []}),
        grounded=cast(Any, {"zona": marker, "validated_risks": []}),
    )


def _pois() -> list[Poi]:
    poi = cast(
        Poi,
        {"id": "node/1", "name": "A", "terminus_class": "Bank", "lat": 1.0, "lon": 2.0},
    )
    return [poi]


def setup_function() -> None:
    cache.clear()


def test_current_id_default_without_building_the_default() -> None:
    assert current_id() == "default"
    with bind(_other_set("x")):
        assert current_id() == "x"


def test_cache_of_different_sessions_does_not_mix() -> None:
    with bind(_other_set("a")):
        cache.put("Roma", "Monti", _ctx("a"), now=0.0)
    with bind(_other_set("b")):
        assert cache.get("Roma", "Monti", now=1.0) is None
        cache.put("Roma", "Monti", _ctx("b"), now=0.0)
    with bind(_other_set("a")):
        hit = cache.get("Roma", "Monti", now=1.0)
        assert hit is not None and hit["grounded"]["zona"] == "a"
    assert cache.get("Roma", "Monti", now=1.0) is None  # the default sees nothing


def test_default_cache_stays_visible_without_session() -> None:
    cache.put("Roma", "Monti", _ctx("d"), now=0.0)
    assert cache.get("Roma", "Monti", now=1.0) is not None
    with bind(_other_set("a")):
        assert cache.get("Roma", "Monti", now=1.0) is None


def test_purge_removes_only_the_entries_of_the_set() -> None:
    with bind(_other_set("a")):
        cache.put("Roma", "Monti", _ctx("a"), now=0.0)
    with bind(_other_set("b")):
        cache.put("Roma", "Monti", _ctx("b"), now=0.0)
    cache.purge("a")
    with bind(_other_set("a")):
        assert cache.get("Roma", "Monti", now=1.0) is None
    with bind(_other_set("b")):
        assert cache.get("Roma", "Monti", now=1.0) is not None


def test_active_sources_id_none_for_the_default() -> None:
    assert active_sources_id() is None
    with bind(_other_set("a")):
        assert active_sources_id() == "a"


def test_fingerprint_without_sources_is_identical_to_before() -> None:
    assert fingerprint(_pois()) == fingerprint(_pois(), sources_id=None)


def test_fingerprint_depends_on_the_set() -> None:
    base = fingerprint(_pois())
    a = fingerprint(_pois(), sources_id="a")
    b = fingerprint(_pois(), sources_id="b")
    assert len({base, a, b}) == 3


def test_fingerprint_with_istat_and_sources_does_not_collide() -> None:
    assert fingerprint(_pois(), istat_version="v1", sources_id="a") != fingerprint(
        _pois(), istat_version="v1"
    )
    assert fingerprint(_pois(), istat_version="v1", sources_id="a") != fingerprint(
        _pois(), istat_version="v1", sources_id="b"
    )
