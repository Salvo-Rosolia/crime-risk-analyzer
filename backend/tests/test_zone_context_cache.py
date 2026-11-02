"""Bounded zone-context cache (#197), reused by /analyze/poi."""

from __future__ import annotations

from typing import Any, cast

from crime_risk_analyzer import zone_context_cache as cache
from crime_risk_analyzer.zone_context_cache import MAX_ZONES, TTL_SECONDS, ZoneContext


def _ctx(zone: str) -> ZoneContext:
    """Minimal ZoneContext: the cache does not inspect the content."""
    return ZoneContext(
        retrieval=cast(Any, {"citta": "Roma", "zona": zone, "pois": []}),
        grounded=cast(Any, {"zona": zone, "validated_risks": []}),
    )


def setup_function() -> None:
    cache.clear()


def test_get_returns_what_put_stored() -> None:
    cache.put("Roma", "Colosseo", _ctx("Colosseo"), now=0.0)
    got = cache.get("Roma", "Colosseo", now=1.0)
    assert got is not None
    assert got["grounded"]["zona"] == "Colosseo"


def test_get_is_case_and_whitespace_insensitive() -> None:
    """The client sends the zone back as it received it: the key is not fragile."""
    cache.put("Roma", "Colosseo", _ctx("Colosseo"), now=0.0)
    assert cache.get("  roma ", "COLOSSEO", now=1.0) is not None


def test_get_misses_on_unknown_zone() -> None:
    assert cache.get("Roma", "Trastevere", now=0.0) is None


def test_entry_expires_after_ttl() -> None:
    """OSM is a live source: a stale context would produce a narrative
    anchored to POIs that may no longer exist."""
    cache.put("Roma", "Colosseo", _ctx("Colosseo"), now=0.0)
    assert cache.get("Roma", "Colosseo", now=TTL_SECONDS - 1) is not None
    assert cache.get("Roma", "Colosseo", now=TTL_SECONDS + 1) is None


def test_evicts_oldest_beyond_max_zones() -> None:
    for i in range(MAX_ZONES + 1):
        cache.put("Roma", f"zona-{i}", _ctx(f"zona-{i}"), now=float(i))
    assert cache.get("Roma", "zona-0", now=1.0) is None
    assert cache.get("Roma", f"zona-{MAX_ZONES}", now=1.0) is not None


def test_clear_empties_the_cache() -> None:
    cache.put("Roma", "Colosseo", _ctx("Colosseo"), now=0.0)
    cache.clear()
    assert cache.get("Roma", "Colosseo", now=0.0) is None
