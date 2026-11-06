"""Geocoding zone -> bbox via Nominatim (#15, hardening #115).

Resolves a zone inside a city into coordinates and bounding box, using
``geopy.geocoders.Nominatim``. The bbox is the tuple ``(lat_min, lon_min, lat_max,
lon_max)`` consumed downstream by the Overpass client.

The domain exceptions (:class:`ZoneNotFoundError`, :class:`GeocodingError`)
are designed to be mapped by the orchestrator to explicit HTTP responses
(zone not geocodable -> 422, service unreachable -> 503), feeding the frontend's
Error State. Nominatim is a synchronous HTTP service: the public functions
(:func:`geocode_zone`, :func:`geocode_freeform`,
:func:`reverse_geocode_label`) are therefore synchronous and must be invoked via
``run_in_threadpool`` from an async handler.

Note (decision 3B): the PRODUCT filters POIs with the Nominatim ``bbox`` *by
design*; the real polygonal filter is reserved to the evaluation gate
(eval/city_agnostic). The Nominatim bbox remains the base, but with a guaranteed
minimum size (#204, :func:`_enforce_min_bbox`): without a floor, a zone that
resolves to a point landmark (bbox ~150 m) would return 0 POIs from Overpass and
``/analyze`` an empty 200. The "bleed" of the bbox at the edges thus remains known
and measured in the eval gate, not a defect here.
"""

from __future__ import annotations

import threading
import time
import unicodedata
from collections.abc import Callable
from functools import lru_cache
from typing import Protocol, TypedDict, TypeVar, cast

from geopy.exc import GeocoderServiceError  # pyright: ignore[reportMissingTypeStubs]
from geopy.extra.rate_limiter import (  # pyright: ignore[reportMissingTypeStubs]
    RateLimiter,
)
from geopy.geocoders import (  # pyright: ignore[reportMissingTypeStubs]
    Nominatim,
)

from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.models.geo import Bbox, bbox_side_m

__all__ = [
    "Bbox",
    "GeoResult",
    "GeocodingError",
    "ZoneNotFoundError",
    "AreaTooLargeError",
    "geocode_zone",
    "check_area_size",
    "geocode_freeform",
    "reverse_geocode_label",
]

#: Dedicated user-agent, required by Nominatim's usage policy.
_USER_AGENT = (
    "crime-risk-analyzer (https://github.com/Salvo-Rosolia/crime-risk-analyzer)"
)


class _Location(Protocol):
    """Minimal typed view of ``geopy.location.Location`` (library without stubs)."""

    @property
    def latitude(self) -> float: ...

    @property
    def longitude(self) -> float: ...

    @property
    def raw(self) -> dict[str, object]: ...


class _Geocoder(Protocol):
    """Minimal typed view of the geocoder (geopy has no stubs).

    Declaring here the signatures we need (instead of inheriting the untyped one
    of ``Nominatim``) keeps the call verifiable by pyright strict without
    scattered ``# pyright: ignore`` on the arguments. ``reverse`` is added here
    (#318) because it goes through the same dispatcher as ``geocode``.
    """

    def geocode(
        self,
        query: str,
        *,
        addressdetails: bool = ...,
        country_codes: str = ...,
        timeout: float = ...,
    ) -> _Location | None: ...

    def reverse(
        self,
        query: tuple[float, float],
        *,
        exactly_one: bool = ...,
        addressdetails: bool = ...,
        timeout: float = ...,
    ) -> _Location | None: ...


class GeoResult(TypedDict):
    """Geocoding outcome: central point + bounding box."""

    lat: float
    lon: float
    bbox: Bbox


class GeocodingError(RuntimeError):
    """Geocoding service error (timeout, HTTP, response parsing)."""


class ZoneNotFoundError(GeocodingError):
    """The zone is not geocodable in the given city."""


class AreaTooLargeError(ZoneNotFoundError):
    """The geocoded area exceeds the size cap (#497): e.g. a whole city.

    Subclass of :class:`ZoneNotFoundError` so the cold-cache rebuild paths that
    already catch it keep working; the central handler gives it its own code.
    """


#: In-memory cache of geocoding results (#115), gated by Settings.cache_enabled.
#: Normalised key (strip+lower) so case/whitespace variants are not duplicated.
_CACHE: dict[tuple[str, str], GeoResult] = {}

#: Cache cap (#170): with a user-controlled ``zona`` in the key, an unbounded dict
#: would grow without limit in a long-lived process. When full, the oldest entry
#: is evicted (FIFO: ``dict`` in 3.7+ preserves insertion order). 1024 keys
#: (zona, citta) are ample for real use and keep memory negligible. The cap
#: applies to EACH of the stores (``_CACHE``, ``_FREEFORM_CACHE`` since #344,
#: ``_FREEFORM_NEGATIVE_CACHE`` since #376): in total up to 3 x 1024 entries.
_CACHE_MAXSIZE = 1024

#: Cache of the points of :func:`geocode_freeform` (#344, "go to a place" box):
#: same gate (``cache_enabled``), same cap and same FIFO eviction as
#: ``_CACHE``, but a separate store because key and value are different. The value
#: is an immutable tuple: no defensive copy.
_FREEFORM_CACHE: dict[str, tuple[float, float]] = {}

#: Negative cache of :func:`geocode_freeform` (#376): the "no result" outcomes.
#: Without it, a non-existent place goes back to Nominatim on every submit and
#: queues on the rate limiter shared with ``/analyze``. Same gate, cap, FIFO
#: eviction and lock as the other stores; the value is the expiry instant on
#: :data:`_clock`. Service errors never enter it.
_FREEFORM_NEGATIVE_CACHE: dict[str, float] = {}

#: Lifetime (seconds) of a negative entry. Short, unlike successes which stay for
#: the whole life of the process: a place just added to OSM, or a "no result" due
#: to a transient Nominatim problem, becomes findable again within ten minutes
#: without restarting the backend.
_FREEFORM_NEGATIVE_TTL_SECONDS = 600.0

#: Expiry clock: monotonic, hence immune to system time changes. Module variable
#: so the tests replace it.
_clock: Callable[[], float] = time.monotonic

#: The public functions run in ``run_in_threadpool``, hence on several threads at
#: once. The single operations on the ``dict`` are atomic, the sequence
#: "full? evict the oldest, then insert" is not: two threads could evict the
#: same key (``KeyError``) or iterate while the other writes.
#: The lock covers only the operations on the stores, never the call to Nominatim.
_CACHE_LOCK = threading.Lock()

_K = TypeVar("_K")
_V = TypeVar("_V")


def _cache_get(store: dict[_K, _V], key: _K) -> _V | None:
    with _CACHE_LOCK:
        return store.get(key)


def _cache_put(store: dict[_K, _V], key: _K, value: _V) -> None:
    """Inserts with cap ``_CACHE_MAXSIZE`` and FIFO eviction (#170).

    When full, the oldest entry is removed (``dict`` preserves insertion
    order); updating a key already present does not grow the store, so it evicts
    nothing.
    """
    with _CACHE_LOCK:
        if len(store) >= _CACHE_MAXSIZE and key not in store:
            store.pop(next(iter(store)))
        store[key] = value


def _negative_cache_hit(key: str) -> bool:
    """True if ``key`` has a not yet expired "no result" (#376).

    An expired entry is deleted here, under the same lock: it no longer takes
    room in the store and a new "no result" reinserts it at the tail.
    """
    with _CACHE_LOCK:
        expires_at = _FREEFORM_NEGATIVE_CACHE.get(key)
        if expires_at is None:
            return False
        if _clock() < expires_at:
            return True
        del _FREEFORM_NEGATIVE_CACHE[key]
        return False


def _cache_key(zona: str, citta: str) -> tuple[str, str]:
    return (zona.strip().lower(), citta.strip().lower())


def _freeform_key(query: str) -> str:
    """Key of :data:`_FREEFORM_CACHE` and :data:`_FREEFORM_NEGATIVE_CACHE`.

    It removes only the differences that Nominatim ignores anyway: capitals and
    equivalent variants in Unicode's caseless comparison (``casefold``,
    wider than ``lower``: also "ß" -> "ss" and ligatures like "ﬁ" -> "fi"),
    spaces (at the edges, multiple or inner tabs reduced to one, #344) and
    Unicode form (#376): "Città" with the precomposed or decomposed accent is the
    same text.

    The Unicode form is fixed with NFC both before and after ``casefold``: the
    key respects canonical equivalence and, for realistic texts, coincides
    with the canonical caseless comparison form of Unicode (NFD before and
    after ``casefold``). It differs only on pathological Greek sequences with
    double accent and ypogegrammeni. Before: ``casefold`` does not respect
    canonical equivalence, and two equivalent orders of the diacritic marks
    would give different keys. After: ``casefold`` can produce non-NFC text
    (U+0390 becomes three code points).
    NFC, not NFKC: compatibility variants (superscripts, fractions) remain
    different text. Digits and punctuation remain: "Via Roma 1" and
    "Via Roma, 10" are different places.
    """
    collapsed = " ".join(query.split())
    folded = unicodedata.normalize("NFC", collapsed).casefold()
    return unicodedata.normalize("NFC", folded)


def _copy_result(result: GeoResult) -> GeoResult:
    """Defensive shallow copy of a :class:`GeoResult` (#170).

    Returning the cache object by reference would expose the shared entry: a
    consumer that mutated the dict would poison the cache. ``bbox``
    is an immutable :class:`Bbox`, so the shallow copy is enough.
    """
    return cast("GeoResult", dict(result))


@lru_cache(maxsize=1)
def _get_geolocator() -> Nominatim:
    """Cached provider of the Nominatim geocoder (one instance per process)."""
    return Nominatim(user_agent=_USER_AGENT)


def _nominatim_dispatch(op: str, arg: str | tuple[float, float]) -> _Location | None:
    """Actual call to geopy (without stubs): dispatches on ``geocode``/``reverse``.

    Re-resolves ``_get_geolocator()`` at every call so the tests' monkeypatch
    is still honoured even behind the singleton RateLimiter (#115). A single
    dispatcher for the two directions (#318): it is what lets
    :func:`_get_rate_limited_call` wrap them in one shared RateLimiter,
    instead of one per direction.
    """
    settings = get_settings()
    geolocator = cast("_Geocoder", _get_geolocator())
    if op == "geocode":
        return geolocator.geocode(
            cast(str, arg),
            addressdetails=False,
            country_codes=settings.geocoding_country_codes,
            timeout=settings.geocoding_timeout_seconds,
        )
    lat, lon = cast("tuple[float, float]", arg)
    return geolocator.reverse(
        (lat, lon),
        exactly_one=True,
        addressdetails=True,
        timeout=settings.geocoding_timeout_seconds,
    )


@lru_cache(maxsize=1)
def _get_rate_limited_call() -> Callable[
    [str, str | tuple[float, float]], _Location | None
]:
    """Per-process singleton RateLimiter, shared by geocode AND reverse (#318).

    Nominatim's usage policy is "1 request/second, absolute, on the whole
    service" -- not "1 req/s per direction". Before this unification
    (it was ``_get_rate_limited_geocode``, forward only) a reverse geocode
    would have had its own independent RateLimiter: the combined traffic
    of the two directions could have exceeded the policy even if each one,
    in isolation, respected it. By wrapping :func:`_nominatim_dispatch` (which
    itself dispatches on ``geocode``/``reverse``) in a single RateLimiter, every
    call -- whatever the direction -- goes through the same throttling.

    ``min_delay_seconds`` from the settings spaces calls within that
    policy. ``max_retries=0`` preserves the single-call semantics (a
    service error propagates immediately, no retry waits);
    ``swallow_exceptions=False`` makes ``GeocoderServiceError`` propagate
    (otherwise geopy would swallow it returning ``None``, confusing it with
    "zone not found" -> 422 instead of 503). Cached so the throttling state
    (``_last_call``) persists between calls; the tests reset it with
    ``cache_clear()``.
    """
    min_delay = get_settings().geocoding_min_delay_seconds
    return cast(
        "Callable[[str, str | tuple[float, float]], _Location | None]",
        RateLimiter(
            _nominatim_dispatch,
            min_delay_seconds=min_delay,
            max_retries=0,
            # geopy requires ``error_wait_seconds >= min_delay_seconds`` (assert in
            # ``RateLimiter.__init__``): with ``max_retries=0`` this value is
            # inert (no retry, so it never waits), but it must be kept >=
            # min_delay so the lazy construction does not collapse with an
            # ``AssertionError`` (not a ``GeocoderServiceError``, hence NOT
            # mapped by :func:`geocode_zone` -> 500 instead of 503) when an env
            # configures ``geocoding_min_delay_seconds`` > 5s.
            error_wait_seconds=max(5.0, min_delay),
            swallow_exceptions=False,
        ),
    )


def _parse_bbox(boundingbox: object) -> Bbox:
    """Converts the Nominatim ``boundingbox`` into :data:`Bbox`.

    Nominatim exposes ``raw['boundingbox'] = [lat_min, lat_max, lon_min, lon_max]``
    as strings; here it is reordered into ``(lat_min, lon_min, lat_max, lon_max)``.
    Raises ``(ValueError, TypeError)`` if the format is unusable: the
    caller translates it into :class:`ZoneNotFoundError`.
    """
    if not isinstance(boundingbox, (list, tuple)):
        raise ValueError("boundingbox missing or malformed")
    values: list[object] = list(cast("list[object] | tuple[object, ...]", boundingbox))
    if len(values) != 4:
        raise ValueError("boundingbox of unexpected length")
    lat_min, lat_max, lon_min, lon_max = (float(cast(str, v)) for v in values)
    return Bbox(min_lat=lat_min, min_lon=lon_min, max_lat=lat_max, max_lon=lon_max)


def _enforce_min_bbox(bbox: Bbox, half_span: float) -> Bbox:
    """Imposes a minimum size on ``bbox`` by expanding it symmetrically (#204).

    When a zone resolves to a point landmark, Nominatim returns a tiny bbox
    (as big as the building) in which Overpass finds no POI.
    Here we guarantee that every side measures at least ``2 * half_span`` degrees,
    expanding around the midpoint of the original bbox.

    It is an "expand-only" operation: a bbox already larger than the threshold
    stays unchanged (the ``min``/``max`` keep the original extremes) and an axis
    already wide is not touched while the other, narrow one is extended. The
    midpoint is preserved on both axes.
    """
    lat_mid = (bbox.min_lat + bbox.max_lat) / 2
    lon_mid = (bbox.min_lon + bbox.max_lon) / 2
    return Bbox(
        min_lat=min(bbox.min_lat, lat_mid - half_span),
        min_lon=min(bbox.min_lon, lon_mid - half_span),
        max_lat=max(bbox.max_lat, lat_mid + half_span),
        max_lon=max(bbox.max_lon, lon_mid + half_span),
    )


def check_area_size(result: GeoResult, label: str) -> GeoResult:
    """Rejects a geocoded area larger than the circle cap (#497) and returns it.

    The text mode is held to the same area cap as the drawn circle: no side above
    the diameter of the largest allowed circle. It is applied by the callers on
    the product paths, not inside :func:`geocode_zone`, so the evaluation harness
    (fixed zones, reproducibility) keeps calling it unchanged.

    Raises:
        AreaTooLargeError: a side of the bbox exceeds ``2 * search_radius_max_m``.
    """
    max_side_m = 2 * get_settings().search_radius_max_m
    height, width = bbox_side_m(result["bbox"])
    if max(height, width) > max_side_m:
        raise AreaTooLargeError(
            f"Area troppo estesa per {label!r}: massimo {max_side_m / 1000:.0f} km "
            "per lato. Indica una zona o un quartiere piu' piccolo."
        )
    return result


def geocode_zone(zona: str, citta: str) -> GeoResult:
    """Geocodes ``zona`` inside ``citta`` -> ``{lat, lon, bbox}``.

    Composes the query as "zona, citta". It is the text -> area path of both
    two-field consumers: the product's city + zone mode (alternative to the
    drawn circle, :func:`~crime_risk_analyzer.area_search.resolve_zone`) and
    the evaluation harness (``eval/``), which works on fixed pairs for
    reproducibility.

    Raises :class:`ZoneNotFoundError` if the zone is not found or has no usable
    bounding box, and :class:`GeocodingError` if the Nominatim service is
    unreachable.

    With ``Settings.cache_enabled`` only SUCCESSES are stored by normalised key
    (#115): an already resolved zone does not query Nominatim again. Errors
    raise before reaching the store, so they are not cached.
    """
    settings = get_settings()
    key = _cache_key(zona, citta)
    if settings.cache_enabled:
        cached = _cache_get(_CACHE, key)
        if cached is not None:
            return _copy_result(cached)

    query = f"{zona}, {citta}"
    try:
        location = _get_rate_limited_call()("geocode", query)
    except GeocoderServiceError as exc:
        raise GeocodingError(
            f"Servizio di geocoding non raggiungibile per {query!r}"
        ) from exc

    if location is None:
        raise ZoneNotFoundError(f"Zona non trovata: {zona!r} in {citta!r}")

    raw = location.raw
    try:
        bbox = _parse_bbox(raw.get("boundingbox"))
    except (ValueError, TypeError) as exc:
        raise ZoneNotFoundError(
            f"Zona priva di bounding box: {zona!r} in {citta!r}"
        ) from exc

    # Minimum floor (#204): guarantees a usable Overpass search area even when
    # the zone resolves to a point landmark (Nominatim bbox ~150 m).
    # Applied BEFORE building the GeoResult (and hence before populating the
    # cache); lat/lon remain those of Nominatim.
    bbox = _enforce_min_bbox(bbox, settings.geocoding_min_bbox_half_span_deg)

    result = GeoResult(lat=location.latitude, lon=location.longitude, bbox=bbox)
    if settings.cache_enabled:
        _cache_put(_CACHE, key, result)
    # Defensive copy on the miss too (#170): the entry just stored is the same
    # instance, so returning ``result`` by reference would expose it.
    return _copy_result(result)


def reverse_geocode_label(lat: float, lon: float) -> tuple[str, str]:
    """Best-effort (citta, zona) label for a point, via reverse geocode (#318).

    Never raises: a Nominatim failure (service error, no result, missing
    address) returns a fallback on formatted coordinates, because the label is
    cosmetic (narrative/UI) and must never block the analysis (D9, design doc).
    """
    fallback = (f"area {lat:.4f},{lon:.4f}", "zona non identificata")
    try:
        location = _get_rate_limited_call()("reverse", (lat, lon))
    except GeocoderServiceError:
        return fallback
    if location is None:
        return fallback
    address_raw = location.raw.get("address")
    if not isinstance(address_raw, dict):
        return fallback
    # ``isinstance(x, dict)`` narrows only to ``dict[Unknown, Unknown]`` (no
    # check on the type args): the explicit cast keeps ``citta``/``zona``
    # verifiable by pyright strict, as in _parse_bbox above.
    address = cast("dict[str, object]", address_raw)
    citta = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or fallback[0]
    )
    zona = (
        address.get("suburb")
        or address.get("neighbourhood")
        or address.get("quarter")
        or fallback[1]
    )
    return (str(citta), str(zona))


def geocode_freeform(query: str) -> tuple[float, float] | None:
    """Forward geocode of a free query (#318, "go to a place" box).

    Unlike :func:`geocode_zone`: no "zona, citta" concatenation, no bbox floor
    (here only a point is needed to centre the map).

    With ``Settings.cache_enabled`` successes are stored by normalised key
    (#344): repeating the same place does not requeue a request on the rate
    limiter shared with ``/analyze``. Nominatim still receives the text as
    typed. The "no result" is also stored (#376), but in a separate store and
    only for :data:`_FREEFORM_NEGATIVE_TTL_SECONDS`: a repeated non-existent
    place does not go back to Nominatim, one that has just appeared on OSM is
    found again after expiry. Service errors are never stored (they raise
    first). Two concurrent misses on the same key both query Nominatim (no
    deduplication of in-flight requests).
    """
    settings = get_settings()
    key = _freeform_key(query)
    if settings.cache_enabled:
        cached = _cache_get(_FREEFORM_CACHE, key)
        if cached is not None:
            return cached
        if _negative_cache_hit(key):
            return None

    try:
        location = _get_rate_limited_call()("geocode", query)
    except GeocoderServiceError as exc:
        raise GeocodingError(
            f"Servizio di geocoding non raggiungibile per {query!r}"
        ) from exc
    if location is None:
        if settings.cache_enabled:
            _cache_put(
                _FREEFORM_NEGATIVE_CACHE,
                key,
                _clock() + _FREEFORM_NEGATIVE_TTL_SECONDS,
            )
        return None
    point = (location.latitude, location.longitude)
    if settings.cache_enabled:
        _cache_put(_FREEFORM_CACHE, key, point)
    return point
