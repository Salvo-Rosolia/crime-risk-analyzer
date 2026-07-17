"""Geocoding zona -> bbox via Nominatim (#15, hardening #115).

Risolve una zona all'interno di una citta' in coordinate e bounding box, usando
``geopy.geocoders.Nominatim``. Il bbox e' la tupla ``(lat_min, lon_min, lat_max,
lon_max)`` consumata a valle dal client Overpass.

Le eccezioni di dominio (:class:`ZoneNotFoundError`, :class:`GeocodingError`)
sono progettate per essere mappate dall'orchestrator a risposte HTTP esplicite
(zona non geocodificabile -> 422, servizio non raggiungibile -> 503), alimentando
lo Stato Errore del frontend. Nominatim e' un servizio HTTP sincrono: l'unica
funzione pubblica e' percio' sincrona e va invocata via ``run_in_threadpool`` da
un handler async.

Nota (decisione 3B): il PRODOTTO filtra i POI col ``bbox`` Nominatim *by design*;
il filtro poligonale reale e' riservato al gate di valutazione (eval/city_agnostic).
Il "sbavamento" del bbox ai bordi e' quindi noto e misurato li', non un difetto qui.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Protocol, TypedDict, cast

from geopy.exc import GeocoderServiceError  # pyright: ignore[reportMissingTypeStubs]
from geopy.extra.rate_limiter import (  # pyright: ignore[reportMissingTypeStubs]
    RateLimiter,
)
from geopy.geocoders import (  # pyright: ignore[reportMissingTypeStubs]
    Nominatim,
)

from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.models.geo import Bbox

__all__ = ["Bbox", "GeoResult", "GeocodingError", "ZoneNotFoundError", "geocode_zone"]

#: User-agent dedicato, richiesto dalla usage policy di Nominatim.
_USER_AGENT = (
    "crime-risk-analyzer (https://github.com/Salvo-Rosolia/crime-risk-analyzer)"
)


class _Location(Protocol):
    """Vista tipata minimale del ``geopy.location.Location`` (libreria senza stub)."""

    @property
    def latitude(self) -> float: ...

    @property
    def longitude(self) -> float: ...

    @property
    def raw(self) -> dict[str, object]: ...


class _Geocoder(Protocol):
    """Vista tipata minimale del geocoder (geopy senza stub): solo ``geocode``.

    Dichiarare qui la firma che ci serve (invece di ereditare quella non tipata
    di ``Nominatim``) mantiene la chiamata verificabile da pyright strict senza
    ``# pyright: ignore`` sparsi sugli argomenti.
    """

    def geocode(
        self,
        query: str,
        *,
        addressdetails: bool = ...,
        country_codes: str = ...,
        timeout: float = ...,
    ) -> _Location | None: ...


class GeoResult(TypedDict):
    """Esito del geocoding: punto centrale + bounding box."""

    lat: float
    lon: float
    bbox: Bbox


class GeocodingError(RuntimeError):
    """Errore del servizio di geocoding (timeout, HTTP, parsing risposta)."""


class ZoneNotFoundError(GeocodingError):
    """La zona non e' geocodificabile nella citta' indicata."""


#: Cache in-memory dei risultati di geocoding (#115), gate da Settings.cache_enabled.
#: Chiave normalizzata (strip+lower) per non duplicare varianti di case/spazi.
_CACHE: dict[tuple[str, str], GeoResult] = {}


def _cache_key(zona: str, citta: str) -> tuple[str, str]:
    return (zona.strip().lower(), citta.strip().lower())


@lru_cache(maxsize=1)
def _get_geolocator() -> Nominatim:
    """Provider cached del geocoder Nominatim (un'istanza per processo)."""
    return Nominatim(user_agent=_USER_AGENT)


def _geocode_raw(query: str) -> _Location | None:
    """Chiamata effettiva a geopy (senza stub), con timeout e country_codes.

    Ri-risolve ``_get_geolocator()`` a ogni chiamata cosi' il monkeypatch dei
    test resta onorato anche dietro il RateLimiter singleton (#115).
    """
    settings = get_settings()
    geolocator = cast("_Geocoder", _get_geolocator())
    return geolocator.geocode(
        query,
        addressdetails=False,
        country_codes=settings.geocoding_country_codes,
        timeout=settings.geocoding_timeout_seconds,
    )


@lru_cache(maxsize=1)
def _get_rate_limited_geocode() -> Callable[[str], _Location | None]:
    """RateLimiter singleton per processo attorno a :func:`_geocode_raw` (#115).

    ``min_delay_seconds`` dai setting distanzia le chiamate a Nominatim entro la
    sua usage policy (~1 req/s). ``max_retries=0`` preserva la semantica a
    chiamata singola (un errore di servizio propaga subito, niente attese di
    retry); ``swallow_exceptions=False`` fa propagare ``GeocoderServiceError``
    (altrimenti geopy lo inghiottirebbe restituendo ``None``, confondendolo con
    "zona non trovata" -> 422 invece di 503). Cached cosi' lo stato di
    throttling (``_last_call``) persiste tra le chiamate; i test lo resettano
    con ``cache_clear()``.
    """
    min_delay = get_settings().geocoding_min_delay_seconds
    return cast(
        "Callable[[str], _Location | None]",
        RateLimiter(
            _geocode_raw,
            min_delay_seconds=min_delay,
            max_retries=0,
            # geopy impone ``error_wait_seconds >= min_delay_seconds`` (assert in
            # ``RateLimiter.__init__``): con ``max_retries=0`` questo valore e'
            # inerte (nessun retry, quindi non si attende mai), ma va tenuto >=
            # min_delay per non far crollare la costruzione lazy con un
            # ``AssertionError`` (non un ``GeocoderServiceError``, quindi NON
            # mappato da :func:`geocode_zone` -> 500 anziche' 503) quando un env
            # configura ``geocoding_min_delay_seconds`` > 5s.
            error_wait_seconds=max(5.0, min_delay),
            swallow_exceptions=False,
        ),
    )


def _parse_bbox(boundingbox: object) -> Bbox:
    """Converte il ``boundingbox`` Nominatim in :data:`Bbox`.

    Nominatim espone ``raw['boundingbox'] = [lat_min, lat_max, lon_min, lon_max]``
    come stringhe; qui si riordina in ``(lat_min, lon_min, lat_max, lon_max)``.
    Solleva ``(ValueError, TypeError)`` se il formato non e' utilizzabile: il
    chiamante lo traduce in :class:`ZoneNotFoundError`.
    """
    if not isinstance(boundingbox, (list, tuple)):
        raise ValueError("boundingbox assente o malformato")
    values: list[object] = list(cast("list[object] | tuple[object, ...]", boundingbox))
    if len(values) != 4:
        raise ValueError("boundingbox di lunghezza inattesa")
    lat_min, lat_max, lon_min, lon_max = (float(cast(str, v)) for v in values)
    return Bbox(min_lat=lat_min, min_lon=lon_min, max_lat=lat_max, max_lon=lon_max)


def geocode_zone(zona: str, citta: str) -> GeoResult:
    """Geocodifica ``zona`` dentro ``citta`` -> ``{lat, lon, bbox}``.

    Solleva :class:`ZoneNotFoundError` se la zona non e' trovata o e' priva di
    bounding box utilizzabile, e :class:`GeocodingError` se il servizio Nominatim
    non e' raggiungibile.

    Con ``Settings.cache_enabled`` i soli SUCCESSI sono memorizzati per chiave
    normalizzata (#115): una zona gia' risolta non ri-interroga Nominatim. Gli
    errori sollevano prima di raggiungere lo store, quindi non vengono cacheati.
    """
    settings = get_settings()
    key = _cache_key(zona, citta)
    if settings.cache_enabled and key in _CACHE:
        return _CACHE[key]

    query = f"{zona}, {citta}"
    try:
        location = _get_rate_limited_geocode()(query)
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

    result = GeoResult(lat=location.latitude, lon=location.longitude, bbox=bbox)
    if settings.cache_enabled:
        _CACHE[key] = result
    return result
