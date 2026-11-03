"""Endpoint and orchestration of the per-POI narrative (#197), offline."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer import area_search, zone_context_cache
from crime_risk_analyzer.analyze_narrative import run_analysis_fast
from crime_risk_analyzer.geocoding import GeoResult, ZoneNotFoundError
from crime_risk_analyzer.llm.client import LLMError, LLMResponse, get_llm_client
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.poi_narrative import (
    ContextMismatchError,
    PoiNarrativeRequest,
    PoiNarrativeResponse,
    PoiNotFoundError,
    _risk_model_of,  # pyright: ignore[reportPrivateUsage]
    run_poi_narrative,
)
from crime_risk_analyzer.rag import retrieval
from crime_risk_analyzer.sources.context import current_executor

_POI_ID = "node/1"

_BANK = PoiRiskProfile(
    terminus_class="Bank",
    hazards=["Bank_robbery", "Property_theft"],
    vulnerabilities=["Accesso non controllato"],
    sparql_paths=["Bank → havingHazard → Bank_robbery"],
)


class _FakeProfiler:
    def profile(self, terminus_class: str) -> PoiRiskProfile:
        return {"Bank": _BANK}.get(
            terminus_class, PoiRiskProfile(terminus_class=terminus_class)
        )


class _FakeLLMClient:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        return LLMResponse(
            text=(
                "Sintesi.\n\n"
                "[ONTOLOGIA]\nRischio rapina.\n\n"
                "[CONTESTO]\nVicino a una scuola.\n"
            ),
            llm_used="claude-sonnet-4-6",
            tokens_input=5,
            tokens_output=8,
            cache_hit=False,
            temperature=0.2,
            seed=42,
            prompt_hash="h",
        )


class _RaisingLLMClient:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        raise LLMError("provider down")


def _pois(citta: str) -> list[Poi]:
    return [
        {
            "id": _POI_ID,
            "name": "Banca A",
            "lat": 41.8900,
            "lon": 12.4920,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": citta,
        },
        {
            "id": "node/2",
            "name": "Liceo Cavour",
            "lat": 41.8901,
            "lon": 12.4921,
            "osm_tags": "amenity=school",
            "terminus_class": "School",
            "citta": citta,
        },
    ]


async def _geo_source(citta: str, zona: str) -> GeoResult:
    return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))


async def _poi_source(bbox: Bbox, citta: str) -> list[Poi]:
    return _pois(citta)


async def _prime_cache() -> str:
    """Fills the zone-context cache by running /analyze with the doubles.

    Returns the context fingerprint (#242): the tests send it back as the
    client would, instead of recomputing it and ending up testing the function
    against itself.

    Phase 1 of the route (``run_analysis_fast``, #292) is the only thing that
    deposits the zone context: it is exactly what precedes a user click on a
    POI, and it spends no model call to get there.
    """
    zone_context_cache.clear()
    resp = await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    return resp.contesto_hash


def _fake_reverse_geocode(lat: float, lon: float) -> tuple[str, str]:
    return ("Roma", "Colosseo")


def _patch_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replaces reverse geocode and Overpass for the HTTP endpoint tests (#318).

    ``retrieval.geocode_zone`` is not called by ``/analyze`` (the tests here use
    the circle, and ``resolve_circle`` always passes its own ``geo_source``):
    the only I/O to patch here is the reverse-geocoded label
    (``area_search.reverse_geocode_label``) and Overpass.
    """
    monkeypatch.setattr(area_search, "reverse_geocode_label", _fake_reverse_geocode)

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois(citta)

    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)


def _client(llm: object = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[current_executor] = lambda: _FakeProfiler()
    app.dependency_overrides[get_llm_client] = lambda: llm or _FakeLLMClient()
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("enabled", [True, False], ids=["istat-on", "istat-off"])
def test_poi_route_reads_the_switch_from_settings(
    enabled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from crime_risk_analyzer.config import Settings, get_settings
    from crime_risk_analyzer.rag.poi_generation import (
        POI_SYSTEM_PROMPT,
        POI_SYSTEM_PROMPT_ISTAT,
    )

    systems: list[str] = []

    class _Spy(_FakeLLMClient):
        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            systems.append(system_prompt)
            return await super().generate(system_prompt, user_content)

    _patch_io(monkeypatch)
    settings = Settings(istat_context_enabled=enabled)
    app = create_app()
    app.dependency_overrides[current_executor] = lambda: _FakeProfiler()
    app.dependency_overrides[get_llm_client] = lambda: _Spy()
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app, raise_server_exceptions=False)
    context_hash = _analyze(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/poi",
            json={
                "citta": "Roma",
                "zona": "Colosseo",
                "poi_id": _POI_ID,
                "contesto_hash": context_hash,
            },
        ),
    )
    assert resp.status_code == 200
    assert systems == [POI_SYSTEM_PROMPT_ISTAT if enabled else POI_SYSTEM_PROMPT]
    assert resp.json()["istat_attivo"] is enabled


def test_risk_model_of_propagates_source() -> None:
    vr = {
        "poi_id": "node/1",
        "poi": "Banca A",
        "risks": [
            {
                "hazard": "Bank_robbery",
                "confidence": "verificato",
                "tag": "ONTOLOGIA",
                "source": "Bank → havingHazard → Bank_robbery",
            }
        ],
        "terminus_class": "Bank",
        "critical_events": [],
        "vulnerabilities": [],
        "stakeholders": [],
        "sparql_path": "Bank → havingHazard → Bank_robbery",
    }
    model = _risk_model_of(vr)  # type: ignore[arg-type]
    assert model.risks[0].source == "Bank → havingHazard → Bank_robbery"


async def test_returns_narrative_for_a_poi_in_the_cached_zone() -> None:
    context_hash = await _prime_cache()
    out = await run_poi_narrative(
        "Roma",
        "Colosseo",
        _POI_ID,
        contesto_hash=context_hash,
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
    )
    assert out.poi_id == _POI_ID
    assert out.narrativa != ""
    assert out.fallback is False
    # The point's risks carry its id, not just the name: the id is what the
    # frontend uses to attribute them, and OSM names identify nothing.
    assert [(rm.poi_id, rm.poi) for rm in out.risk_models] == [(_POI_ID, "Banca A")]


async def test_cache_hit_does_not_touch_overpass() -> None:
    """On a hit no call is spent on a free public service (#232)."""
    context_hash = await _prime_cache()

    async def _exploding(bbox: Bbox, citta: str) -> list[Poi]:
        raise AssertionError("Overpass must not be called on a cache hit")

    out = await run_poi_narrative(
        "Roma",
        "Colosseo",
        _POI_ID,
        contesto_hash=context_hash,
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_exploding,
    )
    assert out.narrativa != ""


async def test_cold_cache_rebuilds_the_context() -> None:
    """With a cold cache and unchanged OSM the click stays usable (#242): the
    rebuild coincides with the context shown, so the narrative comes out.

    TTL expiry reproduced as the client experiences it: the analysis happened
    (and the fingerprint is the right one), but the cache no longer holds the
    context.
    """
    context_hash = await _prime_cache()
    zone_context_cache.clear()
    out = await run_poi_narrative(
        "Roma",
        "Colosseo",
        _POI_ID,
        contesto_hash=context_hash,
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    assert out.narrativa != ""
    assert zone_context_cache.get("Roma", "Colosseo") is not None


async def test_narrative_context_carries_the_neighbourhood() -> None:
    """The POI prompt must contain the neighbourhood: it is what sets it apart."""
    context_hash = await _prime_cache()
    seen: list[str] = []

    class _Recording:
        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            seen.append(user_content)
            return LLMResponse(
                text="x",
                llm_used="fake",
                tokens_input=1,
                tokens_output=1,
                cache_hit=False,
                temperature=0.0,
                seed=0,
                prompt_hash="h",
            )

    await run_poi_narrative(
        "Roma",
        "Colosseo",
        _POI_ID,
        contesto_hash=context_hash,
        executor=_FakeProfiler(),
        llm_client=_Recording(),
    )
    assert "PUNTO SELEZIONATO: Banca A" in seen[0]
    assert "Liceo Cavour" in seen[0]
    assert "COMPOSIZIONE DELLA ZONA:" in seen[0]


async def test_unknown_poi_id_raises_poi_not_found() -> None:
    """With an ALIGNED fingerprint an unknown id stays a 404, not a 409: the
    contract keeps distinguishing «your context is not mine» from «that id is
    not in this context» (#242)."""
    context_hash = await _prime_cache()
    with pytest.raises(PoiNotFoundError):
        await run_poi_narrative(
            "Roma",
            "Colosseo",
            "non-esiste",
            contesto_hash=context_hash,
            executor=_FakeProfiler(),
            llm_client=_FakeLLMClient(),
        )


async def test_llm_error_falls_back_without_raising() -> None:
    """Same policy as the zone path: structured data + fallback=True."""
    context_hash = await _prime_cache()
    out = await run_poi_narrative(
        "Roma",
        "Colosseo",
        _POI_ID,
        contesto_hash=context_hash,
        executor=_FakeProfiler(),
        llm_client=_RaisingLLMClient(),
    )
    assert out.fallback is True
    assert out.narrativa == ""
    assert out.risk_models != []


# --- #242: the context fingerprint makes the anchoring verifiable ---


async def _divergent_poi_source(bbox: Bbox, citta: str) -> list[Poi]:
    """Different OSM capture: one more POI than ``_poi_source``.

    It is the real case of the defect (#242): between the analysis and the
    click, OSM changes or the MAX_POIS cap lets a point in, and the rebuilt
    neighbourhood is not the one shown on the map.
    """
    return [
        *_pois(citta),
        {
            "id": "node/3",
            "name": "Farmacia Nuova",
            "lat": 41.8902,
            "lon": 12.4922,
            "osm_tags": "amenity=pharmacy",
            "terminus_class": "Pharmacy",
            "citta": citta,
        },
    ]


async def test_warm_cache_overwritten_by_a_second_analysis_rejects() -> None:
    """The case the issue did not foresee, reproduced in full: the same zone is
    re-analysed (another tab, zone «Rigenera») and ``put`` overwrites the cache
    entry. The client that still shows the FIRST analysis asks for the narrative
    of a POI: without a comparison it would be born on the context of the
    second, silently.

    Reproducing the overwrite, instead of sending an arbitrary string, is what
    makes the test a proof of acceptance criterion 2: it would stay red even if
    the fingerprint were stored at ``put`` time instead of being recomputed on
    the list about to be used.
    """
    first = await _prime_cache()
    # Second analysis of the SAME zone: different OSM capture, cache rewritten.
    second = await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_divergent_poi_source,
        geo_source=_geo_source,
    )
    assert second.contesto_hash != first
    with pytest.raises(ContextMismatchError):
        await run_poi_narrative(
            "Roma",
            "Colosseo",
            _POI_ID,
            contesto_hash=first,
            executor=_FakeProfiler(),
            llm_client=_FakeLLMClient(),
        )


async def test_mismatched_fingerprint_spends_no_llm_call() -> None:
    """The comparison precedes generation: a rejection costs no tokens."""
    await _prime_cache()

    class _Exploding:
        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            raise AssertionError(
                "the LLM must not be called on a mismatched fingerprint"
            )

    with pytest.raises(ContextMismatchError):
        await run_poi_narrative(
            "Roma",
            "Colosseo",
            _POI_ID,
            contesto_hash="non-combacia",
            executor=_FakeProfiler(),
            llm_client=_Exploding(),
        )


async def test_cold_cache_with_divergent_rebuild_rejects() -> None:
    """The case described by #242: with a cold cache the rebuild returns a
    neighbourhood different from the one shown -> rejection, not silent prose."""
    context_hash = await _prime_cache()
    zone_context_cache.clear()
    with pytest.raises(ContextMismatchError):
        await run_poi_narrative(
            "Roma",
            "Colosseo",
            _POI_ID,
            contesto_hash=context_hash,
            executor=_FakeProfiler(),
            llm_client=_FakeLLMClient(),
            poi_source=_divergent_poi_source,
            geo_source=_geo_source,
        )
    # The rejected context does not enter the cache: nobody has ever seen it, and
    # it would take a slot, evicting a valid zone when the cache is full (review M1).
    assert zone_context_cache.get("Roma", "Colosseo") is None


async def test_cold_cache_geocode_failure_becomes_context_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#318 (review finding I2): with a cold cache and NO ``geo_source`` (the real
    case of the route) the rebuild does a FORWARD geocode of ``citta``/``zona``
    — which however originate from a reverse geocode of the circle, almost never
    a string that Nominatim finds again when searching forward. The failure
    must not propagate as a 422 "zona non geocodificabile" (the operator typed
    nothing wrong): it becomes the same ``ContextMismatchError`` -> 409 of the
    ``contesto_hash`` branch, with the same invitation to rerun the analysis
    (twin of the homonymous test in ``test_analyze_narrative.py``).
    """
    context_hash = await _prime_cache()
    zone_context_cache.clear()

    def _boom(zona: str, citta: str) -> GeoResult:
        raise ZoneNotFoundError("unknown zone")

    monkeypatch.setattr(retrieval, "geocode_zone", _boom)

    with pytest.raises(ContextMismatchError):
        await run_poi_narrative(
            "Roma",
            "Colosseo",
            _POI_ID,
            contesto_hash=context_hash,
            executor=_FakeProfiler(),
            llm_client=_FakeLLMClient(),
        )


async def test_fingerprint_does_not_enter_the_prompt() -> None:
    """Guard #184/#197: the fingerprint is COMPARED, never consumed. If it ended up
    in the prompt it would be client data inside the model context."""
    context_hash = await _prime_cache()
    seen: list[str] = []

    class _Recorder:
        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            seen.append(user_content + system_prompt)
            return LLMResponse(
                text="x",
                llm_used="fake",
                tokens_input=1,
                tokens_output=1,
                cache_hit=False,
                temperature=0.0,
                seed=0,
                prompt_hash="h",
            )

    await run_poi_narrative(
        "Roma",
        "Colosseo",
        _POI_ID,
        contesto_hash=context_hash,
        executor=_FakeProfiler(),
        llm_client=_Recorder(),
    )
    assert context_hash not in seen[0]


def _analyze(client: TestClient) -> str:
    """Runs the zone analysis and returns the fingerprint, as the client would."""
    zone_resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    return str(zone_resp.json()["contesto_hash"])


def test_endpoint_returns_200_and_narrative(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    client = _client()
    context_hash = _analyze(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/poi",
            json={
                "citta": "Roma",
                "zona": "Colosseo",
                "poi_id": _POI_ID,
                "contesto_hash": context_hash,
            },
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["poi_id"] == _POI_ID
    assert body["narrativa_fonti"]["ontologia"] != ""
    assert body["fallback"] is False


def test_endpoint_returns_404_for_unknown_poi(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    client = _client()
    context_hash = _analyze(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/poi",
            json={
                "citta": "Roma",
                "zona": "Colosseo",
                "poi_id": "non-esiste",
                "contesto_hash": context_hash,
            },
        ),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["errore"] == "poi_non_nel_contesto"


def test_endpoint_returns_409_for_mismatched_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#242: a fingerprint that does not identify the context -> 409 with an
    invitation to rerun the analysis, not a normal-looking narrative."""
    _patch_io(monkeypatch)
    client = _client()
    _analyze(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/poi",
            json={
                "citta": "Roma",
                "zona": "Colosseo",
                "poi_id": _POI_ID,
                "contesto_hash": "0" * 64,
            },
        ),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["errore"] == "contesto_disallineato"
    assert "rilancia" in resp.json()["detail"]["messaggio"]


def test_endpoint_requires_the_context_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The field is mandatory: without a fingerprint there is no valid request,
    otherwise the guarantee of #242 would be opt-in."""
    _patch_io(monkeypatch)
    client = _client()
    _analyze(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/poi",
            json={"citta": "Roma", "zona": "Colosseo", "poi_id": _POI_ID},
        ),
    )
    assert resp.status_code == 422


def test_endpoint_rejects_too_short_contesto_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``contesto_hash`` below min_length=64 -> 422, not 409.

    Same bound as ``ZoneNarrativeRequest``: a fingerprint shorter than a sha256
    digest does not have the shape of a fingerprint and is rejected at
    validation, before the route pays a rebuild (geocoding + Overpass) on a cold
    cache only to reject it anyway. The 409 stays for the well-formed
    fingerprint that identifies ANOTHER context.
    """
    _patch_io(monkeypatch)
    client = _client()
    _analyze(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/poi",
            json={
                "citta": "Roma",
                "zona": "Colosseo",
                "poi_id": _POI_ID,
                "contesto_hash": "0" * 8,
            },
        ),
    )
    assert resp.status_code == 422


# --- #184: anti-scoring guard extended to the ``/analyze/poi`` contract (#197) ---
# Same exact-set pattern as ``test_orchestrator``: the payload grep below only
# catches already-known field names, while the exact set turns ANY new field
# red, forcing a conscious review of the legal constraint.


def test_poi_narrative_request_surface_is_exactly_id_zone_and_fingerprint() -> None:
    """REQUEST contract (#197/#242): the client supplies the zone, the point id
    and an opaque fingerprint — nothing else. The non-injectability claim is a
    constraint on the request: a future ``terminus_class``/``risks`` field would
    give the client a say on the risk data, which must stay re-derived by the
    server. The exact set pins it."""
    assert set(PoiNarrativeRequest.model_fields) == {
        "citta",
        "zona",
        "poi_id",
        "contesto_hash",
    }


def test_poi_narrative_response_has_no_numeric_danger_scoring_field() -> None:
    """``/analyze/poi`` response contract: no numeric danger scoring
    (_project.md §Vincoli). The numeric fields present
    (``tokens_*``/``latenza_ms``) measure cost and performance, NOT the
    magnitude of danger. A rating field added here would break the exact set."""
    assert set(PoiNarrativeResponse.model_fields) == {
        "poi_id",
        "narrativa",
        "narrativa_fonti",
        "risk_models",
        "tokens_input",
        "tokens_output",
        "latenza_ms",
        "repro",
        "fallback",
        "istat_attivo",
        "istat_versione_dati",
        "istat_frasi_scartate",
    }


def test_endpoint_response_never_contains_a_danger_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anti-scoring guard extended to the new endpoint (#184)."""
    _patch_io(monkeypatch)
    client = _client()
    context_hash = _analyze(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/poi",
            json={
                "citta": "Roma",
                "zona": "Colosseo",
                "poi_id": _POI_ID,
                "contesto_hash": context_hash,
            },
        ),
    )
    assert resp.status_code == 200
    payload = resp.text.lower()
    for forbidden in ("punteggio", "score", "livello di rischio", "pericolosit"):
        assert forbidden not in payload
