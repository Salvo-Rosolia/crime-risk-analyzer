"""Test del geocoding zona -> bbox (#15). Nominatim e' sempre mockato."""

from __future__ import annotations

from typing import Any

import pytest

from crime_risk_analyzer.geocoding import (
    GeocodingError,
    ZoneNotFoundError,
    geocode_zone,
)


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

    def geocode(self, query: str, **_: object) -> _FakeLocation | None:
        self.queries.append(query)
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
