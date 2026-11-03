"""Tests for the zone -> bbox geocoding (#15). Nominatim is always mocked."""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from typing import Any, cast

import pytest
from geopy.exc import GeocoderServiceError  # pyright: ignore[reportMissingTypeStubs]

import crime_risk_analyzer.geocoding as _geo_mod
from crime_risk_analyzer import geocoding
from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.geocoding import (
    GeocodingError,
    ZoneNotFoundError,
    geocode_zone,
)
from crime_risk_analyzer.models.geo import Bbox


def _clear_geocoding_state() -> None:
    """Empties the shared module state: settings, RateLimiter and the three stores.

    ``get_settings`` and the singleton RateLimiter (``_get_rate_limited_call``,
    which carries the throttling state ``_last_call``, shared by geocode and
    reverse since #318) are cached per process: without a reset the tests would
    contaminate each other (residual sleeps, stale delay from the settings of
    another test). The same holds for the caches: a negative entry left by a test
    (#376) would make ``None`` come back to another one without touching the fake.
    """
    get_settings.cache_clear()
    _geo_mod._get_rate_limited_call.cache_clear()  # pyright: ignore[reportPrivateUsage]
    _geo_mod._CACHE.clear()  # pyright: ignore[reportPrivateUsage]
    _geo_mod._FREEFORM_CACHE.clear()  # pyright: ignore[reportPrivateUsage]
    _geo_mod._FREEFORM_NEGATIVE_CACHE.clear()  # pyright: ignore[reportPrivateUsage]


@pytest.fixture(autouse=True)
def _reset_geocoding_state() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Resets the shared module state before/after each test."""
    _clear_geocoding_state()
    yield
    _clear_geocoding_state()


class _FakeLocation:
    """Stub of the geopy Location: latitude/longitude + raw['boundingbox']."""

    def __init__(self, lat: float, lon: float, boundingbox: list[str] | None) -> None:
        self.latitude = lat
        self.longitude = lon
        self.raw: dict[str, Any] = {}
        if boundingbox is not None:
            self.raw["boundingbox"] = boundingbox


class _FakeGeocoder:
    """Stub of the Nominatim: returns a predefined location or raises."""

    def __init__(
        self, location: _FakeLocation | None = None, exc: Exception | None = None
    ) -> None:
        self._location = location
        self._exc = exc
        self.queries: list[str] = []
        self.calls: list[dict[str, object]] = []
        self.reverse_queries: list[tuple[float, float]] = []
        self.reverse_calls: list[dict[str, object]] = []

    def geocode(self, query: str, **kwargs: object) -> _FakeLocation | None:
        self.queries.append(query)
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._location

    def reverse(
        self, query: tuple[float, float], **kwargs: object
    ) -> _FakeLocation | None:
        """Stub of ``geolocator.reverse`` (#318): records query and kwargs as
        ``.geocode`` already does above, so the tests can exercise the reverse branch
        of ``_nominatim_dispatch`` instead of monkeypatching the accessor.
        """
        self.reverse_queries.append(query)
        self.reverse_calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._location


def _patch_geocoder(monkeypatch: pytest.MonkeyPatch, fake: _FakeGeocoder) -> None:
    import crime_risk_analyzer.geocoding as mod

    monkeypatch.setattr(mod, "_get_geolocator", lambda: fake)


def test_geocode_zone_returns_lat_lon_bbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zone found -> dict with lat, lon, bbox (lat_min, lon_min, lat_max, lon_max)."""
    # Nominatim boundingbox: [lat_min, lat_max, lon_min, lon_max] as strings.
    fake = _FakeGeocoder(
        _FakeLocation(41.8902, 12.4922, ["41.88", "41.90", "12.48", "12.50"])
    )
    _patch_geocoder(monkeypatch, fake)

    result = geocode_zone("Colosseo", "Roma")

    assert result["lat"] == pytest.approx(41.8902)
    assert result["lon"] == pytest.approx(12.4922)
    assert result["bbox"] == (41.88, 12.48, 41.90, 12.50)


def test_geocode_zone_query_includes_zone_and_city(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The query passed to Nominatim contains zona and citta."""
    fake = _FakeGeocoder(_FakeLocation(45.46, 9.19, ["45.45", "45.47", "9.18", "9.20"]))
    _patch_geocoder(monkeypatch, fake)

    geocode_zone("Duomo", "Milano")

    assert "Duomo" in fake.queries[0]
    assert "Milano" in fake.queries[0]


def test_geocode_zone_not_found_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nominatim returns None -> ZoneNotFoundError (zona+citta in the message)."""
    _patch_geocoder(monkeypatch, _FakeGeocoder(location=None))

    with pytest.raises(ZoneNotFoundError, match="Duomo"):
        geocode_zone("Duomo", "Milano")


def test_geocode_zone_missing_bbox_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Location without boundingbox -> ZoneNotFoundError (zone not usable)."""
    _patch_geocoder(monkeypatch, _FakeGeocoder(_FakeLocation(41.0, 12.0, None)))

    with pytest.raises(ZoneNotFoundError):
        geocode_zone("Ignota", "Roma")


def test_geocode_zone_bbox_wrong_length_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """boundingbox present but of unexpected length -> ZoneNotFoundError."""
    _patch_geocoder(
        monkeypatch, _FakeGeocoder(_FakeLocation(41.0, 12.0, ["41.0", "42.0"]))
    )

    with pytest.raises(ZoneNotFoundError):
        geocode_zone("Strana", "Roma")


def test_geocode_zone_service_error_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service error (timeout/HTTP) -> GeocodingError, not a raw exception."""
    _patch_geocoder(monkeypatch, _FakeGeocoder(exc=GeocoderServiceError("boom")))

    with pytest.raises(GeocodingError):
        geocode_zone("Colosseo", "Roma")


def test_geocode_zone_passes_country_codes_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """country_codes and timeout come FROM the settings, not from hardcoded values.

    It uses NON-default sentinels (``fr``/``7``) so the test fails even if one day
    the values were wired to the default ("it"/10.0): the only proof that they
    really come from the configuration.
    """
    monkeypatch.setenv("GEOCODING_COUNTRY_CODES", "fr")
    monkeypatch.setenv("GEOCODING_TIMEOUT_SECONDS", "7")
    get_settings.cache_clear()

    fake = _FakeGeocoder(
        _FakeLocation(41.89, 12.49, ["41.88", "41.90", "12.48", "12.50"])
    )
    _patch_geocoder(monkeypatch, fake)

    geocode_zone("Colosseo", "Roma")

    assert fake.calls[0]["country_codes"] == "fr"
    assert fake.calls[0]["timeout"] == 7.0


def test_geocode_zone_caches_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """With cache_enabled, the second call does NOT query the geocoder."""
    fake = _FakeGeocoder(
        _FakeLocation(41.89, 12.49, ["41.88", "41.90", "12.48", "12.50"])
    )
    _patch_geocoder(monkeypatch, fake)

    first = geocode_zone("Colosseo", "Roma")
    second = geocode_zone("Colosseo", "Roma")

    assert first == second
    assert len(fake.queries) == 1  # second answer from the cache


def test_geocode_zone_cache_disabled_queries_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CACHE_ENABLED", "false")
    # minimum min_delay (gt=0) + rebuilt limiter: zeroes the ~1s of real sleep on the
    # 2nd call keeping the config constraint.
    monkeypatch.setenv("GEOCODING_MIN_DELAY_SECONDS", "0.001")
    get_settings.cache_clear()
    _geo_mod._get_rate_limited_call.cache_clear()  # pyright: ignore[reportPrivateUsage]
    fake = _FakeGeocoder(
        _FakeLocation(41.89, 12.49, ["41.88", "41.90", "12.48", "12.50"])
    )
    _patch_geocoder(monkeypatch, fake)

    geocode_zone("Colosseo", "Roma")
    geocode_zone("Colosseo", "Roma")

    assert len(fake.queries) == 2
    # M1: with the cache disabled the store is NOT populated. It catches the
    # mutation "only the read-gate removed but the write stays": without this
    # assert, an entry written with the cache off would go unnoticed.
    assert len(_geo_mod._CACHE) == 0  # pyright: ignore[reportPrivateUsage]


def test_geocode_zone_does_not_cache_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure does not populate the cache: the next call really retries."""
    # minimum min_delay (gt=0) + rebuilt limiter: zeroes the ~1s of real sleep
    # between the 2 calls keeping the config constraint.
    monkeypatch.setenv("GEOCODING_MIN_DELAY_SECONDS", "0.001")
    get_settings.cache_clear()
    _geo_mod._get_rate_limited_call.cache_clear()  # pyright: ignore[reportPrivateUsage]
    failing = _FakeGeocoder(exc=GeocoderServiceError("boom"))
    _patch_geocoder(monkeypatch, failing)
    with pytest.raises(GeocodingError):
        geocode_zone("Colosseo", "Roma")

    ok = _FakeGeocoder(
        _FakeLocation(41.89, 12.49, ["41.88", "41.90", "12.48", "12.50"])
    )
    _patch_geocoder(monkeypatch, ok)
    result = geocode_zone("Colosseo", "Roma")
    assert result["lat"] == pytest.approx(41.89)
    assert len(ok.queries) == 1  # it did not serve an error from the cache


def test_geocode_zone_cache_key_normalizes_case_and_spaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case/space variants hit the same cache entry (#115)."""
    fake = _FakeGeocoder(
        _FakeLocation(41.89, 12.49, ["41.88", "41.90", "12.48", "12.50"])
    )
    _patch_geocoder(monkeypatch, fake)
    geocode_zone("Colosseo", "Roma")
    geocode_zone("  colosseo  ", " ROMA ")
    assert len(fake.queries) == 1  # second from the cache thanks to the normalization


def test_geocode_zone_cache_distinguishes_zones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C1: different zones do NOT collide in the cache -> two distinct lookups (#115).

    Guard against a collapsed ``_cache_key`` (one that ignored the zone): two
    different zones in the same city must query the geocoder twice, not serve the
    second from the entry of the first.
    """
    monkeypatch.setenv("GEOCODING_MIN_DELAY_SECONDS", "0.001")
    get_settings.cache_clear()
    _geo_mod._get_rate_limited_call.cache_clear()  # pyright: ignore[reportPrivateUsage]
    fake = _FakeGeocoder(
        _FakeLocation(41.89, 12.49, ["41.88", "41.90", "12.48", "12.50"])
    )
    _patch_geocoder(monkeypatch, fake)

    geocode_zone("Colosseo", "Roma")
    geocode_zone("Trastevere", "Roma")  # different zone -> NOT from the cache

    assert len(fake.queries) == 2


def test_geocode_zone_cache_distinguishes_cities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C1: same zone but different city does NOT collide -> two distinct lookups
    (#115).

    Guard against a ``_cache_key`` that ignored the city: "Duomo" in Milano and
    "Duomo" in Roma are different entities and must query the geocoder twice.
    """
    monkeypatch.setenv("GEOCODING_MIN_DELAY_SECONDS", "0.001")
    get_settings.cache_clear()
    _geo_mod._get_rate_limited_call.cache_clear()  # pyright: ignore[reportPrivateUsage]
    fake = _FakeGeocoder(_FakeLocation(45.46, 9.19, ["45.45", "45.47", "9.18", "9.20"]))
    _patch_geocoder(monkeypatch, fake)

    geocode_zone("Duomo", "Milano")
    geocode_zone("Duomo", "Roma")  # different city -> NOT from the cache

    assert len(fake.queries) == 2


def test_geocode_zone_does_not_cache_zone_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M2: a zone not found (location None) is NOT cached (#115).

    It catches the "negative caching" mutation: if the first ZoneNotFoundError
    ended up in the store, the second call (with a geocoder now valid) on the same
    (zona, citta) would be served from the cache without really querying the
    service, staying stuck on a transient error.
    """
    monkeypatch.setenv("GEOCODING_MIN_DELAY_SECONDS", "0.001")
    get_settings.cache_clear()
    _geo_mod._get_rate_limited_call.cache_clear()  # pyright: ignore[reportPrivateUsage]
    _patch_geocoder(monkeypatch, _FakeGeocoder(location=None))
    with pytest.raises(ZoneNotFoundError):
        geocode_zone("Duomo", "Milano")

    ok = _FakeGeocoder(_FakeLocation(45.46, 9.19, ["45.45", "45.47", "9.18", "9.20"]))
    _patch_geocoder(monkeypatch, ok)
    result = geocode_zone("Duomo", "Milano")

    assert result["lat"] == pytest.approx(45.46)
    assert len(ok.queries) == 1  # it REALLY queried, not served from the negative cache


def test_rate_limiter_wired_with_settings() -> None:
    """The rate limiter uses min_delay from the settings, max_retries=0, no swallow."""
    from geopy.extra.rate_limiter import (  # pyright: ignore[reportMissingTypeStubs]
        RateLimiter,
    )

    rl = _geo_mod._get_rate_limited_call()  # pyright: ignore[reportPrivateUsage]
    assert isinstance(rl, RateLimiter)
    assert rl.min_delay_seconds == get_settings().geocoding_min_delay_seconds
    assert rl.max_retries == 0
    assert rl.swallow_exceptions is False


def test_rate_limiter_builds_with_high_min_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """min_delay > 5s must not break the construction of the RateLimiter (#115)."""
    from geopy.extra.rate_limiter import (  # pyright: ignore[reportMissingTypeStubs]
        RateLimiter,
    )

    monkeypatch.setenv("GEOCODING_MIN_DELAY_SECONDS", "6")
    get_settings.cache_clear()
    _geo_mod._get_rate_limited_call.cache_clear()  # pyright: ignore[reportPrivateUsage]
    rl = _geo_mod._get_rate_limited_call()  # pyright: ignore[reportPrivateUsage]
    assert isinstance(rl, RateLimiter)
    assert rl.min_delay_seconds == 6.0
    assert rl.error_wait_seconds >= rl.min_delay_seconds


def test_rate_limiter_throttles_second_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two close calls -> applies a delay >= min_delay (fake clock)."""
    monkeypatch.setenv("GEOCODING_MIN_DELAY_SECONDS", "1")
    get_settings.cache_clear()
    _geo_mod._get_rate_limited_call.cache_clear()  # pyright: ignore[reportPrivateUsage]

    fake = _FakeGeocoder(
        _FakeLocation(41.89, 12.49, ["41.88", "41.90", "12.48", "12.50"])
    )
    _patch_geocoder(monkeypatch, fake)

    now = [1000.0]
    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds  # time advances by as much as is slept

    monkeypatch.setattr("geopy.extra.rate_limiter.sleep", fake_sleep)
    rl = _geo_mod._get_rate_limited_call()  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(rl, "_clock", lambda: now[0])

    geocode_zone("Colosseo", "Roma")  # 1st call: no sleep
    # cache disabled to force a real 2nd call
    monkeypatch.setenv("CACHE_ENABLED", "false")
    get_settings.cache_clear()
    geocode_zone("Trastevere", "Roma")  # 2nd call: throttle

    assert slept and slept[0] == pytest.approx(1.0)


# --- #170: bound of _CACHE (FIFO eviction) + defensive copy on the cache hit ---


def test_cache_evicts_oldest_when_full(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once _CACHE_MAXSIZE is exceeded, the oldest entry (FIFO) is evicted (#170)."""
    monkeypatch.setattr(_geo_mod, "_CACHE_MAXSIZE", 3)
    # minimum min_delay (gt=0) + rebuilt limiter: zeroes the ~1s of real sleep
    # between the calls keeping the config constraint.
    monkeypatch.setenv("GEOCODING_MIN_DELAY_SECONDS", "0.001")
    get_settings.cache_clear()
    _geo_mod._get_rate_limited_call.cache_clear()  # pyright: ignore[reportPrivateUsage]
    fake = _FakeGeocoder(
        _FakeLocation(41.89, 12.49, ["41.88", "41.90", "12.48", "12.50"])
    )
    _patch_geocoder(monkeypatch, fake)

    for zona in ("A", "B", "C", "D"):
        geocode_zone(zona, "Roma")

    cache = _geo_mod._CACHE  # pyright: ignore[reportPrivateUsage]
    assert len(cache) == 3
    # FIFO: "A" (the oldest) was evicted; "D" (the last) is there.
    assert _geo_mod._cache_key("A", "Roma") not in cache  # pyright: ignore[reportPrivateUsage]
    assert _geo_mod._cache_key("D", "Roma") in cache  # pyright: ignore[reportPrivateUsage]


def test_cache_hit_returns_defensive_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cache hit returns a COPY: mutating it does not poison the entry (#170)."""
    fake = _FakeGeocoder(
        _FakeLocation(41.89, 12.49, ["41.88", "41.90", "12.48", "12.50"])
    )
    _patch_geocoder(monkeypatch, fake)

    geocode_zone("Colosseo", "Roma")  # populates the cache (miss)
    hit = geocode_zone("Colosseo", "Roma")  # cache hit
    hit["lat"] = 0.0  # a consumer mutates the returned dict

    again = geocode_zone("Colosseo", "Roma")  # new cache hit
    assert again["lat"] == pytest.approx(41.89)  # the entry in the cache is intact


def test_cache_miss_returns_defensive_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cache-miss return is a copy too: mutating it does not poison (#170)."""
    fake = _FakeGeocoder(
        _FakeLocation(41.89, 12.49, ["41.88", "41.90", "12.48", "12.50"])
    )
    _patch_geocoder(monkeypatch, fake)

    miss = geocode_zone("Colosseo", "Roma")  # cache miss: builds and stores
    miss["lat"] = 0.0  # mutates the dict just returned

    hit = geocode_zone("Colosseo", "Roma")  # cache hit on the stored entry
    assert hit["lat"] == pytest.approx(41.89)  # the entry in the cache is not aliased


def test_get_geolocator_builds_nominatim() -> None:
    """The default provider builds a Nominatim (no network call)."""
    from geopy.geocoders import (  # pyright: ignore[reportMissingTypeStubs]
        Nominatim,
    )

    from crime_risk_analyzer.geocoding import (
        _get_geolocator,  # pyright: ignore[reportPrivateUsage]
    )

    geolocator = _get_geolocator()
    assert isinstance(geolocator, Nominatim)


def test_get_geolocator_wires_user_agent_into_header() -> None:
    """Constant -> constructor -> header chain: the geolocator UA == _USER_AGENT.

    Real fail-if-removed on the *wired* value: a constructor with a diverging value
    (or without a contact URL) makes the test fail, not just the value of the
    constant.
    """
    from crime_risk_analyzer.geocoding import (
        _USER_AGENT,  # pyright: ignore[reportPrivateUsage]
        _get_geolocator,  # pyright: ignore[reportPrivateUsage]
    )

    geolocator = _get_geolocator()
    headers = cast("dict[str, str]", geolocator.headers)  # pyright: ignore[reportUnknownMemberType]
    user_agent = headers["User-Agent"]

    assert user_agent == _USER_AGENT
    assert "https://github.com/Salvo-Rosolia/crime-risk-analyzer" in user_agent


# --- #204: minimum bbox size floor (_enforce_min_bbox) ---


def test_min_bbox_floor_expands_tiny_landmark_bbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tiny bbox (landmark) is expanded to at least 2*half_span on BOTH axes,
    preserving the midpoint; lat/lon stay those of Nominatim (#204).
    """
    # Nominatim boundingbox [lat_min, lat_max, lon_min, lon_max]: span ~0.001 degrees
    # (a building: it is the case that gave 0 POIs from Overpass -> map not
    # recentered).
    fake = _FakeGeocoder(
        _FakeLocation(41.8902, 12.4922, ["41.8897", "41.8907", "12.4917", "12.4927"])
    )
    _patch_geocoder(monkeypatch, fake)
    half_span = get_settings().geocoding_min_bbox_half_span_deg

    result = geocode_zone("Colosseo", "Roma")
    bbox = result["bbox"]

    # both sides expanded to at least 2*half_span (float tolerance)
    assert bbox.max_lat - bbox.min_lat >= 2 * half_span - 1e-9
    assert bbox.max_lon - bbox.min_lon >= 2 * half_span - 1e-9
    # SYMMETRIC expansion: the midpoint of the original bbox is preserved
    assert (bbox.min_lat + bbox.max_lat) / 2 == pytest.approx(41.8902)
    assert (bbox.min_lon + bbox.max_lon) / 2 == pytest.approx(12.4922)
    # lat/lon = those of Nominatim, unchanged by the floor on the bbox
    assert result["lat"] == pytest.approx(41.8902)
    assert result["lon"] == pytest.approx(12.4922)


def test_min_bbox_floor_leaves_large_bbox_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An already large bbox (neighborhood, span ~0.05 degrees) is NOT shrunk (#204).

    "Expand-only": with a bbox beyond the threshold the min/max keep the original
    extremes, so the result must be identical to the parsed input.
    """
    fake = _FakeGeocoder(
        _FakeLocation(41.885, 12.485, ["41.86", "41.91", "12.46", "12.51"])
    )
    _patch_geocoder(monkeypatch, fake)

    result = geocode_zone("Centro Storico", "Roma")

    assert result["bbox"] == (41.86, 12.46, 41.91, 12.51)


def test_min_bbox_floor_expands_single_narrow_axis_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bbox narrow on ONE axis: expands that axis, the other stays unchanged (#204)."""
    # narrow lat (~0.001), already wide lon (~0.05).
    fake = _FakeGeocoder(
        _FakeLocation(41.8902, 12.485, ["41.8897", "41.8907", "12.46", "12.51"])
    )
    _patch_geocoder(monkeypatch, fake)
    half_span = get_settings().geocoding_min_bbox_half_span_deg

    result = geocode_zone("Via Stretta", "Roma")
    bbox = result["bbox"]

    # lat axis (narrow) expanded to at least 2*half_span (float tolerance)
    assert bbox.max_lat - bbox.min_lat >= 2 * half_span - 1e-9
    # lon axis (already wide) intact
    assert bbox.min_lon == pytest.approx(12.46)
    assert bbox.max_lon == pytest.approx(12.51)


def test_enforce_min_bbox_expands_when_below_threshold() -> None:
    """_enforce_min_bbox: bbox below threshold -> expanded to 2*half_span, midpoint
    fixed."""
    from crime_risk_analyzer.geocoding import (
        _enforce_min_bbox,  # pyright: ignore[reportPrivateUsage]
    )

    bbox = Bbox(min_lat=10.0, min_lon=20.0, max_lat=10.002, max_lon=20.002)
    out = _enforce_min_bbox(bbox, 0.01)

    assert out.max_lat - out.min_lat == pytest.approx(0.02)
    assert out.max_lon - out.min_lon == pytest.approx(0.02)
    assert (out.min_lat + out.max_lat) / 2 == pytest.approx(10.001)
    assert (out.min_lon + out.max_lon) / 2 == pytest.approx(20.001)


def test_enforce_min_bbox_noop_when_above_threshold() -> None:
    """_enforce_min_bbox: bbox already beyond threshold -> unchanged (not shrunk)."""
    from crime_risk_analyzer.geocoding import (
        _enforce_min_bbox,  # pyright: ignore[reportPrivateUsage]
    )

    bbox = Bbox(min_lat=10.0, min_lon=20.0, max_lat=10.05, max_lon=20.05)
    out = _enforce_min_bbox(bbox, 0.01)

    assert out == bbox


def test_min_bbox_floor_threshold_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing geocoding_min_bbox_half_span_deg changes the expanded width (#204)."""
    monkeypatch.setenv("GEOCODING_MIN_BBOX_HALF_SPAN_DEG", "0.05")
    get_settings.cache_clear()
    fake = _FakeGeocoder(
        _FakeLocation(41.8902, 12.4922, ["41.8897", "41.8907", "12.4917", "12.4927"])
    )
    _patch_geocoder(monkeypatch, fake)

    result = geocode_zone("Colosseo", "Roma")
    bbox = result["bbox"]

    # with half_span=0.05 every side is extended to at least 0.10 degrees (float
    # tolerance)
    assert bbox.max_lat - bbox.min_lat >= 0.10 - 1e-9
    assert bbox.max_lon - bbox.min_lon >= 0.10 - 1e-9


def test_enforce_min_bbox_noop_at_exact_threshold() -> None:
    """_enforce_min_bbox: span EXACTLY 2*half_span on BOTH axes -> unchanged.

    Boundary case between "expand" and "leave alone": it shields the ``min``/
    ``max`` logic against a future refactor to ``<`` vs ``<=`` (a strict ``<``
    would let the case through to the expansion branch).
    """
    from crime_risk_analyzer.geocoding import (
        _enforce_min_bbox,  # pyright: ignore[reportPrivateUsage]
    )

    half_span = 0.01
    lat_mid, lon_mid = 41.9, 12.5
    # bbox built as midpoint +/- half_span: span == exactly 2*half_span (float-exact,
    # so the equality with the input is meaningful and not flaky).
    bbox = Bbox(
        min_lat=lat_mid - half_span,
        min_lon=lon_mid - half_span,
        max_lat=lat_mid + half_span,
        max_lon=lon_mid + half_span,
    )
    out = _enforce_min_bbox(bbox, half_span)

    assert out == bbox


def test_min_bbox_floor_expands_degenerate_point_bbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Degenerate point bbox (min==max on both axes) -> expanded to span
    2*half_span on both axes, centered on the point (#204).

    It is the real worst case of the landmark: Nominatim for a point feature
    returns a zero-area boundingbox (0 POIs from Overpass without the floor).
    """
    fake = _FakeGeocoder(
        _FakeLocation(41.8902, 12.4922, ["41.8902", "41.8902", "12.4922", "12.4922"])
    )
    _patch_geocoder(monkeypatch, fake)
    half_span = get_settings().geocoding_min_bbox_half_span_deg

    result = geocode_zone("Fontana di Trevi", "Roma")
    bbox = result["bbox"]

    # both sides expanded to exactly 2*half_span
    assert bbox.max_lat - bbox.min_lat == pytest.approx(2 * half_span)
    assert bbox.max_lon - bbox.min_lon == pytest.approx(2 * half_span)
    # centered on the degenerate point (symmetric expansion)
    assert (bbox.min_lat + bbox.max_lat) / 2 == pytest.approx(41.8902)
    assert (bbox.min_lon + bbox.max_lon) / 2 == pytest.approx(12.4922)


# --- #318: shared rate limiter (geocode+reverse) + free reverse/forward ---


class _FakeReverseLocation:
    def __init__(self, address: dict[str, str]) -> None:
        self.raw = {"address": address}


def test_reverse_geocode_label_from_address(monkeypatch: pytest.MonkeyPatch) -> None:
    loc = _FakeReverseLocation({"city": "Roma", "suburb": "Trastevere"})

    def _fake_dispatch(op: str, arg: object) -> object:
        assert op == "reverse"
        assert arg == (41.8, 12.5)
        return loc

    geocoding._get_rate_limited_call.cache_clear()  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(geocoding, "_get_rate_limited_call", lambda: _fake_dispatch)
    citta, zona = geocoding.reverse_geocode_label(41.8, 12.5)
    assert citta == "Roma"
    assert zona == "Trastevere"


def test_reverse_geocode_label_fallback_on_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _none_dispatch(op: str, arg: object) -> object:
        return None

    monkeypatch.setattr(geocoding, "_get_rate_limited_call", lambda: _none_dispatch)
    citta, zona = geocoding.reverse_geocode_label(41.8, 12.5)
    assert citta == "area 41.8000,12.5000"
    assert zona == "zona non identificata"


def test_reverse_geocode_label_fallback_on_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(op: str, arg: object) -> object:
        raise GeocoderServiceError("giu")

    monkeypatch.setattr(geocoding, "_get_rate_limited_call", lambda: _boom)
    citta, zona = geocoding.reverse_geocode_label(41.8, 12.5)
    assert citta == "area 41.8000,12.5000"
    assert zona == "zona non identificata"


def test_geocode_freeform_success(monkeypatch: pytest.MonkeyPatch) -> None:
    loc = _FakeReverseLocation({})
    loc.latitude = 41.9  # type: ignore[attr-defined]
    loc.longitude = 12.5  # type: ignore[attr-defined]

    def _loc_dispatch(op: str, arg: object) -> object:
        return loc

    monkeypatch.setattr(geocoding, "_get_rate_limited_call", lambda: _loc_dispatch)
    assert geocoding.geocode_freeform("Duomo di Milano") == (41.9, 12.5)


def test_geocode_freeform_no_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _none_dispatch(op: str, arg: object) -> object:
        return None

    monkeypatch.setattr(geocoding, "_get_rate_limited_call", lambda: _none_dispatch)
    assert geocoding.geocode_freeform("xyzxyz") is None


# --- #344: bounded cache of geocode_freeform ("go to a place" box) ---


def _fast_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """minimum min_delay (gt=0) + rebuilt limiter: no real sleeps."""
    monkeypatch.setenv("GEOCODING_MIN_DELAY_SECONDS", "0.001")
    get_settings.cache_clear()
    _geo_mod._get_rate_limited_call.cache_clear()  # pyright: ignore[reportPrivateUsage]


def test_geocode_freeform_caches_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """With cache_enabled, the same repeated query does NOT query Nominatim again."""
    fake = _FakeGeocoder(_FakeLocation(45.464, 9.19, None))
    _patch_geocoder(monkeypatch, fake)

    first = geocoding.geocode_freeform("Duomo di Milano")
    second = geocoding.geocode_freeform("Duomo di Milano")

    assert first == second == (45.464, 9.19)
    assert fake.queries == ["Duomo di Milano"]  # second answer from the cache


def test_geocode_freeform_cache_key_normalizes_case_and_spaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uppercase, edge spaces and internal multiple spaces hit the same entry."""
    fake = _FakeGeocoder(_FakeLocation(45.464, 9.19, None))
    _patch_geocoder(monkeypatch, fake)

    geocoding.geocode_freeform("Duomo di Milano")
    geocoding.geocode_freeform("  duomo   DI\tmilano ")

    assert len(fake.queries) == 1


def test_geocode_freeform_cache_key_uses_casefold_not_lower(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``casefold`` "Straße" and "STRASSE" share the entry, ``lower`` does not."""
    fake = _FakeGeocoder(_FakeLocation(46.5, 11.35, None))
    _patch_geocoder(monkeypatch, fake)

    geocoding.geocode_freeform("Hauptstraße")
    geocoding.geocode_freeform("HAUPTSTRASSE")

    assert len(fake.queries) == 1


def test_geocode_freeform_cache_distinguishes_different_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Really different texts (digits, punctuation) do NOT collide in the cache."""
    _fast_limiter(monkeypatch)
    fake = _FakeGeocoder(_FakeLocation(41.9, 12.5, None))
    _patch_geocoder(monkeypatch, fake)

    for query in ("Via Roma 1", "Via Roma 10", "Via Roma, 1", "Via Roma"):
        geocoding.geocode_freeform(query)

    assert len(fake.queries) == 4


def test_geocode_freeform_sends_raw_query_to_nominatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The normalization applies only to the key: Nominatim gets the typed text."""
    fake = _FakeGeocoder(_FakeLocation(41.9, 12.5, None))
    _patch_geocoder(monkeypatch, fake)

    geocoding.geocode_freeform("Piazza  Navona, Roma")

    assert fake.queries == ["Piazza  Navona, Roma"]


def test_geocode_freeform_cache_disabled_queries_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With CACHE_ENABLED=false every call goes to Nominatim, the store stays empty."""
    monkeypatch.setenv("CACHE_ENABLED", "false")
    _fast_limiter(monkeypatch)
    fake = _FakeGeocoder(_FakeLocation(41.9, 12.5, None))
    _patch_geocoder(monkeypatch, fake)

    geocoding.geocode_freeform("Colosseo")
    geocoding.geocode_freeform("Colosseo")

    assert len(fake.queries) == 2
    assert len(_geo_mod._FREEFORM_CACHE) == 0  # pyright: ignore[reportPrivateUsage]


def test_geocode_freeform_does_not_cache_service_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A service error does not populate the cache: the repetition really retries."""
    _fast_limiter(monkeypatch)
    _patch_geocoder(monkeypatch, _FakeGeocoder(exc=GeocoderServiceError("boom")))
    with pytest.raises(GeocodingError):
        geocoding.geocode_freeform("Colosseo")

    ok = _FakeGeocoder(_FakeLocation(41.89, 12.49, None))
    _patch_geocoder(monkeypatch, ok)

    assert geocoding.geocode_freeform("Colosseo") == (41.89, 12.49)
    assert len(ok.queries) == 1


# --- #376: negative cache with expiry for the "no result" ---


def _fake_clock(monkeypatch: pytest.MonkeyPatch, start: float = 1000.0) -> list[float]:
    """Fake clock for the negative cache: it is advanced by mutating ``now[0]``."""
    now = [start]
    monkeypatch.setattr(_geo_mod, "_clock", lambda: now[0])
    return now


def _ttl() -> float:
    return _geo_mod._FREEFORM_NEGATIVE_TTL_SECONDS  # pyright: ignore[reportPrivateUsage]


def _negative_store() -> dict[str, float]:
    return _geo_mod._FREEFORM_NEGATIVE_CACHE  # pyright: ignore[reportPrivateUsage]


def test_negative_ttl_is_ten_minutes() -> None:
    """The expiry is short: a place just mapped on OSM becomes findable again soon."""
    assert _ttl() == 600.0


def test_negative_entry_expires_exactly_at_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boundary: an instant before it is valid, at ``now == expires_at`` it is
    expired."""
    now = _fake_clock(monkeypatch, start=1000.0 - 0.5)
    _negative_store()["luogo"] = 1000.0
    hit = _geo_mod._negative_cache_hit  # pyright: ignore[reportPrivateUsage]

    assert hit("luogo") is True
    assert "luogo" in _negative_store()

    now[0] = 1000.0
    assert hit("luogo") is False
    assert "luogo" not in _negative_store()


def test_geocode_freeform_positive_cache_wins_over_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same key in both stores: the point of the positive cache wins."""
    _fake_clock(monkeypatch)
    _geo_mod._FREEFORM_CACHE["colosseo"] = (41.89, 12.49)  # pyright: ignore[reportPrivateUsage]
    _negative_store()["colosseo"] = 1e12
    fake = _FakeGeocoder(location=None)
    _patch_geocoder(monkeypatch, fake)

    assert geocoding.geocode_freeform("Colosseo") == (41.89, 12.49)
    assert fake.queries == []


def test_negative_cache_hit_is_thread_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Many threads on expired entries continuously reinserted: no exception.

    Without a lock two threads read the same expired entry and both delete it: the
    second ``del`` raises ``KeyError``. A tiny switch interval forces thread
    switches in the middle of the sequence.
    """
    _fake_clock(monkeypatch)
    keys = ["k0", "k1", "k2", "k3"]
    errors: list[BaseException] = []
    n_threads, n_ops = 16, 2000
    barrier = threading.Barrier(n_threads)
    hit = _geo_mod._negative_cache_hit  # pyright: ignore[reportPrivateUsage]
    put = _geo_mod._cache_put  # pyright: ignore[reportPrivateUsage]

    def worker(tid: int) -> None:
        barrier.wait()
        try:
            for i in range(n_ops):
                key = keys[(tid + i) % len(keys)]
                put(_negative_store(), key, 0.0)  # already expired
                hit(key)
        except BaseException as exc:  # noqa: BLE001 - collected and verified below
            errors.append(exc)

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(old_interval)

    assert errors == []


def test_geocode_freeform_caches_no_result_within_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Within the expiry a nonexistent place does not go back to Nominatim."""
    _fast_limiter(monkeypatch)
    now = _fake_clock(monkeypatch)
    _patch_geocoder(monkeypatch, _FakeGeocoder(location=None))
    assert geocoding.geocode_freeform("Luogo Inesistente") is None

    later = _FakeGeocoder(_FakeLocation(41.89, 12.49, None))
    _patch_geocoder(monkeypatch, later)
    now[0] += _ttl() - 1

    assert geocoding.geocode_freeform("  luogo   INESISTENTE ") is None
    assert later.queries == []  # served from the negative cache
    assert len(_geo_mod._FREEFORM_CACHE) == 0  # pyright: ignore[reportPrivateUsage]


def test_geocode_freeform_negative_entry_expires_and_is_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once the entry has expired, we go back to Nominatim and the negative entry
    disappears."""
    _fast_limiter(monkeypatch)
    now = _fake_clock(monkeypatch)
    _patch_geocoder(monkeypatch, _FakeGeocoder(location=None))
    assert geocoding.geocode_freeform("Colosseo") is None
    assert "colosseo" in _negative_store()

    ok = _FakeGeocoder(_FakeLocation(41.89, 12.49, None))
    _patch_geocoder(monkeypatch, ok)
    now[0] += _ttl() + 1

    assert geocoding.geocode_freeform("Colosseo") == (41.89, 12.49)
    assert ok.queries == ["Colosseo"]
    assert "colosseo" not in _negative_store()
    assert len(_geo_mod._FREEFORM_CACHE) == 1  # pyright: ignore[reportPrivateUsage]


def test_geocode_freeform_expired_negative_entry_is_renewed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expired and still without a result: new request and new expiry from now."""
    _fast_limiter(monkeypatch)
    now = _fake_clock(monkeypatch)
    fake = _FakeGeocoder(location=None)
    _patch_geocoder(monkeypatch, fake)

    geocoding.geocode_freeform("xyzxyz")
    now[0] += _ttl() + 1
    geocoding.geocode_freeform("xyzxyz")

    assert len(fake.queries) == 2
    assert _negative_store() == {"xyzxyz": now[0] + _ttl()}


def test_geocode_freeform_negative_cache_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With CACHE_ENABLED=false the "no result" also always goes to Nominatim."""
    monkeypatch.setenv("CACHE_ENABLED", "false")
    _fast_limiter(monkeypatch)
    fake = _FakeGeocoder(location=None)
    _patch_geocoder(monkeypatch, fake)

    assert geocoding.geocode_freeform("xyzxyz") is None
    assert geocoding.geocode_freeform("xyzxyz") is None

    assert len(fake.queries) == 2
    assert _negative_store() == {}


def test_geocode_freeform_service_error_not_in_negative_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A service error does not become a cached "no result"."""
    _fast_limiter(monkeypatch)
    _patch_geocoder(monkeypatch, _FakeGeocoder(exc=GeocoderServiceError("boom")))
    with pytest.raises(GeocodingError):
        geocoding.geocode_freeform("Colosseo")
    assert _negative_store() == {}

    ok = _FakeGeocoder(_FakeLocation(41.89, 12.49, None))
    _patch_geocoder(monkeypatch, ok)

    assert geocoding.geocode_freeform("Colosseo") == (41.89, 12.49)
    assert len(ok.queries) == 1


def test_geocode_freeform_negative_cache_evicts_oldest_when_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same cap and same FIFO eviction as the other stores."""
    monkeypatch.setattr(_geo_mod, "_CACHE_MAXSIZE", 3)
    _fast_limiter(monkeypatch)
    _fake_clock(monkeypatch)
    fake = _FakeGeocoder(location=None)
    _patch_geocoder(monkeypatch, fake)

    for query in ("A", "B", "C", "D"):
        geocoding.geocode_freeform(query)

    assert list(_negative_store()) == ["b", "c", "d"]

    geocoding.geocode_freeform("A")  # evicted: goes back to Nominatim
    assert len(fake.queries) == 5


def test_geocode_freeform_negative_cache_is_separate_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The three stores neither mix nor compete for the cap."""
    monkeypatch.setattr(_geo_mod, "_CACHE_MAXSIZE", 2)
    _fast_limiter(monkeypatch)
    _fake_clock(monkeypatch)

    _patch_geocoder(monkeypatch, _FakeGeocoder(location=None))
    geocoding.geocode_freeform("Nulla 1")
    geocoding.geocode_freeform("Nulla 2")

    _patch_geocoder(
        monkeypatch,
        _FakeGeocoder(
            _FakeLocation(41.89, 12.49, ["41.88", "41.90", "12.48", "12.50"])
        ),
    )
    geocoding.geocode_freeform("Colosseo")
    geocoding.geocode_freeform("Pantheon")
    geocode_zone("Colosseo", "Roma")

    assert list(_negative_store()) == ["nulla 1", "nulla 2"]
    assert list(_geo_mod._FREEFORM_CACHE) == ["colosseo", "pantheon"]  # pyright: ignore[reportPrivateUsage]
    assert len(_geo_mod._CACHE) == 1  # pyright: ignore[reportPrivateUsage]


def test_clear_geocoding_state_empties_negative_store() -> None:
    """The reset of the autouse fixture also empties the negative cache."""
    _negative_store()["fantasma"] = 1e12

    _clear_geocoding_state()

    assert _negative_store() == {}


# --- #376: key normalized also by Unicode form (NFC) ---


@pytest.mark.parametrize(
    ("first", "second"),
    [
        # "Citta'" with precomposed accent (U+00E0) and decomposed (a + U+0300).
        ("Città", "Città"),
        ("CITTÀ", "città"),
        # Decomposed accent and "ß" together: NFC and casefold must combine.
        ("Müllerstraße", "MÜLLERSTRASSE"),
        # NFC before casefold: two canonically equivalent orders of the diacritic
        # marks. Without the initial NFC casefold turns the ypogegrammeni (U+0345) into
        # "ι" before the marks are reordered, and the two texts stay different.
        ("ᾴ", "ᾴ"),
        # NFC after casefold: casefold of U+0390 gives three code points, that of
        # "Ϊ" + U+0301 two (U+03CA + U+0301). Equivalent, but different without a
        # final NFC.
        ("Ϊ́", "ΐ"),
    ],
)
def test_freeform_key_is_canonical_caseless(first: str, second: str) -> None:
    """Key = NFC(casefold(NFC(text))): the Unicode comparison form."""
    key = _geo_mod._freeform_key  # pyright: ignore[reportPrivateUsage]
    assert key(first) == key(second)


def test_freeform_key_keeps_accents() -> None:
    """NFC does not remove the accents: "Citta" and "Città" stay different places."""
    key = _geo_mod._freeform_key  # pyright: ignore[reportPrivateUsage]
    assert key("Citta") != key("Città")


def test_geocode_freeform_nfc_variants_share_entry_raw_text_to_nominatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Composed and decomposed: same cache entry, Nominatim gets the raw text."""
    fake = _FakeGeocoder(_FakeLocation(43.77, 11.25, None))
    _patch_geocoder(monkeypatch, fake)

    geocoding.geocode_freeform("Città di Castello")
    geocoding.geocode_freeform("Città di Castello")

    assert fake.queries == ["Città di Castello"]


def test_geocode_freeform_cache_evicts_oldest_when_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same cap: beyond _CACHE_MAXSIZE the oldest entry is evicted."""
    monkeypatch.setattr(_geo_mod, "_CACHE_MAXSIZE", 3)
    _fast_limiter(monkeypatch)
    fake = _FakeGeocoder(_FakeLocation(41.9, 12.5, None))
    _patch_geocoder(monkeypatch, fake)

    for query in ("A", "B", "C", "D"):
        geocoding.geocode_freeform(query)

    cache = _geo_mod._FREEFORM_CACHE  # pyright: ignore[reportPrivateUsage]
    assert list(cache) == ["b", "c", "d"]

    geocoding.geocode_freeform("A")  # evicted: goes back to Nominatim
    assert len(fake.queries) == 5


def test_geocode_freeform_cache_is_separate_from_zone_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two caches do not mix: the freeform one neither fills nor empties the zone
    one."""
    _fast_limiter(monkeypatch)
    fake = _FakeGeocoder(
        _FakeLocation(41.89, 12.49, ["41.88", "41.90", "12.48", "12.50"])
    )
    _patch_geocoder(monkeypatch, fake)

    geocode_zone("Colosseo", "Roma")
    geocoding.geocode_freeform("Colosseo, Roma")

    assert len(fake.queries) == 2
    assert len(_geo_mod._CACHE) == 1  # pyright: ignore[reportPrivateUsage]
    assert len(_geo_mod._FREEFORM_CACHE) == 1  # pyright: ignore[reportPrivateUsage]


def test_cache_put_existing_key_on_full_store_evicts_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full store + key already present: the value is updated, no eviction."""
    monkeypatch.setattr(_geo_mod, "_CACHE_MAXSIZE", 3)
    store: dict[str, int] = {"a": 1, "b": 2, "c": 3}

    _geo_mod._cache_put(store, "b", 20)  # pyright: ignore[reportPrivateUsage]

    assert store == {"a": 1, "b": 20, "c": 3}


def test_cache_put_and_get_are_thread_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Many threads on a small store: no exception, cap never exceeded.

    Without a lock the sequence "full? evict, then insert" interleaves: two threads
    evict the same key (``KeyError``), one iterates while the other writes
    (``RuntimeError``) or both insert beyond the cap. A tiny switch interval forces
    thread switches in the middle of the sequence.
    """
    maxsize = 4
    monkeypatch.setattr(_geo_mod, "_CACHE_MAXSIZE", maxsize)
    store: dict[str, int] = {}
    errors: list[BaseException] = []
    sizes: list[int] = []
    n_threads, n_ops = 12, 1500
    barrier = threading.Barrier(n_threads)

    def worker(tid: int) -> None:
        barrier.wait()
        try:
            for i in range(n_ops):
                _geo_mod._cache_put(store, f"{tid}-{i}", i)  # pyright: ignore[reportPrivateUsage]
                _geo_mod._cache_get(store, f"{tid}-{i - 1}")  # pyright: ignore[reportPrivateUsage]
                sizes.append(len(store))
        except BaseException as exc:  # noqa: BLE001 - collected and verified below
            errors.append(exc)

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(old_interval)

    assert errors == []
    assert max(sizes) <= maxsize
    assert len(store) <= maxsize


def test_reverse_geocode_label_goes_through_the_real_nominatim_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reverse branch REALLY exercises ``_nominatim_dispatch`` (#318).

    Unlike the ``reverse_geocode_label_*``/``geocode_freeform_*`` tests above (which
    monkeypatch ``_get_rate_limited_call`` directly, bypassing
    ``_nominatim_dispatch``), here only ``_get_geolocator`` is patched -- the same
    style already used for ``geocode_zone`` -- so the real path
    ``_get_rate_limited_call() -> _nominatim_dispatch() ->
    geolocator.reverse(...)`` is exercised against a fake that records the received
    kwargs: a wrong signature (``exactly_one``/``addressdetails``/``timeout``)
    would be caught here, not just by a live call to Nominatim.
    """
    loc = _FakeLocation(41.8, 12.5, None)
    loc.raw["address"] = {"city": "Roma", "suburb": "Trastevere"}
    fake = _FakeGeocoder(loc)
    _patch_geocoder(monkeypatch, fake)

    citta, zona = geocoding.reverse_geocode_label(41.8, 12.5)

    assert citta == "Roma"
    assert zona == "Trastevere"
    assert fake.reverse_queries == [(41.8, 12.5)]
    assert fake.reverse_calls[0]["exactly_one"] is True
    assert fake.reverse_calls[0]["addressdetails"] is True
    assert fake.reverse_calls[0]["timeout"] == get_settings().geocoding_timeout_seconds


def test_geocode_and_reverse_share_the_same_rate_limiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """geocode and reverse REALLY go through the same RateLimiter (#318).

    It is not enough that ``_get_rate_limited_call() is _get_rate_limited_call()``:
    that would be guaranteed by ``@lru_cache(maxsize=1)`` for ANY zero-argument
    function, even if ``geocode_zone``/``reverse_geocode_label`` called two
    independent dispatchers/limiters (the bug this test must prevent). Here the two
    consumer paths are REALLY exercised in sequence, with a fake clock (same style
    as ``test_rate_limiter_throttles_second_call``): if the two directions had
    separate limiters, the reverse call -- the "first" for an independent limiter --
    would not have to wait. The observed sleep proves that the ``_last_call`` is
    shared across the two directions.
    """
    monkeypatch.setenv("GEOCODING_MIN_DELAY_SECONDS", "1")
    get_settings.cache_clear()
    geocoding._get_rate_limited_call.cache_clear()  # pyright: ignore[reportPrivateUsage]

    loc = _FakeLocation(41.89, 12.49, ["41.88", "41.90", "12.48", "12.50"])
    loc.raw["address"] = {"city": "Roma", "suburb": "Trastevere"}
    fake = _FakeGeocoder(loc)
    _patch_geocoder(monkeypatch, fake)

    now = [1000.0]
    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds  # time advances by as much as is slept

    monkeypatch.setattr("geopy.extra.rate_limiter.sleep", fake_sleep)
    rl = geocoding._get_rate_limited_call()  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(rl, "_clock", lambda: now[0])

    geocode_zone("Colosseo", "Roma")  # very first call: no sleep
    assert not slept

    geocoding.reverse_geocode_label(41.8, 12.5)  # right after, different direction

    assert slept and slept[0] == pytest.approx(1.0)
