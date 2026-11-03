"""Tests for the POST /analyze endpoint (#18)."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from crime_risk_analyzer import area_search, zone_context_cache
from crime_risk_analyzer.analyze_narrative import run_analysis_fast
from crime_risk_analyzer.config import Settings, get_settings
from crime_risk_analyzer.context_fingerprint import fingerprint
from crime_risk_analyzer.geocoding import GeoResult, ZoneNotFoundError
from crime_risk_analyzer.llm.client import LLMResponse, get_llm_client
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.orchestrator import run_analysis, run_baseline
from crime_risk_analyzer.overpass_client import OverpassError, Poi
from crime_risk_analyzer.rag import retrieval
from crime_risk_analyzer.rag.grounding import GroundedContext
from crime_risk_analyzer.rag.retrieval import RetrievalContext
from crime_risk_analyzer.sources.context import current_executor

_BANK = PoiRiskProfile(
    ontology_class="Bank",
    hazards=["Bank_robbery"],
    sparql_paths=["Bank → havingHazard → Bank_robbery"],
)


class _FakeProfiler:
    def profile(self, ontology_class: str) -> PoiRiskProfile:
        profiles = {"Bank": _BANK}
        return profiles.get(
            ontology_class, PoiRiskProfile(ontology_class=ontology_class)
        )


class _FakeLLMClient:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        return LLMResponse(
            text="Analisi: rischio rapina.",
            llm_used="claude-sonnet-4-6",
            tokens_input=5,
            tokens_output=8,
            cache_hit=False,
            temperature=0.2,
            seed=42,
            prompt_hash="h",
        )


class _RecordingLLMClient:
    """Spy: records the ``user_content`` the endpoint sends to the model."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        self.calls.append((system_prompt, user_content))
        return LLMResponse(
            text="Analisi: rischio rapina.",
            llm_used="claude-sonnet-4-6",
            tokens_input=5,
            tokens_output=8,
            cache_hit=False,
            temperature=0.2,
            seed=42,
            prompt_hash="h",
        )


def _pois(citta: str) -> list[Poi]:
    return [
        {
            "id": "1",
            "name": "Banca A",
            "lat": 41.89,
            "lon": 12.49,
            "osm_tags": "amenity=bank",
            "ontology_class": "Bank",
            "citta": citta,
        },
        {
            "id": "2",
            "name": "Bar Roma",
            "lat": 41.90,
            "lon": 12.50,
            "osm_tags": "amenity=bar",
            "ontology_class": "GenericUrbanPOI",
            "citta": citta,
        },
    ]


def _fake_reverse_geocode(lat: float, lon: float) -> tuple[str, str]:
    return ("Roma", "Trastevere")


def _patch_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch only the I/O that the circle path (#318) really goes through.

    With the circle ``geocode_zone`` is not called (it is only called in the
    citta + zona mode, see ``_patch_zone_io``): ``resolve_circle`` always passes
    its own ``geo_source``. The citta/zona label comes from
    ``area_search.reverse_geocode_label`` (reverse geocode of the center); the
    bbox comes from ``bbox_from_circle`` (pure, no I/O) -- so only the label
    has to be simulated here.
    """
    monkeypatch.setattr(area_search, "reverse_geocode_label", _fake_reverse_geocode)

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois(citta)

    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)


def _client(llm: object = None, *, settings: Settings | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[current_executor] = lambda: _FakeProfiler()
    app.dependency_overrides[get_llm_client] = lambda: llm or _FakeLLMClient()
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app, raise_server_exceptions=False)


def test_analyze_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """#292: the route answers in phase 1 -- structured data, ``narrativa`` absent.

    ``narrativa is None`` is not a fallback (``fallback`` stays ``False``): it
    tells the client that the text is on its way from ``POST /analyze/narrativa``.
    The distinction is the contract on which the frontend decides whether to show
    the narrativa skeleton or the "LLM down" message.
    """
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["citta"] == "Roma"
    assert body["zona_normalizzata"] == "Trastevere"
    assert body["fallback"] is False
    assert body["narrativa"] is None
    assert [p["confidence"] for p in body["poi"]] == ["verificato", None]


def test_analyze_contesto_hash_changes_with_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#416: the same input from sessions with different sources does not share the
    fingerprint (and therefore cannot reuse another set's narrativa)."""
    import dataclasses

    from crime_risk_analyzer.sources import routes as sources_routes
    from crime_risk_analyzer.sources.context import default_set
    from crime_risk_analyzer.sources.session import SessionStore

    _patch_io(monkeypatch)
    zone_context_cache.clear()
    store = SessionStore(ttl_seconds=100, max_sessions=2)
    sid = "sessione-di-prova-AAAA"
    store.activate(
        sid, dataclasses.replace(default_set(), id="custom-x", kind="custom"), []
    )
    client = _client()
    cast(FastAPI, client.app).dependency_overrides[sources_routes.get_sessions] = (
        lambda: store
    )
    body = {"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0}
    default = client.post("/analyze", json=body).json()["contesto_hash"]
    with_set = client.post("/analyze", json=body, headers={"X-Session-Id": sid}).json()[
        "contesto_hash"
    ]
    assert default != with_set


@pytest.mark.parametrize("enabled", [True, False], ids=["istat-acceso", "istat-spento"])
def test_analyze_route_passes_the_switch(
    enabled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#346: without forwarding ``istat_context_enabled=settings.istat_context_enabled``
    in ``main.py``, ``poi[].istat`` would never reach the client in production,
    whatever the value of ``Settings.istat_context_enabled``."""
    from crime_risk_analyzer import analyze_narrative
    from crime_risk_analyzer.rag.grounding import ground as real_ground
    from tests.istat._factories import BANKROB, istat_poi

    _patch_io(monkeypatch)
    istat_payload = istat_poi(BANKROB)

    def _ground_with_istat(ctx: RetrievalContext) -> GroundedContext:
        grounded = real_ground(ctx)
        for vr in grounded["validated_risks"]:
            vr["istat"] = istat_payload
        return grounded

    monkeypatch.setattr(analyze_narrative, "ground", _ground_with_istat)
    resp = cast(
        httpx.Response,
        _client(settings=Settings(istat_context_enabled=enabled)).post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 200
    assert (resp.json()["poi"][0]["istat"] is not None) is enabled


def test_analyze_response_is_gzip_compressed_when_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#346 (O10): the ``IstatPoi`` repeated for every POI raises the weight of the
    response by 50-55%; GZip compression compensates for it. ``TestClient``/httpx
    decompresses the body by itself: here we only check the transport header."""
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
            headers={"Accept-Encoding": "gzip"},
        ),
    )
    assert resp.status_code == 200
    assert resp.headers["content-encoding"] == "gzip"


def test_analyze_zone_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """An error while resolving the label (reverse geocode) propagates as a 422.

    The real ``reverse_geocode_label`` never raises (cosmetic fallback, #318):
    this only checks that the central ``ZoneNotFoundError`` handler stays wired
    even behind the new ``resolve_circle``.
    """

    def _raise(lat: float, lon: float) -> tuple[str, str]:
        raise ZoneNotFoundError("zona ignota")

    monkeypatch.setattr(area_search, "reverse_geocode_label", _raise)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["errore"] == "zona_non_geocodificabile"


def test_analyze_reports_reverse_geocoded_city(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#318: the ``citta`` in the response is the one from the reverse geocode of the
    center.

    There is no allowlist anymore (already removed by #191) nor a ``citta`` field
    in the request: it checks that ``center.lat``/``center.lon`` reach
    ``reverse_geocode_label`` and that the returned label ends up in the response.
    """
    seen: list[tuple[float, float]] = []

    def _recording_reverse(lat: float, lon: float) -> tuple[str, str]:
        seen.append((lat, lon))
        return ("Acireale", "Centro")

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois(citta)

    monkeypatch.setattr(area_search, "reverse_geocode_label", _recording_reverse)
    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 37.61, "lon": 15.16}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["citta"] == "Acireale"
    assert seen == [(37.61, 15.16)]


def test_analyze_rejects_out_of_range_radius(monkeypatch: pytest.MonkeyPatch) -> None:
    """radius_m outside [search_radius_min_m, search_radius_max_m] -> 422 (#318).

    Pydantic validation before any I/O, like the old ``max_length=100`` limit on
    ``citta`` (removed together with the field): a malformed body must reach
    neither the reverse geocode nor Overpass.
    """
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 50_000.0},
        ),
    )
    assert resp.status_code == 422


def _pois_by_radius(citta: str) -> list[Poi]:
    """One POI at the exact center of the request + one more than a km away (#318)."""
    return [
        {
            "id": "vicino",
            "name": "Banca A",
            "lat": 41.89,
            "lon": 12.49,
            "osm_tags": "amenity=bank",
            "ontology_class": "Bank",
            "citta": citta,
        },
        {
            "id": "lontano",
            "name": "Bar Roma",
            "lat": 41.90,
            "lon": 12.50,
            "osm_tags": "amenity=bar",
            "ontology_class": "GenericUrbanPOI",
            "citta": citta,
        },
    ]


def test_analyze_radius_m_really_reaches_the_geospatial_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#318: proves at the HTTP boundary that ``radius_m`` filters the POIs, not just
    that it is validated by the ``field_validator``.

    Without ``radius_m=request.radius_m`` wired from ``main.py`` into
    ``run_analysis_fast``, the whole suite would pass anyway (nothing, at route
    level, proves that the radius really reaches the pipeline). The center of the
    request coincides with ``Banca A`` (distance ~0 m) while ``Bar Roma`` is over
    a km away: a 150 m radius (the allowed minimum) must exclude the latter from
    the response.
    """
    monkeypatch.setattr(area_search, "reverse_geocode_label", _fake_reverse_geocode)

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois_by_radius(citta)

    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 150.0},
        ),
    )
    assert resp.status_code == 200
    assert [p["id"] for p in resp.json()["poi"]] == ["vicino"]


def test_analyze_overpass_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(area_search, "reverse_geocode_label", _fake_reverse_geocode)

    async def _raise_fetch(*args: object, **kwargs: object) -> list[Poi]:
        raise OverpassError("overpass giu'")

    monkeypatch.setattr(retrieval, "fetch_pois", _raise_fetch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["errore"] == "overpass_non_disponibile"


def test_analyze_never_calls_the_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """#292: phase 1 does not spend a model call -- that is its whole point.

    Before, the route blocked on the LLM and the structured data arrived only
    after the narrativa. If a refactor put ``run_analysis`` back on the route, the
    spy would record a call and this test would turn red: it is the guard of the
    perceived latency, not an implementation detail.

    The ``risk_models`` stay in the phase 1 response (they come from the
    grounding, not from the LLM): the frontend attaches the risks to the point by
    ``poi_id``, so the key name is verified on the wire.
    """
    _patch_io(monkeypatch)
    llm = _RecordingLLMClient()
    resp = cast(
        httpx.Response,
        _client(llm=llm).post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 200
    assert llm.calls == []
    body = resp.json()
    assert body["narrativa"] is None
    assert body["fallback"] is False
    assert body["risk_models"][0]["poi"] == "Banca A"
    assert body["risk_models"][0]["poi_id"] == "1"


async def test_run_analysis_threads_geo_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#169: the geo_source passed to run_analysis reaches retrieve (no geocode)."""

    def _boom_geocode(zona: str, citta: str) -> GeoResult:
        raise AssertionError("geocode_zone non deve essere chiamato con geo_source")

    monkeypatch.setattr(retrieval, "geocode_zone", _boom_geocode)
    seen: list[tuple[str, str]] = []

    async def _geo(citta: str, zona: str) -> GeoResult:
        seen.append((citta, zona))
        return GeoResult(lat=0.0, lon=0.0, bbox=Bbox(0.0, 0.0, 0.0, 0.0))

    async def _pois(bbox: Bbox, citta: str) -> list[Poi]:
        return []

    await run_analysis(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_pois,
        geo_source=_geo,
    )
    assert seen == [("Roma", "Colosseo")]


async def test_analyze_populates_the_zone_context_cache() -> None:
    """#197: the context computed by /analyze stays available to /analyze/poi.

    The product invariant is the same as before, only who implements it changes:
    after the split (#292) it is phase 1 of the route (``run_analysis_fast``) that
    stores the context, not ``run_analysis`` -- which no route calls anymore.
    Verified on the content, not just on the presence: the click on a POI reads
    the zone, the points and the validated risks from here, so that is what must
    stay intact.
    """

    async def _geo(citta: str, zona: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    async def _fetch(bbox: Bbox, citta: str) -> list[Poi]:
        return _pois(citta)

    zone_context_cache.clear()
    await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_fetch,
        geo_source=_geo,
    )
    cached = zone_context_cache.get("Roma", "Colosseo")
    assert cached is not None
    assert cached["retrieval"]["zona"] == "Colosseo"
    assert [p["name"] for p in cached["retrieval"]["pois"]] == ["Banca A", "Bar Roma"]
    assert len(cached["grounded"]["validated_risks"]) == 2


# --- #242: context fingerprint in the response ---
# ``retrieve`` passes the POI list AS IS from the source to the context
# (``pois = await source(...)``: no filter, no reordering), so the fingerprint
# of the response identifies exactly the list produced by the source and the
# comparison with ``fingerprint(_pois(...))`` is legitimate.


async def test_run_analysis_exposes_the_context_fingerprint() -> None:
    """#242: the fingerprint identifies the POI list of the response that contains it.

    It is no longer a route guard: since #292 ``run_analysis`` is the only
    EVALUATION path, and the same property on the route is verified by
    ``test_analyze_narrative`` on phase 1. It stays here because the response
    contract is single, and the two paths must keep emitting the same fingerprint
    for the same list.
    """

    async def _geo(citta: str, zona: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    async def _fetch(bbox: Bbox, citta: str) -> list[Poi]:
        return _pois(citta)

    resp = await run_analysis(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_fetch,
        geo_source=_geo,
    )
    assert resp.contesto_hash == fingerprint(_pois("Roma"))


async def test_different_fingerprint_if_the_poi_set_changes() -> None:
    """Two captures with different POIs cannot have the same fingerprint:
    it is the condition for /analyze/poi to detect the divergence (#242)."""

    async def _geo(citta: str, zona: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    async def _fetch_full(bbox: Bbox, citta: str) -> list[Poi]:
        return _pois(citta)

    async def _fetch_reduced(bbox: Bbox, citta: str) -> list[Poi]:
        return _pois(citta)[:1]

    full = await run_analysis(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_fetch_full,
        geo_source=_geo,
    )
    reduced = await run_analysis(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_fetch_reduced,
        geo_source=_geo,
    )
    assert full.contesto_hash != reduced.contesto_hash


async def test_baseline_exposes_the_context_fingerprint() -> None:
    """The pipeline without the LLM emits the fingerprint too: the response is the
    same and the frontend in Base mode must not be left without it (#242)."""

    async def _geo(citta: str, zona: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    async def _fetch(bbox: Bbox, citta: str) -> list[Poi]:
        return _pois(citta)

    resp = await run_baseline(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_fetch,
        geo_source=_geo,
    )
    assert resp.contesto_hash == fingerprint(_pois("Roma"))


async def test_baseline_fingerprint_computed_after_the_tipo_poi_filter() -> None:
    """The fingerprint identifies the RETURNED list, not the pre-filter one (#242).

    Without this test a refactor that moved ``fingerprint`` above
    ``_filter_pois_by_type`` (#119) would stay green and reintroduce the
    divergence that #242 closes: a fingerprint identifying POIs never shown.
    """

    async def _geo(citta: str, zona: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    async def _fetch(bbox: Bbox, citta: str) -> list[Poi]:
        return _pois(citta)

    resp = await run_baseline(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_fetch,
        geo_source=_geo,
        tipo_poi="Bank",
    )
    filtered_pois = [p for p in _pois("Roma") if p["ontology_class"] == "Bank"]
    assert [p.name for p in resp.poi] == [p["name"] for p in filtered_pois]
    assert resp.contesto_hash == fingerprint(filtered_pois)
    assert resp.contesto_hash != fingerprint(_pois("Roma"))


# --- The two search modes coexist: circle OR citta + zona ---
#
# The circle does not replace the two text fields. /analyze accepts exactly
# one of the two forms and routes them to different resolvers, which however
# return the same contract: from retrieve() down the pipeline does not know
# which one was used.


def _patch_zone_io(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Like ``_patch_io`` but for the citta + zona mode: geocode + reverse.

    Here the bbox is NOT computed from center+radius: it comes from Nominatim, so
    ``geocode_zone`` must be simulated too (it is never called in the circle mode).
    Returns the (zona, citta) pairs received, to verify the routing.
    """
    calls: list[tuple[str, str]] = []

    def _fake_geocode_zone(zona: str, citta: str) -> GeoResult:
        calls.append((zona, citta))
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    monkeypatch.setattr(area_search, "geocode_zone", _fake_geocode_zone)
    _patch_io(monkeypatch)
    return calls


def test_analyze_accepts_citta_and_zona(monkeypatch: pytest.MonkeyPatch) -> None:
    """Citta + zona produce the same structured response as the circle.

    The labels in the response are the typed ones, not the reverse geocode.
    """
    calls = _patch_zone_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"citta": "Roma", "zona": "Colosseo"},
        ),
    )
    assert resp.status_code == 200
    assert calls == [("Colosseo", "Roma")]
    body = resp.json()
    assert body["citta"] == "Roma"
    assert body["zona_normalizzata"] == "Colosseo"
    assert body["narrativa"] is None
    assert len(body["poi"]) == 2


def test_analyze_zone_not_found_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    """A zone that Nominatim does not find is a readable 422, not a random area.

    The message names zona and citta: it is what the frontend shows.
    """

    def _raise(zona: str, citta: str) -> GeoResult:
        raise ZoneNotFoundError(f"Zona non trovata: {zona!r} in {citta!r}")

    monkeypatch.setattr(area_search, "geocode_zone", _raise)
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"citta": "Roma", "zona": "Atlantide"},
        ),
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["errore"] == "zona_non_geocodificabile"
    assert "Atlantide" in detail["messaggio"]
    assert "Roma" in detail["messaggio"]


def test_analyze_rejects_both_modes_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Circle and citta/zona in the same body -> 422.

    Silently accepting one of them would mean analyzing a different area from the
    one the user believes to have chosen.
    """
    _patch_zone_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={
                "center": {"lat": 41.89, "lon": 12.49},
                "radius_m": 2000.0,
                "citta": "Roma",
                "zona": "Colosseo",
            },
        ),
    )
    assert resp.status_code == 422


def test_analyze_rejects_the_body_without_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neither circle nor citta/zona -> 422: there is no default area."""
    _patch_zone_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post("/analyze", json={}),  # pyright: ignore[reportUnknownMemberType]
    )
    assert resp.status_code == 422


@pytest.mark.parametrize(
    "body",
    [{"citta": "Roma"}, {"zona": "Colosseo"}, {"citta": "Roma", "zona": "   "}],
)
def test_analyze_rejects_missing_citta_or_zona(
    monkeypatch: pytest.MonkeyPatch, body: dict[str, str]
) -> None:
    """Both text fields are required, and non-empty."""
    calls = _patch_zone_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post("/analyze", json=body),  # pyright: ignore[reportUnknownMemberType]
    )
    assert resp.status_code == 422
    assert calls == []


def test_analyze_rejects_the_circle_without_radius(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The center alone is not enough: the circle requires both fields."""
    _patch_zone_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}},
        ),
    )
    assert resp.status_code == 422
