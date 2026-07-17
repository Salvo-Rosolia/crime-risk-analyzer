"""Test del geocoding zona -> bbox (#15). Nominatim e' sempre mockato."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import pytest

import crime_risk_analyzer.geocoding as _geo_mod
from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.geocoding import (
    GeocodingError,
    ZoneNotFoundError,
    geocode_zone,
)


@pytest.fixture(autouse=True)
def _reset_geocoding_state() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Resetta lo stato di modulo condiviso prima/dopo ogni test.

    ``get_settings`` e il RateLimiter singleton (``_get_rate_limited_geocode``,
    che porta lo stato di throttling ``_last_call``) sono cacheati per processo:
    senza reset i test si contaminerebbero a vicenda (sleep residui, delay stale
    dai setting di un altro test).
    """
    get_settings.cache_clear()
    _geo_mod._get_rate_limited_geocode.cache_clear()  # pyright: ignore[reportPrivateUsage]
    yield
    get_settings.cache_clear()
    _geo_mod._get_rate_limited_geocode.cache_clear()  # pyright: ignore[reportPrivateUsage]


class _FakeLocation:
    """Stub del Location di geopy: latitude/longitude + raw['boundingbox']."""

    def __init__(self, lat: float, lon: float, boundingbox: list[str] | None) -> None:
        self.latitude = lat
        self.longitude = lon
        self.raw: dict[str, Any] = {}
        if boundingbox is not None:
            self.raw["boundingbox"] = boundingbox


class _FakeGeocoder:
    """Stub del Nominatim: ritorna una location predefinita o solleva."""

    def __init__(
        self, location: _FakeLocation | None = None, exc: Exception | None = None
    ) -> None:
        self._location = location
        self._exc = exc
        self.queries: list[str] = []
        self.calls: list[dict[str, object]] = []

    def geocode(self, query: str, **kwargs: object) -> _FakeLocation | None:
        self.queries.append(query)
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._location


def _patch_geocoder(monkeypatch: pytest.MonkeyPatch, fake: _FakeGeocoder) -> None:
    import crime_risk_analyzer.geocoding as mod

    monkeypatch.setattr(mod, "_get_geolocator", lambda: fake)


def test_geocode_zone_returns_lat_lon_bbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zona trovata -> dict con lat, lon e bbox (lat_min, lon_min, lat_max, lon_max)."""
    # boundingbox di Nominatim: [lat_min, lat_max, lon_min, lon_max] come stringhe.
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
    """La query passata a Nominatim contiene zona e citta'."""
    fake = _FakeGeocoder(_FakeLocation(45.46, 9.19, ["45.45", "45.47", "9.18", "9.20"]))
    _patch_geocoder(monkeypatch, fake)

    geocode_zone("Duomo", "Milano")

    assert "Duomo" in fake.queries[0]
    assert "Milano" in fake.queries[0]


def test_geocode_zone_not_found_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nominatim ritorna None -> ZoneNotFoundError (zona+citta' nel messaggio)."""
    _patch_geocoder(monkeypatch, _FakeGeocoder(location=None))

    with pytest.raises(ZoneNotFoundError, match="Duomo"):
        geocode_zone("Duomo", "Milano")


def test_geocode_zone_missing_bbox_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Location senza boundingbox -> ZoneNotFoundError (zona non utilizzabile)."""
    _patch_geocoder(monkeypatch, _FakeGeocoder(_FakeLocation(41.0, 12.0, None)))

    with pytest.raises(ZoneNotFoundError):
        geocode_zone("Ignota", "Roma")


def test_geocode_zone_bbox_wrong_length_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """boundingbox presente ma di lunghezza inattesa -> ZoneNotFoundError."""
    _patch_geocoder(
        monkeypatch, _FakeGeocoder(_FakeLocation(41.0, 12.0, ["41.0", "42.0"]))
    )

    with pytest.raises(ZoneNotFoundError):
        geocode_zone("Strana", "Roma")


def test_geocode_zone_service_error_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Errore del servizio (timeout/HTTP) -> GeocodingError, non eccezione grezza."""
    from geopy.exc import (  # pyright: ignore[reportMissingTypeStubs]
        GeocoderServiceError,
    )

    _patch_geocoder(monkeypatch, _FakeGeocoder(exc=GeocoderServiceError("boom")))

    with pytest.raises(GeocodingError):
        geocode_zone("Colosseo", "Roma")


def test_geocode_zone_passes_country_codes_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """country_codes e timeout arrivano DAI setting, non da valori hardcoded.

    Usa sentinelle NON-default (``fr``/``7``) cosi' il test fallisce anche se un
    domani i valori venissero cablati sul default ("it"/10.0): la sola prova che
    provengono davvero dalla configurazione.
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


def test_rate_limiter_wired_with_settings() -> None:
    """Il rate-limiter usa min_delay dai setting, max_retries=0, no swallow."""
    from geopy.extra.rate_limiter import (  # pyright: ignore[reportMissingTypeStubs]
        RateLimiter,
    )

    rl = _geo_mod._get_rate_limited_geocode()  # pyright: ignore[reportPrivateUsage]
    assert isinstance(rl, RateLimiter)
    assert rl.min_delay_seconds == get_settings().geocoding_min_delay_seconds
    assert rl.max_retries == 0
    assert rl.swallow_exceptions is False


def test_rate_limiter_builds_with_high_min_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """min_delay > 5s non deve rompere la costruzione del RateLimiter (#115)."""
    from geopy.extra.rate_limiter import (  # pyright: ignore[reportMissingTypeStubs]
        RateLimiter,
    )

    monkeypatch.setenv("GEOCODING_MIN_DELAY_SECONDS", "6")
    get_settings.cache_clear()
    _geo_mod._get_rate_limited_geocode.cache_clear()  # pyright: ignore[reportPrivateUsage]
    rl = _geo_mod._get_rate_limited_geocode()  # pyright: ignore[reportPrivateUsage]
    assert isinstance(rl, RateLimiter)
    assert rl.min_delay_seconds == 6.0
    assert rl.error_wait_seconds >= rl.min_delay_seconds


def test_rate_limiter_throttles_second_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Due chiamate ravvicinate -> applica un ritardo >= min_delay (clock finto)."""
    monkeypatch.setenv("GEOCODING_MIN_DELAY_SECONDS", "1")
    get_settings.cache_clear()
    _geo_mod._get_rate_limited_geocode.cache_clear()  # pyright: ignore[reportPrivateUsage]

    fake = _FakeGeocoder(
        _FakeLocation(41.89, 12.49, ["41.88", "41.90", "12.48", "12.50"])
    )
    _patch_geocoder(monkeypatch, fake)

    now = [1000.0]
    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds  # il tempo avanza di quanto si dorme

    monkeypatch.setattr("geopy.extra.rate_limiter.sleep", fake_sleep)
    rl = _geo_mod._get_rate_limited_geocode()  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(rl, "_clock", lambda: now[0])

    geocode_zone("Colosseo", "Roma")  # 1a chiamata: nessuno sleep
    # cache disabilitata per forzare una 2a chiamata reale
    monkeypatch.setenv("CACHE_ENABLED", "false")
    get_settings.cache_clear()
    geocode_zone("Trastevere", "Roma")  # 2a chiamata: throttle

    assert slept and slept[0] == pytest.approx(1.0)


def test_get_geolocator_builds_nominatim() -> None:
    """Il provider di default costruisce un Nominatim (nessuna chiamata di rete)."""
    from geopy.geocoders import (  # pyright: ignore[reportMissingTypeStubs]
        Nominatim,
    )

    from crime_risk_analyzer.geocoding import (
        _get_geolocator,  # pyright: ignore[reportPrivateUsage]
    )

    geolocator = _get_geolocator()
    assert isinstance(geolocator, Nominatim)


def test_get_geolocator_wires_user_agent_into_header() -> None:
    """Catena costante -> costruttore -> header: l'UA del geolocator == _USER_AGENT.

    Fail-if-removed reale sul valore *cablato*: un costruttore con valore divergente
    (o senza URL di contatto) fa fallire il test, non solo il valore della costante.
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
