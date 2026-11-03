from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from geopy.exc import GeocoderServiceError  # pyright: ignore[reportMissingTypeStubs]

from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.eval import city_agnostic as ca
from crime_risk_analyzer.eval.geometry import CityBoundary
from crime_risk_analyzer.eval.snapshots import current_canonical_config
from crime_risk_analyzer.geocoding import GeocodingError, ZoneNotFoundError
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.overpass_client import OverpassError, Poi

_BOUNDARY = CityBoundary(
    polygons=[[[(11.0, 40.0), (13.0, 40.0), (13.0, 42.0), (11.0, 42.0)]]]
)


@pytest.fixture(autouse=True)
def _reset_boundary_state() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Reset the shared module state before/after each test (#170).

    ``get_settings`` and the boundary's local RateLimiter
    (``_boundary_rate_limiter``, which carries the throttling state ``_last_call``)
    are cached per process: without a reset the ``fetch_city_boundary`` tests would
    contaminate each other (residual throttle sleeps, stale delay from the settings of
    another test). Mirror of ``_reset_geocoding_state`` for #115.
    """
    get_settings.cache_clear()
    ca._boundary_rate_limiter.cache_clear()  # pyright: ignore[reportPrivateUsage]
    yield
    get_settings.cache_clear()
    ca._boundary_rate_limiter.cache_clear()  # pyright: ignore[reportPrivateUsage]


def _poi() -> Poi:
    return {
        "id": "1",
        "name": "Banca",
        "lat": 41.0,
        "lon": 12.0,
        "osm_tags": "amenity=bank",
        "terminus_class": "Bank",
        "citta": "Roma",
    }


def _fake_boundary(citta: str) -> CityBoundary:
    return _BOUNDARY


class _FakeLocation:
    """Minimal double of ``geopy.location.Location`` for the boundary tests."""

    def __init__(self, raw: dict[str, object]) -> None:
        self.raw = raw


class _FakeGeolocator:
    """Minimal double of ``Nominatim`` for the ``fetch_city_boundary`` tests."""

    def __init__(
        self,
        result: _FakeLocation | None = None,
        *,
        raise_service_error: bool = False,
    ) -> None:
        self._result = result
        self._raise_service_error = raise_service_error
        self.calls: list[dict[str, object]] = []

    def geocode(self, query: str, **kwargs: object) -> _FakeLocation | None:
        self.calls.append({"query": query, **kwargs})
        if self._raise_service_error:
            raise GeocoderServiceError("nominatim non raggiungibile")
        return self._result


def _capture(pois: list[Poi] | None = None) -> ca.CityCapture:
    return ca.CityCapture(
        citta="Roma",
        zona="Colosseo",
        lat=41.89,
        lon=12.49,
        bbox=(41.0, 12.0, 41.5, 12.5),
        switch_ms=900,
        pois=pois or [_poi()],
        boundary=_BOUNDARY,
    )


def test_city_slug_normalises() -> None:
    assert ca.city_slug("Piazza Garibaldi") == "piazza-garibaldi"


def test_capture_path_under_snapshots(tmp_path: Path) -> None:
    p = ca.capture_path(tmp_path, "Roma")
    assert p == tmp_path / "city_agnostic" / "snapshots" / "roma.json"


def test_save_and_load_outcome_roundtrip(tmp_path: Path) -> None:
    outcome = ca.CaptureOutcome(
        status="ok", citta="Roma", zona="Colosseo", capture=_capture()
    )
    path = ca.capture_path(tmp_path, "Roma")
    ca.save_outcome(path, outcome)
    assert ca.load_outcome(path) == outcome


def test_save_outcome_writes_lf_line_endings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No translation to CRLF on Windows: the snapshots are versioned (#241).

    The check on the bytes holds only on Windows (on Linux ``write_text`` writes LF
    anyway), so it is also verified that ``newline=""`` is really passed.
    """
    calls: list[dict[str, object]] = []
    original = Path.write_text

    def _spy(self: Path, data: str, *args: Any, **kwargs: Any) -> int:
        calls.append(dict(kwargs))
        return original(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _spy)
    outcome = ca.CaptureOutcome(
        status="ok", citta="Roma", zona="Colosseo", capture=_capture()
    )
    path = ca.capture_path(tmp_path, "Roma")
    ca.save_outcome(path, outcome)
    assert calls[-1].get("newline") == ""
    assert b"\r\n" not in path.read_bytes()


async def test_capture_city_times_and_fetches_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        return {"lat": 41.89, "lon": 12.49, "bbox": Bbox(41.0, 12.0, 41.5, 12.5)}

    monkeypatch.setattr(ca, "geocode_zone", _fake_geocode)

    async def _fake_source(bbox: Bbox, citta: str) -> list[Poi]:
        return [_poi()]

    capture = await ca.capture_city(
        "Roma", "Colosseo", poi_source=_fake_source, boundary_source=_fake_boundary
    )
    assert capture.citta == "Roma"
    assert capture.bbox == (41.0, 12.0, 41.5, 12.5)
    assert capture.pois == [_poi()]
    assert capture.switch_ms >= 0
    assert capture.boundary == _BOUNDARY


def test_fetch_city_boundary_returns_boundary_for_valid_polygon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    geojson = {
        "type": "Polygon",
        "coordinates": [
            [[11.0, 40.0], [13.0, 40.0], [13.0, 42.0], [11.0, 42.0], [11.0, 40.0]]
        ],
    }
    location = _FakeLocation({"geojson": geojson})
    monkeypatch.setattr(ca, "_boundary_geolocator", lambda: _FakeGeolocator(location))

    boundary = ca.fetch_city_boundary("Roma")

    assert boundary.polygons


def test_fetch_city_boundary_passes_timeout_and_country_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """timeout and country_codes come FROM the settings, not from hardcoded values
    (#170).

    NON-default sentinels (``fr``/``7``) so the test fails even if one
    day the values were wired to the default: the only proof that they really come
    from the configuration. ``geometry='geojson'`` stays wired in (needed
    to obtain the polygon).
    """
    monkeypatch.setenv("GEOCODING_COUNTRY_CODES", "fr")
    monkeypatch.setenv("GEOCODING_TIMEOUT_SECONDS", "7")
    get_settings.cache_clear()
    ca._boundary_rate_limiter.cache_clear()  # pyright: ignore[reportPrivateUsage]

    geojson = {
        "type": "Polygon",
        "coordinates": [
            [[11.0, 40.0], [13.0, 40.0], [13.0, 42.0], [11.0, 42.0], [11.0, 40.0]]
        ],
    }
    fake = _FakeGeolocator(_FakeLocation({"geojson": geojson}))
    monkeypatch.setattr(ca, "_boundary_geolocator", lambda: fake)

    ca.fetch_city_boundary("Roma")

    assert fake.calls[0]["country_codes"] == "fr"
    assert fake.calls[0]["timeout"] == 7.0
    assert fake.calls[0]["geometry"] == "geojson"


def test_boundary_rate_limiter_wired_with_settings() -> None:
    """The local rate-limiter uses min_delay from the settings, max_retries=0, no
    swallow.

    Mirror of the #115 limiter of ``geocode_zone``, but LOCAL (not shared): the
    boundary respects the Nominatim usage policy without touching the #115 logic.
    """
    from geopy.extra.rate_limiter import (  # pyright: ignore[reportMissingTypeStubs]
        RateLimiter,
    )

    rl = ca._boundary_rate_limiter()  # pyright: ignore[reportPrivateUsage]
    assert isinstance(rl, RateLimiter)
    assert rl.min_delay_seconds == get_settings().geocoding_min_delay_seconds
    assert rl.max_retries == 0
    assert rl.swallow_exceptions is False


def test_fetch_city_boundary_raises_zone_not_found_when_location_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ca, "_boundary_geolocator", lambda: _FakeGeolocator(None))

    with pytest.raises(ZoneNotFoundError):
        ca.fetch_city_boundary("Atlantide")


def test_fetch_city_boundary_raises_geocoding_error_on_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ca, "_boundary_geolocator", lambda: _FakeGeolocator(raise_service_error=True)
    )

    with pytest.raises(GeocodingError):
        ca.fetch_city_boundary("Roma")


def test_fetch_city_boundary_raises_zone_not_found_when_geojson_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location = _FakeLocation({})
    monkeypatch.setattr(ca, "_boundary_geolocator", lambda: _FakeGeolocator(location))

    with pytest.raises(ZoneNotFoundError):
        ca.fetch_city_boundary("Roma")


def test_fetch_city_boundary_raises_zone_not_found_for_non_polygon_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    geojson = {"type": "Point", "coordinates": [12.0, 41.0]}
    location = _FakeLocation({"geojson": geojson})
    monkeypatch.setattr(ca, "_boundary_geolocator", lambda: _FakeGeolocator(location))

    with pytest.raises(ZoneNotFoundError):
        ca.fetch_city_boundary("Torino")


async def test_capture_roster_isolates_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        if citta == "Napoli":
            raise ZoneNotFoundError("zona non trovata")
        return {"lat": 41.0, "lon": 12.0, "bbox": Bbox(41.0, 12.0, 41.5, 12.5)}

    monkeypatch.setattr(ca, "geocode_zone", _fake_geocode)

    async def _fake_source(bbox: Bbox, citta: str) -> list[Poi]:
        return [_poi()]

    roster = (ca.RosterCity("Roma", "Colosseo"), ca.RosterCity("Napoli", "Garibaldi"))
    await ca.capture_roster(
        roster, tmp_path, poi_source=_fake_source, boundary_source=_fake_boundary
    )

    roma = ca.load_outcome(ca.capture_path(tmp_path, "Roma"))
    napoli = ca.load_outcome(ca.capture_path(tmp_path, "Napoli"))
    assert roma.status == "ok"
    assert roma.capture is not None
    assert napoli.status == "failed"
    assert napoli.error_type == "ZoneNotFoundError"
    assert napoli.capture is None


async def test_capture_roster_continues_after_failure_precedes_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """M3: a city that fails must not make the following one disappear."""

    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        if citta == "Napoli":
            raise ZoneNotFoundError("zona non trovata")
        return {"lat": 41.0, "lon": 12.0, "bbox": Bbox(41.0, 12.0, 41.5, 12.5)}

    monkeypatch.setattr(ca, "geocode_zone", _fake_geocode)

    async def _fake_source(bbox: Bbox, citta: str) -> list[Poi]:
        return [_poi()]

    roster = (ca.RosterCity("Napoli", "Garibaldi"), ca.RosterCity("Roma", "Colosseo"))
    await ca.capture_roster(
        roster, tmp_path, poi_source=_fake_source, boundary_source=_fake_boundary
    )

    napoli = ca.load_outcome(ca.capture_path(tmp_path, "Napoli"))
    roma = ca.load_outcome(ca.capture_path(tmp_path, "Roma"))
    assert napoli.status == "failed"
    assert roma.status == "ok"
    assert roma.capture is not None


def test_boundary_geolocator_wires_user_agent_into_header() -> None:
    """Constant -> constructor -> header chain for the boundary geolocator.

    The effective UA == _BOUNDARY_USER_AGENT (``-eval`` label preserved) and contains
    the contact URL: real fail-if-removed on the value wired into the constructor.
    """
    geolocator = ca._boundary_geolocator()  # pyright: ignore[reportPrivateUsage]
    headers = cast("dict[str, str]", geolocator.headers)  # pyright: ignore[reportUnknownMemberType]
    user_agent = headers["User-Agent"]

    assert user_agent == ca._BOUNDARY_USER_AGENT  # pyright: ignore[reportPrivateUsage]
    assert user_agent.startswith("crime-risk-analyzer-eval")
    assert "https://github.com/Salvo-Rosolia/crime-risk-analyzer" in user_agent


async def test_capture_roster_isolates_overpass_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        return {"lat": 41.0, "lon": 12.0, "bbox": Bbox(41.0, 12.0, 41.5, 12.5)}

    monkeypatch.setattr(ca, "geocode_zone", _fake_geocode)

    async def _boom(bbox: Bbox, citta: str) -> list[Poi]:
        raise OverpassError("overpass giù")

    await ca.capture_roster(
        (ca.RosterCity("Roma", "Colosseo"),),
        tmp_path,
        poi_source=_boom,
        boundary_source=_fake_boundary,
    )
    roma = ca.load_outcome(ca.capture_path(tmp_path, "Roma"))
    assert roma.status == "failed"
    assert roma.error_type == "OverpassError"


_INSTANT = datetime(2026, 10, 21, 9, 30, tzinfo=UTC)


def _fixed_clock() -> datetime:
    return _INSTANT


def test_outcome_roundtrip_preserves_provenance(tmp_path: Path) -> None:
    prov = ca.OutcomeProvenance(
        catturato_il=_INSTANT.isoformat(),
        configurazione_canonica=dict(current_canonical_config()),
    )
    outcome = ca.CaptureOutcome(
        status="ok",
        citta="Roma",
        zona="Colosseo",
        capture=_capture(),
        provenienza=prov,
    )
    path = ca.capture_path(tmp_path, "Roma")
    ca.save_outcome(path, outcome)
    loaded = ca.load_outcome(path)
    assert loaded == outcome
    assert loaded.provenienza is not None
    assert loaded.provenienza.catturato_il == "2026-10-21T09:30:00+00:00"


def test_old_outcome_without_provenance_loads_as_none(tmp_path: Path) -> None:
    outcome = ca.CaptureOutcome(
        status="failed", citta="Roma", zona="Colosseo", error_type="X", error="e"
    )
    path = ca.capture_path(tmp_path, "Roma")
    ca.save_outcome(path, outcome)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("provenienza")
    path.write_text(json.dumps(data), encoding="utf-8")
    assert ca.load_outcome(path).provenienza is None


async def test_capture_roster_writes_provenance_on_ok_and_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        if citta == "Napoli":
            raise ZoneNotFoundError("zona non trovata")
        return {"lat": 41.0, "lon": 12.0, "bbox": Bbox(41.0, 12.0, 41.5, 12.5)}

    monkeypatch.setattr(ca, "geocode_zone", _fake_geocode)

    async def _fake_source(bbox: Bbox, citta: str) -> list[Poi]:
        return [_poi()]

    roster = (ca.RosterCity("Roma", "Colosseo"), ca.RosterCity("Napoli", "Garibaldi"))
    await ca.capture_roster(
        roster,
        tmp_path,
        poi_source=_fake_source,
        boundary_source=_fake_boundary,
        clock=_fixed_clock,
    )

    for citta, status in (("Roma", "ok"), ("Napoli", "failed")):
        outcome = ca.load_outcome(ca.capture_path(tmp_path, citta))
        assert outcome.status == status
        assert outcome.provenienza is not None
        assert outcome.provenienza.catturato_il == _INSTANT.isoformat()
        assert outcome.provenienza.configurazione_canonica == current_canonical_config()
        assert "taglio_osm" not in ca.OutcomeProvenance.model_fields


@pytest.mark.integration
async def test_capture_city_live_roma() -> None:
    """Real live capture on a guaranteed city (skip default; -m integration)."""
    capture = await ca.capture_city("Roma", "Colosseo")
    assert capture.pois
    assert ca.bbox_valid(capture.bbox)
    assert capture.boundary.polygons


@pytest.mark.integration
async def test_capture_roster_live_roma(tmp_path: Path) -> None:
    """Real end-to-end driver on Rome (skip default; -m integration)."""
    await ca.capture_roster((ca.RosterCity("Roma", "Colosseo"),), tmp_path)
    outcome = ca.load_outcome(ca.capture_path(tmp_path, "Roma"))
    assert outcome.status == "ok"
    assert outcome.capture is not None
    assert outcome.capture.boundary.polygons
    assert outcome.capture.pois
