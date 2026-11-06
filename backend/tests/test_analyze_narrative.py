"""The two phases of ``/analyze`` (#259) and the routes that expose them (#292).

Phase 1: fast structured response, narrativa not generated yet. Phase 2:
``POST /analyze/narrativa`` generates the text on the context warmed by phase 1.
"""

from __future__ import annotations

import inspect
import re
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from crime_risk_analyzer import area_search, geocoding, zone_context_cache
from crime_risk_analyzer.config import Settings, get_settings
from crime_risk_analyzer.geocoding import GeoResult, ZoneNotFoundError
from crime_risk_analyzer.llm.client import LLMError, LLMResponse, get_llm_client
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.poi_narrative import ContextMismatchError
from crime_risk_analyzer.rag import retrieval
from crime_risk_analyzer.rag.generation import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_REQUEST_TOKEN_BUDGET,
)
from crime_risk_analyzer.rag.grounding import GroundedContext
from crime_risk_analyzer.rag.retrieval import RetrievalContext
from crime_risk_analyzer.sources.context import current_executor
from tests.eval._doubles import FakeProfiler, make_poi

_BANK = PoiRiskProfile(
    ontology_class="Bank",
    hazards=["Bank_robbery", "Property_theft"],
    vulnerabilities=["Accesso non controllato"],
    sparql_paths=["Bank → havingHazard → Bank_robbery"],
)


def _pois(citta: str) -> list[Poi]:
    return [
        make_poi(lon=12.4920, citta=citta),
    ]


def _dense_pois(citta: str) -> list[Poi]:
    """OSM capture different from :func:`_pois`: one more POI, also with risks.

    It serves two purposes: it is the DIVERGENT capture of the #242 tests (between
    the two phases OSM changes, or the ``MAX_POIS`` cap lets a point in) and it is
    the minimum for which ``build_context_str`` can truncate the context (with a
    single POI it never truncates), which the token cap tests require.
    """
    return [
        *_pois(citta),
        make_poi(id="node/2", name="Banca B", lat=41.8901, lon=12.4921, citta=citta),
    ]


async def _geo_source(citta: str, zona: str) -> GeoResult:
    return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))


async def _poi_source(bbox: Bbox, citta: str) -> list[Poi]:
    return _pois(citta)


async def _divergent_poi_source(bbox: Bbox, citta: str) -> list[Poi]:
    return _dense_pois(citta)


async def test_fast_response_has_no_narrativa_yet() -> None:
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast

    out = await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=FakeProfiler({"Bank": _BANK}),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    assert out.narrativa is None
    assert out.fallback is False
    assert len(out.poi) == 1
    assert out.poi[0].id == "node/1"
    assert (out.zona_geo.lat, out.zona_geo.lon) == (41.89, 12.49)
    assert out.messaggio is None


@pytest.mark.parametrize("enabled", [True, False], ids=["istat-on", "istat-off"])
async def test_fast_response_exposes_istat_only_with_the_switch(
    enabled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#346: phase 1 is the one that fills the cards, so it is here that
    ``poi[].istat`` must arrive -- and only with the switch on."""
    zone_context_cache.clear()
    from crime_risk_analyzer import analyze_narrative
    from crime_risk_analyzer.rag.grounding import ground as real_ground
    from tests.istat._factories import BANKROB, istat_poi

    istat_payload = istat_poi(BANKROB)

    def _ground_with_istat(ctx: RetrievalContext) -> GroundedContext:
        grounded = real_ground(ctx)
        for vr in grounded["validated_risks"]:
            vr["istat"] = istat_payload
        return grounded

    monkeypatch.setattr(analyze_narrative, "ground", _ground_with_istat)
    out = await analyze_narrative.run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=FakeProfiler({"Bank": _BANK}),
        poi_source=_poi_source,
        geo_source=_geo_source,
        istat_context_enabled=enabled,
    )
    assert out.poi[0].istat == (istat_payload if enabled else None)


async def test_fast_response_zero_poi_has_explicit_message() -> None:
    """#260: zero POIs in coverage but zone geocoded -- the response carries
    ``zona_geo`` (to recenter the map) and an explicit ``messaggio`` that
    distinguishes this case from a zone not found."""
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast

    async def _no_pois(bbox: Bbox, citta: str) -> list[Poi]:
        return []

    out = await run_analysis_fast(
        "Roma",
        "Zona senza POI",
        executor=FakeProfiler({"Bank": _BANK}),
        poi_source=_no_pois,
        geo_source=_geo_source,
    )
    assert out.poi == []
    assert (out.zona_geo.lat, out.zona_geo.lon) == (41.89, 12.49)
    assert out.messaggio is not None


async def test_phase1_then_phase2_zero_poi_real_narrativa_cancels_message() -> None:
    """#260 (review finding): phase 2 recomputes ``messaggio`` from scratch, it does
    not inherit the one from phase 1 -- if the LLM writes real prose anyway on a
    context without POIs, a ``messaggio`` suggesting "nothing to see" next to that
    narrativa would be contradictory information for whoever reads the final
    response."""
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import (
        run_analysis_fast,
        run_zone_narrative,
    )

    async def _no_pois(bbox: Bbox, citta: str) -> list[Poi]:
        return []

    phase1 = await run_analysis_fast(
        "Roma",
        "Zona senza POI fase2",
        executor=FakeProfiler({"Bank": _BANK}),
        poi_source=_no_pois,
        geo_source=_geo_source,
    )
    assert phase1.poi == []
    assert phase1.narrativa is None
    assert phase1.messaggio is not None

    phase2 = await run_zone_narrative(
        "Roma",
        "Zona senza POI fase2",
        contesto_hash=phase1.contesto_hash,
        executor=FakeProfiler({"Bank": _BANK}),
        llm_client=_FakeLLMClient(),
    )
    assert phase2.narrativa != ""
    assert phase2.messaggio is None


async def test_phase1_then_phase2_zero_poi_llm_fallback_keeps_message() -> None:
    """Same phase1->phase2 sequence on an empty zone, but phase 2 falls on the LLM:
    without a real narrativa, the explicit message remains the only information
    available -- it must not vanish just because it is the second call."""
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import (
        run_analysis_fast,
        run_zone_narrative,
    )

    async def _no_pois(bbox: Bbox, citta: str) -> list[Poi]:
        return []

    phase1 = await run_analysis_fast(
        "Roma",
        "Zona senza POI fase2 fallback",
        executor=FakeProfiler({"Bank": _BANK}),
        poi_source=_no_pois,
        geo_source=_geo_source,
    )
    phase2 = await run_zone_narrative(
        "Roma",
        "Zona senza POI fase2 fallback",
        contesto_hash=phase1.contesto_hash,
        executor=FakeProfiler({"Bank": _BANK}),
        llm_client=_RaisingLLMClient(),
    )
    assert phase2.narrativa == ""
    assert phase2.fallback is True
    assert phase2.messaggio is not None


async def test_fast_response_warms_the_zone_context_cache() -> None:
    """The context stays stored: /analyze/narrativa and /analyze/poi must not redo
    Overpass (#232). Phase 1 is the only one that warms the cache -- the
    evaluation path (`run_analysis`) does not touch it."""
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast

    await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=FakeProfiler({"Bank": _BANK}),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    assert zone_context_cache.get("Roma", "Colosseo") is not None


async def test_fast_response_contesto_hash_matches_the_cached_context() -> None:
    """The returned fingerprint is the one /analyze/narrativa must receive back to
    pass the check (#242)."""
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast
    from crime_risk_analyzer.context_fingerprint import fingerprint

    out = await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=FakeProfiler({"Bank": _BANK}),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    cached = zone_context_cache.get("Roma", "Colosseo")
    assert cached is not None
    assert out.contesto_hash == fingerprint(cached["retrieval"]["pois"])


# --- #318: radius_m filters the POIs server-side in run_analysis_fast ---
# Same pattern as ``run_baseline`` (Task 5, test_orchestrator.py): the filter
# lives between ``retrieve`` and ``ground``, so the zone cache must be warmed
# with the ALREADY filtered context, not the raw one.


def _pois_by_radius(citta: str) -> list[Poi]:
    return [
        *_pois(citta),
        make_poi(
            id="node/2", name="Banca Lontana", lat=42.100, lon=12.700, citta=citta
        ),
    ]


async def _poi_source_by_radius(bbox: Bbox, citta: str) -> list[Poi]:
    return _pois_by_radius(citta)


async def test_run_analysis_fast_filters_by_radius() -> None:
    """``radius_m`` filters the POIs server-side from the geocoded center (#318).

    The center of ``_geo_source`` (41.89, 12.49) is ~166m from ``Banca A`` (within
    the requested 300m) but tens of km from ``Banca Lontana``: only the first one
    stays in the response.
    """
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast

    out = await run_analysis_fast(
        "Roma",
        "Raggio",
        executor=FakeProfiler({"Bank": _BANK}),
        poi_source=_poi_source_by_radius,
        geo_source=_geo_source,
        radius_m=300.0,
    )
    assert [p.id for p in out.poi] == ["node/1"]


async def test_run_analysis_fast_without_radius_m_is_identical_to_today() -> None:
    """``radius_m=None`` (the default) does not change the pre-#318 behavior:
    same call as ``test_fast_response_has_no_narrativa_yet``, no filter applied
    (explicit regression)."""
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast

    out = await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=FakeProfiler({"Bank": _BANK}),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    assert out.narrativa is None
    assert out.fallback is False
    assert len(out.poi) == 1
    assert out.poi[0].id == "node/1"
    assert (out.zona_geo.lat, out.zona_geo.lon) == (41.89, 12.49)
    assert out.messaggio is None


class _FakeLLMClient:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        return LLMResponse(
            text=(
                "Sintesi.\n\n[ONTOLOGIA]\nRischio rapina.\n\n"
                "[CONTESTO]\nZona centrale.\n"
            ),
            llm_used="test-model",
            tokens_input=5,
            tokens_output=8,
            cache_hit=False,
            temperature=0.2,
            seed=42,
            prompt_hash="h",
        )


class _RaisingLLMClient:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        raise LLMError("provider giu'")


async def _prime_cache() -> str:
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast

    zone_context_cache.clear()
    resp = await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=FakeProfiler({"Bank": _BANK}),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    assert resp.contesto_hash is not None
    return resp.contesto_hash


async def test_zone_narrative_returns_text_for_the_cached_zone() -> None:
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    context_hash = await _prime_cache()
    out = await run_zone_narrative(
        "Roma",
        "Colosseo",
        contesto_hash=context_hash,
        executor=FakeProfiler({"Bank": _BANK}),
        llm_client=_FakeLLMClient(),
    )
    assert out.narrativa != ""
    assert out.fallback is False


async def test_zone_narrative_cache_hit_does_not_touch_overpass() -> None:
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    context_hash = await _prime_cache()

    async def _exploding(bbox: Bbox, citta: str) -> list[Poi]:
        raise AssertionError("Overpass must not be called on a cache hit")

    out = await run_zone_narrative(
        "Roma",
        "Colosseo",
        contesto_hash=context_hash,
        executor=FakeProfiler({"Bank": _BANK}),
        llm_client=_FakeLLMClient(),
        poi_source=_exploding,
    )
    assert out.narrativa != ""


async def test_zone_narrative_cold_cache_rebuilds_the_context() -> None:
    """TTL expired between the two phases: with OSM unchanged the narrativa still
    comes out.

    It is the path that the route makes really reachable (#292): the frontend can
    ask for the text long after the analysis. The rebuild coincides with the
    context shown, so it passes the #242 check, and the context goes back into the
    cache for the subsequent clicks on the POIs.
    """
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    context_hash = await _prime_cache()
    zone_context_cache.clear()
    out = await run_zone_narrative(
        "Roma",
        "Colosseo",
        contesto_hash=context_hash,
        executor=FakeProfiler({"Bank": _BANK}),
        llm_client=_FakeLLMClient(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    assert out.narrativa != ""
    assert zone_context_cache.get("Roma", "Colosseo") is not None


async def test_zone_narrative_cold_cache_divergent_rebuild_refuses() -> None:
    """On a cold cache the rebuild gives a POI list different from the one on screen
    -> refusal, not silent prose about another neighborhood (#242).

    And the refused context does NOT enter the cache: nobody has ever had it in
    front of them and it would take a slot, evicting a valid zone when the cache is
    full (same choice as ``run_poi_narrative``).
    """
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    context_hash = await _prime_cache()
    zone_context_cache.clear()
    with pytest.raises(ContextMismatchError):
        await run_zone_narrative(
            "Roma",
            "Colosseo",
            contesto_hash=context_hash,
            executor=FakeProfiler({"Bank": _BANK}),
            llm_client=_FakeLLMClient(),
            poi_source=_divergent_poi_source,
            geo_source=_geo_source,
        )
    assert zone_context_cache.get("Roma", "Colosseo") is None


async def test_zone_narrative_cold_cache_geocode_failure_becomes_context_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#318 (review finding I2): on a cold cache WITHOUT ``geo_source`` (the real
    case of the route) the rebuild does a FORWARD geocode of ``citta``/``zona`` --
    which however come from a reverse geocode of the circle, almost never a string
    that Nominatim finds again when searched forward. The failure must not
    propagate as a 422 "zone not geocodable" (the operator typed nothing wrong): it
    becomes the same ``ContextMismatchError`` -> 409 as the ``contesto_hash``
    branch, with the same invitation to rerun the analysis.
    """
    context_hash = await _prime_cache()
    zone_context_cache.clear()

    def _boom(zona: str, citta: str) -> GeoResult:
        raise ZoneNotFoundError("zona ignota")

    monkeypatch.setattr(retrieval, "geocode_zone", _boom)

    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    with pytest.raises(ContextMismatchError):
        await run_zone_narrative(
            "Roma",
            "Colosseo",
            contesto_hash=context_hash,
            executor=FakeProfiler({"Bank": _BANK}),
            llm_client=_FakeLLMClient(),
        )


async def test_zone_narrative_context_mismatch_raises() -> None:
    """Zone re-analyzed between the two calls (#242): same guard as /analyze/poi."""
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    await _prime_cache()
    with pytest.raises(ContextMismatchError):
        await run_zone_narrative(
            "Roma",
            "Colosseo",
            contesto_hash="hash-vecchio-non-valido",
            executor=FakeProfiler({"Bank": _BANK}),
            llm_client=_FakeLLMClient(),
        )


async def test_zone_narrative_llm_error_falls_back_without_raising() -> None:
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    context_hash = await _prime_cache()
    out = await run_zone_narrative(
        "Roma",
        "Colosseo",
        contesto_hash=context_hash,
        executor=FakeProfiler({"Bank": _BANK}),
        llm_client=_RaisingLLMClient(),
    )
    assert out.fallback is True
    assert out.narrativa == ""


async def test_zone_narrative_declares_the_model_that_wrote() -> None:
    """Which of the two models produced the narrativa must be observable.

    The manual Claude/Groq switch (`LLM_PROVIDER`, never an automatic failover) is
    the pivot of the thesis comparison: after the split (#292) phase 1 exposes an
    empty ``llm_used`` by construction and, without this field, neither response
    would say anymore who wrote the text being read. Same source as the LLM branch
    of ``run_analysis``: the ``llm_used`` of the generation layer.
    """
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    context_hash = await _prime_cache()
    out = await run_zone_narrative(
        "Roma",
        "Colosseo",
        contesto_hash=context_hash,
        executor=FakeProfiler({"Bank": _BANK}),
        llm_client=_FakeLLMClient(),
    )
    assert out.llm_used == "test-model"


async def test_zone_narrative_fallback_does_not_attribute_the_text_to_a_model() -> None:
    """In the fallback no model wrote anything: ``llm_used`` stays empty, as in
    ``_structured_response`` for the branch without LLM."""
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    context_hash = await _prime_cache()
    out = await run_zone_narrative(
        "Roma",
        "Colosseo",
        contesto_hash=context_hash,
        executor=FakeProfiler({"Bank": _BANK}),
        llm_client=_RaisingLLMClient(),
    )
    assert out.fallback is True
    assert out.llm_used == ""


def test_zone_narrative_response_has_no_numeric_danger_scoring_field() -> None:
    """Same constraint as `PoiNarrativeResponse` (_project.md, Constraints): the exact
    set prevents sneaking in a numeric danger score.

    ``messaggio`` (#260) is explanatory text conditioned on empty POIs/narrativa,
    not a score: a legitimate addition on the same footing as
    ``AnalyzeResponse.messaggio``.

    ``istat_frasi_scartate`` (#345) counts the sentences removed by the figures
    check: transparency on the filter, not a measure of danger."""
    from crime_risk_analyzer.analyze_narrative import ZoneNarrativeResponse

    assert set(ZoneNarrativeResponse.model_fields) == {
        "narrativa",
        "narrativa_fonti",
        "llm_used",
        "tokens_input",
        "tokens_output",
        "latenza_ms",
        "repro",
        "fallback",
        "messaggio",
        "istat_attivo",
        "istat_versione_dati",
        "istat_frasi_scartate",
    }


def test_zone_narrative_request_surface_is_citta_zona_domanda_contesto_hash() -> None:
    """Twin guard of
    ``test_baseline_request_surface_is_circle_or_citta_zona_tipo_poi``
    (`test_orchestrator.py`, #263): it fixes the other side of the iso-input
    asymmetry.

    ``ZoneNarrativeRequest`` carries ``domanda`` but not ``tipo_poi``;
    ``BaselineRequest`` carries ``tipo_poi`` but not ``domanda``: accepted and
    documented asymmetry (#263, closed). If one day
    ``tipo_poi`` shows up here (or ``domanda`` disappears), it must be updated
    together with the docstring of ``ZoneNarrativeRequest`` and with the twin test
    on ``BaselineRequest``."""
    from crime_risk_analyzer.analyze_narrative import ZoneNarrativeRequest

    assert set(ZoneNarrativeRequest.model_fields) == {
        "citta",
        "zona",
        "domanda",
        "contesto_hash",
    }


# --- #119: the cap on ``domanda`` lives where the field lives ---
# It was ``AnalyzeRequest`` that carried the domanda; after the split (#292)
# phase 1 does not call the model and the field stayed only here, so here goes
# the bound on tokens/cost/prompt-injection surface.


def test_zone_narrative_request_rejects_overlong_domanda() -> None:
    from crime_risk_analyzer.analyze_narrative import ZoneNarrativeRequest

    with pytest.raises(ValidationError):
        ZoneNarrativeRequest(
            citta="Roma", zona="Colosseo", contesto_hash="0" * 64, domanda="x" * 501
        )


def test_zone_narrative_request_accepts_domanda_at_max_length() -> None:
    from crime_risk_analyzer.analyze_narrative import ZoneNarrativeRequest

    req = ZoneNarrativeRequest(
        citta="Roma", zona="Colosseo", contesto_hash="0" * 64, domanda="x" * 500
    )
    assert req.domanda is not None
    assert len(req.domanda) == 500


# --- #292: the two phases on the HTTP routes ---
# Same scaffolding as the ``/analyze/poi`` tests: doubles via
# ``dependency_overrides``, I/O (geocoding/Overpass) replaced with monkeypatch,
# no network.


class _RecordingLLMClient:
    """Spy: records the prompts the route sends to the model."""

    def __init__(
        self, text: str = "Sintesi.\n\n[ONTOLOGIA]\nRischio rapina.\n"
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self._text = text

    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        self.calls.append((system_prompt, user_content))
        return LLMResponse(
            text=self._text,
            llm_used="test-model",
            tokens_input=5,
            tokens_output=8,
            cache_hit=False,
            temperature=0.2,
            seed=42,
            prompt_hash="h",
        )


def _fake_reverse_geocode(lat: float, lon: float) -> tuple[str, str]:
    return ("Roma", "Colosseo")


def _patch_io(monkeypatch: pytest.MonkeyPatch, *, dense: bool = False) -> None:
    """Replaces reverse geocode and Overpass for the HTTP route tests (#318).

    ``retrieval.geocode_zone`` is not called by ``/analyze`` (the tests here use
    the circle, and ``resolve_circle`` always passes its own ``geo_source``): the
    only I/O to patch here is the reverse-geocoded label
    (``area_search.reverse_geocode_label``) and Overpass.
    """
    monkeypatch.setattr(area_search, "reverse_geocode_label", _fake_reverse_geocode)

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _dense_pois(citta) if dense else _pois(citta)

    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)


def _client(llm: object = None, settings: Settings | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[current_executor] = lambda: FakeProfiler({"Bank": _BANK})
    app.dependency_overrides[get_llm_client] = lambda: llm or _FakeLLMClient()
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app, raise_server_exceptions=False)


def _post_analyze(client: TestClient) -> str:
    """Phase 1: zone analysis; returns the fingerprint, as the client would."""
    zone_context_cache.clear()
    zone_resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert zone_resp.status_code == 200
    return str(zone_resp.json()["contesto_hash"])


def _post_narrative(
    client: TestClient, context_hash: str, *, question: str | None = None
) -> httpx.Response:
    """Phase 2: the same call the frontend makes after rendering the data."""
    body: dict[str, str] = {
        "citta": "Roma",
        "zona": "Colosseo",
        "contesto_hash": context_hash,
    }
    if question is not None:
        body["domanda"] = question
    return cast(
        httpx.Response,
        client.post("/analyze/narrativa", json=body),  # pyright: ignore[reportUnknownMemberType]
    )


@pytest.mark.parametrize("enabled", [True, False], ids=["istat-on", "istat-off"])
def test_zone_route_follows_the_switch(
    enabled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from crime_risk_analyzer.rag.generation import SYSTEM_PROMPT, SYSTEM_PROMPT_ISTAT

    _patch_io(monkeypatch)
    llm = _RecordingLLMClient()
    client = _client(llm=llm, settings=Settings(istat_context_enabled=enabled))
    resp = _post_narrative(client, _post_analyze(client))
    assert resp.status_code == 200
    assert llm.calls[0][0] == (SYSTEM_PROMPT_ISTAT if enabled else SYSTEM_PROMPT)
    assert resp.json()["istat_attivo"] is enabled
    assert (resp.json()["istat_versione_dati"] is not None) is enabled


def test_zone_route_with_model_selection_uses_the_selection_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#366: ``istat_scelta_modello`` reaches the prompt, only with ISTAT on."""
    from crime_risk_analyzer.rag.generation import (
        SYSTEM_PROMPT,
        SYSTEM_PROMPT_ISTAT_SELECTION,
    )

    _patch_io(monkeypatch)
    llm = _RecordingLLMClient()
    client = _client(
        llm=llm,
        settings=Settings(istat_context_enabled=True, istat_scelta_modello=True),
    )
    assert _post_narrative(client, _post_analyze(client)).status_code == 200
    assert llm.calls[0][0] == SYSTEM_PROMPT_ISTAT_SELECTION

    llm_off = _RecordingLLMClient()
    disabled = _client(
        llm=llm_off,
        settings=Settings(istat_context_enabled=False, istat_scelta_modello=True),
    )
    assert _post_narrative(disabled, _post_analyze(disabled)).status_code == 200
    assert llm_off.calls[0][0] == SYSTEM_PROMPT


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        d = cast(dict[str, object], value)
        return set(d) | {k for v in d.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in cast(list[object], value) for k in _keys(v)}
    return set()


def test_with_model_selection_the_weight_does_not_leave_the_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D9 (#366): the weight chosen by the model does not enter the API contract nor
    the narrativa (no ranking).

    The fake model really returns a selection anchored to the ISTAT block, so the
    check on the narrativa is not vacuous: the ISTAT sentence composed by the app
    proves the selection was read. The weight is ``medio`` because ``alto`` already
    appears in the composed sentence ("tasso più alto").
    """
    _patch_io(monkeypatch)
    llm = _RecordingLLMClient(
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRischio rapina.\n\n"
        "SCELTA DATI ISTAT:\nFurto di beni | furti | medio\n"
    )
    client = _client(
        llm=llm,
        settings=Settings(istat_context_enabled=True, istat_scelta_modello=True),
    )
    zone_context_cache.clear()
    zone_resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert zone_resp.status_code == 200
    narrative_resp = _post_narrative(client, str(zone_resp.json()["contesto_hash"]))
    assert narrative_resp.status_code == 200
    # Phase 1 never calls the model, so its response cannot carry the selection.
    assert len(llm.calls) == 1
    assert (
        "la voce «furti» (rischio: Furto di beni)"
        in (narrative_resp.json()["narrativa"])
    )
    for response_obj in (zone_resp, narrative_resp):
        resp_body = response_obj.json()
        assert not {k for k in _keys(resp_body) if "scelta" in k or "peso" in k}
        assert "SCELTA DATI ISTAT" not in response_obj.text
        assert not re.search(r"\bmedio\b", response_obj.text)


def test_endpoint_completes_the_narrativa_left_open_by_phase_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real product path: ``/analyze`` without text, then the text.

    The two assertions are in the same test on purpose: it is the sequence the
    frontend runs, and the ``narrativa=None`` of phase 1 makes sense only if
    phase 2 completes it.
    """
    _patch_io(monkeypatch)
    client = _client()
    zone_resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert zone_resp.status_code == 200
    assert zone_resp.json()["narrativa"] is None

    resp = _post_narrative(client, str(zone_resp.json()["contesto_hash"]))

    assert resp.status_code == 200
    body = resp.json()
    assert body["narrativa"] != ""
    assert body["narrativa_fonti"]["ontologia"] != ""
    assert body["fallback"] is False
    # On the wire, not just in the model: the response of this route is the only
    # place where it is possible to see which of the two providers wrote the text.
    assert body["llm_used"] == "test-model"


def test_endpoint_warm_cache_does_not_call_overpass_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 2 reuses the context warmed by phase 1 (#232): two HTTP calls, a single
    OSM capture -- otherwise the split would cost one more call to a free public
    service."""
    _patch_io(monkeypatch)
    client = _client()
    context_hash = _post_analyze(client)

    async def _explodes(*args: object, **kwargs: object) -> list[Poi]:
        raise AssertionError("Overpass must not be called in phase 2")

    monkeypatch.setattr(retrieval, "fetch_pois", _explodes)
    resp = _post_narrative(client, context_hash)

    assert resp.status_code == 200
    assert resp.json()["narrativa"] != ""


def test_endpoint_returns_409_for_mismatched_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#242 on the zone path: a fingerprint that does not identify the context -> 409
    with an invitation to rerun, not a normal-looking narrative. Same register
    (central handler) as ``/analyze/poi``."""
    _patch_io(monkeypatch)
    client = _client()
    _post_analyze(client)

    resp = _post_narrative(client, "0" * 64)

    assert resp.status_code == 409
    assert resp.json()["detail"]["errore"] == "contesto_disallineato"
    assert "rilancia" in resp.json()["detail"]["messaggio"]


def test_endpoint_409_does_not_spend_an_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal precedes the generation: a 409 costs no tokens."""
    _patch_io(monkeypatch)
    llm = _RecordingLLMClient()
    client = _client(llm=llm)
    _post_analyze(client)

    resp = _post_narrative(client, "0" * 64)

    assert resp.status_code == 409
    assert llm.calls == []


def test_endpoint_requires_the_context_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The field is mandatory: without a fingerprint there is no valid request,
    otherwise the #242 guarantee would be opt-in here too."""
    _patch_io(monkeypatch)
    client = _client()
    _post_analyze(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/narrativa", json={"citta": "Roma", "zona": "Colosseo"}
        ),
    )
    assert resp.status_code == 422


# --- Body validation: the same pre-I/O 422s that ``/analyze`` has ---
# The route rebuilds the context on a cold cache, so an out-of-bound body that
# was not rejected by the validation would cost geocoding and Overpass.


def test_endpoint_rejects_overlong_citta(monkeypatch: pytest.MonkeyPatch) -> None:
    """``citta`` over max_length=100 -> 422, as on ``/analyze``: it is a client
    string that ends up in the cache key and in the Nominatim query (#170)."""
    _patch_io(monkeypatch)
    client = _client()
    context_hash = _post_analyze(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/narrativa",
            json={
                "citta": "A" * 101,
                "zona": "Colosseo",
                "contesto_hash": context_hash,
            },
        ),
    )
    assert resp.status_code == 422


def test_endpoint_rejects_overlong_zona(monkeypatch: pytest.MonkeyPatch) -> None:
    """``zona`` over max_length=200 -> 422 (same bound as ``AnalyzeRequest``)."""
    _patch_io(monkeypatch)
    client = _client()
    context_hash = _post_analyze(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/narrativa",
            json={
                "citta": "Roma",
                "zona": "z" * 201,
                "contesto_hash": context_hash,
            },
        ),
    )
    assert resp.status_code == 422


def test_endpoint_rejects_overlong_domanda(monkeypatch: pytest.MonkeyPatch) -> None:
    """``domanda`` over max_length=500 -> 422 on the ROUTE, not only in the model.

    The bound of ``ZoneNarrativeRequest`` is verified elsewhere on the model, but
    the guarantee that matters (#119) is that the cap holds on the wire: the
    domanda is the only UNTRUSTED input that reaches the prompt, so the refusal
    must arrive at validation -- before the rebuild of the context on a cold cache
    and before spending tokens on an oversized domanda.
    """
    _patch_io(monkeypatch)
    llm = _RecordingLLMClient()
    client = _client(llm=llm)
    context_hash = _post_analyze(client)

    resp = _post_narrative(client, context_hash, question="x" * 501)

    assert resp.status_code == 422
    assert llm.calls == []


def test_endpoint_rejects_overlong_contesto_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``contesto_hash`` over max_length=64 -> 422 before any I/O.

    The fingerprint is a sha256 digest (64 hexadecimal characters): a longer value
    cannot identify any context, and rejecting it at validation avoids that on a
    cold cache the route pays an Overpass capture only to refuse anyway.
    """
    _patch_io(monkeypatch)
    client = _client()
    _post_analyze(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/narrativa",
            json={"citta": "Roma", "zona": "Colosseo", "contesto_hash": "0" * 65},
        ),
    )
    assert resp.status_code == 422


def test_endpoint_rejects_too_short_contesto_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``contesto_hash`` under min_length=64 -> 422, not 409.

    Before, the field declared only a cap and a short fingerprint arrived intact
    up to the comparison with the cache, coming out as "mismatched context": a
    more expensive response than necessary, because on a cold cache the route
    rebuilds the context (an Overpass capture) only to refuse a value that did not
    have the shape of a sha256 digest. With ``min_length=64`` the shape is rejected
    before any I/O; the 409 stays for the case that deserves it, the well-formed
    fingerprint that identifies ANOTHER context.
    """
    _patch_io(monkeypatch)
    client = _client()
    _post_analyze(client)
    resp = _post_narrative(client, "0" * 8)
    assert resp.status_code == 422


def test_endpoint_domanda_reaches_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """#119 after the split (#292): the domanda reaches the user_content from HERE.

    It was phase 1 that carried it to the prompt; now phase 1 does not call the
    model, so the #119 vector lives on this route (and the client must repeat it).
    """
    _patch_io(monkeypatch)
    llm = _RecordingLLMClient()
    client = _client(llm=llm)
    context_hash = _post_analyze(client)

    resp = _post_narrative(client, context_hash, question="Rischi di notte?")

    assert resp.status_code == 200
    assert len(llm.calls) == 1
    _system, user = llm.calls[0]
    assert "Rischi di notte?" in user


def test_endpoint_without_domanda_omits_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``domanda`` the user_content does not carry the dedicated section."""
    _patch_io(monkeypatch)
    llm = _RecordingLLMClient()
    client = _client(llm=llm)
    context_hash = _post_analyze(client)

    assert _post_narrative(client, context_hash).status_code == 200

    _system, user = llm.calls[0]
    assert "DOMANDA UTENTE" not in user


def test_endpoint_llm_down_returns_200_with_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider down -> 200 with ``fallback=True`` and empty narrativa, not a 500:
    the structured data is already on screen from phase 1 and stays valid."""
    _patch_io(monkeypatch)
    client = _client(llm=_RaisingLLMClient())
    context_hash = _post_analyze(client)

    resp = _post_narrative(client, context_hash)

    assert resp.status_code == 200
    assert resp.json()["fallback"] is True
    assert resp.json()["narrativa"] == ""


def _phase_2_user_content(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> str:
    """Runs the two phases with the given ``settings`` and returns the user_content."""
    _patch_io(monkeypatch, dense=True)
    llm = _RecordingLLMClient()
    client = _client(llm=llm, settings=settings)
    context_hash = _post_analyze(client)
    assert _post_narrative(client, context_hash).status_code == 200
    return llm.calls[0][1]


def test_endpoint_propagates_the_request_budget_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#210 after the split: the token cap comes from the config, not from the
    defaults.

    Phase 2 is now the only ``generate_analysis`` call of the product: if the
    route did not propagate ``Settings``, the TPM tuning from env would be silently
    ignored. The module defaults COINCIDE with those of ``Settings``, so only a
    value different from the default makes the difference visible: with a tiny
    budget the context must be truncated.
    """
    user = _phase_2_user_content(monkeypatch, Settings(llm_request_token_budget=1))

    assert "piu' rilevanti su 2" in user


def test_endpoint_propagates_the_max_tokens_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tokens reserved for the OUTPUT also come from ``Settings``: they enter the
    computation of the user_content allowance, so a huge value must tighten the
    context as much as a tiny budget."""
    user = _phase_2_user_content(monkeypatch, Settings(llm_max_tokens=100_000))

    assert "piu' rilevanti su 2" in user


def test_endpoint_response_never_contains_a_danger_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anti-scoring guard extended to the new route (#184)."""
    _patch_io(monkeypatch)
    client = _client()
    context_hash = _post_analyze(client)

    resp = _post_narrative(client, context_hash)

    assert resp.status_code == 200
    payload = resp.text.lower()
    for forbidden in ("punteggio", "score", "livello di rischio", "pericolosit"):
        assert forbidden not in payload


# --- #292: the evaluation prompt and the product prompt must not diverge ---
# The two paths call ``generate_analysis`` from different modules and with token
# caps that come from different places: ``eval/harness`` never passes them
# (module default), the route propagates them from ``Settings``. The parity that
# the thesis numbers presuppose is therefore not a fact about the defaults, but
# the SYMMETRY of the parameters: same caps, same prompt. The tests below prove
# it at the defaults AND off the defaults, show that the prompt really feels the
# off-default caps (otherwise the proof would be vacuous) and that with different
# caps the divergence shows -- that is, that this net would tear, instead of
# staying green.

#: ``(request_token_budget, max_tokens)``: the two caps that shape the prompt.
_Caps = tuple[int, int]

#: The caps that both paths use when nobody passes them: it is the pair
#: ``eval/harness`` runs with and, via ``Settings``, the one of the route with an
#: empty config (the equality between the two is fixed by
#: ``test_the_two_paths_start_from_the_same_caps``).
_DEFAULT_CAPS: _Caps = (DEFAULT_REQUEST_TOKEN_BUDGET, DEFAULT_MAX_TOKENS)

#: Pair OFF the defaults chosen because the prompt feels it: with a tiny budget
#: the user_content allowance goes to zero and the context must be truncated
#: (cf. the tests on propagation from ``Settings``). The realistic case is a
#: ``LLM_REQUEST_TOKEN_BUDGET`` lowered in production to stay under the TPM.
_TIGHT_CAPS: _Caps = (1, 900)


async def _product_prompt(
    question: str | None, caps: _Caps, *, istat: bool = False
) -> tuple[str, str]:
    """Prompt that the PRODUCT sends to the model: phase 1 + ``/analyze/narrativa``.

    Two POIs (``_divergent_poi_source``) because it is the minimum in which the
    order and the truncation of the context matter.
    """
    from crime_risk_analyzer.analyze_narrative import (
        run_analysis_fast,
        run_zone_narrative,
    )

    budget, max_tokens = caps
    zone_context_cache.clear()
    phase_1 = await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=FakeProfiler({"Bank": _BANK}),
        poi_source=_divergent_poi_source,
        geo_source=_geo_source,
        # Same switch of the two phases, as in the route (Settings): since #354 the
        # fingerprint with the switch on covers the ISTAT data version.
        istat_context_enabled=istat,
    )
    spy = _RecordingLLMClient()
    await run_zone_narrative(
        "Roma",
        "Colosseo",
        contesto_hash=phase_1.contesto_hash,
        executor=FakeProfiler({"Bank": _BANK}),
        llm_client=spy,
        domanda=question,
        request_token_budget=budget,
        max_tokens=max_tokens,
        istat_context_enabled=istat,
    )

    assert len(spy.calls) == 1
    return spy.calls[0]


async def _evaluation_prompt(
    question: str | None, caps: _Caps, *, istat: bool = False
) -> tuple[str, str]:
    """Prompt that the EVALUATION measures: ``run_analysis``, the entry point of
    ``eval/harness``.

    The caps are explicit here too: the harness leaves them at the defaults, but
    what we want to prove is the symmetry of the parameter, not its default (which
    has its own test).
    """
    from crime_risk_analyzer.orchestrator import run_analysis

    budget, max_tokens = caps
    spy = _RecordingLLMClient()
    await run_analysis(
        "Roma",
        "Colosseo",
        executor=FakeProfiler({"Bank": _BANK}),
        llm_client=spy,
        poi_source=_divergent_poi_source,
        geo_source=_geo_source,
        domanda=question,
        request_token_budget=budget,
        max_tokens=max_tokens,
        istat_context_enabled=istat,
    )

    assert len(spy.calls) == 1
    return spy.calls[0]


@pytest.mark.parametrize(
    "question", [None, "Rischi di notte?"], ids=["without-question", "with-question"]
)
@pytest.mark.parametrize(
    "caps",
    [
        pytest.param(_DEFAULT_CAPS, id="default-caps"),
        pytest.param(_TIGHT_CAPS, id="tight-caps"),
    ],
)
async def test_product_prompt_identical_to_the_evaluation_one(
    caps: _Caps, question: str | None
) -> None:
    """With the same grounded context AND THE SAME CAPS the two paths send the SAME
    prompt.

    After the split (#292) the product narrativa is born in
    ``run_zone_narrative``, while the grounding/hallucination metrics
    (``eval/harness``) measure the one of ``run_analysis``: two calls to
    ``generate_analysis`` in different modules. Today they coincide byte for byte,
    but nothing enforces it -- and if one day only one of the two changed (a
    parameter, a ``context_format``, a domanda handled differently) the thesis
    numbers would speak about a prompt that the user never receives, silently. This
    test is that net: it does not verify the CONTENT of the prompt (the generation
    layer tests do), only that the two paths stay in agreement.

    The caps are EXPLICIT and equal on both sides, at the defaults and off the
    defaults: so the parity observed is that of the symmetry of the parameters, not
    the lucky coincidence between the module defaults and those of ``Settings``
    (which is a separate fact, and has its own test). With and without ``domanda``
    because the untrusted input enters the user_content only on one branch.
    """
    product = await _product_prompt(question, caps)
    evaluation = await _evaluation_prompt(question, caps)

    assert product == evaluation


@pytest.mark.parametrize("istat", [False, True], ids=["istat-off", "istat-on"])
async def test_product_prompt_identical_to_the_evaluation_one_with_istat(
    istat: bool,
) -> None:
    """#345: the #292 parity holds with the ISTAT data too (the test POIs are in
    Rome)."""
    product = await _product_prompt(None, _DEFAULT_CAPS, istat=istat)
    evaluation = await _evaluation_prompt(None, _DEFAULT_CAPS, istat=istat)
    assert product == evaluation
    assert ("DATI ISTAT" in product[1]) is istat


async def test_tight_caps_really_change_the_prompt() -> None:
    """The parity with non-default caps is not a vacuous proof: the prompt feels those
    values (truncated context), so passing them on one side only would show."""
    default_prompt = await _product_prompt(None, _DEFAULT_CAPS)
    tight = await _product_prompt(None, _TIGHT_CAPS)

    assert tight != default_prompt
    assert "piu' rilevanti su 2" in tight[1]


async def test_prompt_diverges_if_the_two_paths_have_different_caps() -> None:
    """Negative check: with different caps the two prompts diverge and the comparison
    above would go RED.

    It is the case that parity at the defaults alone would not intercept: the route
    propagates ``Settings`` (a ``LLM_REQUEST_TOKEN_BUDGET`` configured in
    production), the harness stays at the module defaults. It serves to show that
    the parity test measures the symmetry of the parameters and not the equality of
    two prompts that would be identical anyway.
    """
    product = await _product_prompt(None, _TIGHT_CAPS)
    evaluation = await _evaluation_prompt(None, _DEFAULT_CAPS)

    assert product != evaluation


def test_the_two_paths_start_from_the_same_caps() -> None:
    """The other half of the guarantee: the starting caps of the two paths coincide.

    The symmetry of the parameters (test above) gives parity only if the values the
    two sides receive are the same, and they are not by construction: the harness
    does not pass them (default of ``run_analysis``), the route propagates
    ``Settings``. Here we fix the chain ``run_zone_narrative`` = ``run_analysis`` =
    ``Settings`` = module default, which a change of just one of the three points
    would silently break (same safeguard as
    ``test_max_tokens_default_is_synced_across_modules``). It uses the field
    DEFAULTS, not a ``Settings()`` instance, so as not to depend on a local
    ``.env``.

    The case in which ``LLM_REQUEST_TOKEN_BUDGET``/``LLM_MAX_TOKENS`` are really
    configured from env stays out of the reach of the tests: there the two prompts
    really diverge, and it is a property of the design (the evaluation runs are
    pinned to the module defaults, not to the config of the machine that launches
    them).
    """
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative
    from crime_risk_analyzer.orchestrator import run_analysis

    product = inspect.signature(run_zone_narrative).parameters
    evaluation = inspect.signature(run_analysis).parameters

    assert (
        product["request_token_budget"].default
        == evaluation["request_token_budget"].default
        == Settings.model_fields["llm_request_token_budget"].default
        == DEFAULT_REQUEST_TOKEN_BUDGET
    )
    assert (
        product["max_tokens"].default
        == evaluation["max_tokens"].default
        == Settings.model_fields["llm_max_tokens"].default
        == DEFAULT_MAX_TOKENS
    )
    assert (
        product["istat_context_enabled"].default
        is evaluation["istat_context_enabled"].default
        is False
    )


# --- Full round in citta + zona mode, with a COLD zone cache ---
#
# The labels of the zone mode are the typed text precisely so that phase 2 can
# rebuild the expired context by redoing ``geocode_zone`` on the received labels.
# Here Nominatim is simulated BELOW (under ``geocode_zone``, at the geolocator
# level), so phase 1 and the rebuild go through the same ``_cache_key`` and the
# same query: if the labels diverged from the typed text, the rebuild would look
# for another area and the route would answer 409.


class _FakeNominatimLocation:
    def __init__(self) -> None:
        self.latitude = 41.8902
        self.longitude = 12.4922
        self.raw: dict[str, object] = {
            "boundingbox": ["41.88", "41.90", "12.48", "12.50"]
        }


class _FakeNominatim:
    """Fake geolocator: records the forward queries, forbids the reverse."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def geocode(self, query: str, **kwargs: object) -> _FakeNominatimLocation:
        self.queries.append(query)
        return _FakeNominatimLocation()

    def reverse(self, query: object, **kwargs: object) -> None:
        raise AssertionError("zone mode must not reverse geocode")


def _patch_nominatim(monkeypatch: pytest.MonkeyPatch) -> _FakeNominatim:
    """Replaces only the geolocator, leaving real everything above it.

    The RateLimiter is bypassed (direct dispatch) so as not to wait for the real
    ``min_delay`` between the two calls; cache, key and bbox parsing stay the real
    ones.
    """
    fake = _FakeNominatim()
    monkeypatch.setattr(geocoding, "_get_geolocator", lambda: fake)
    monkeypatch.setattr(
        geocoding,
        "_get_rate_limited_call",
        lambda: geocoding._nominatim_dispatch,  # pyright: ignore[reportPrivateUsage]
    )
    geocoding._CACHE.clear()  # pyright: ignore[reportPrivateUsage]

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois(citta)

    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)
    return fake


def test_zone_mode_rebuilds_the_same_context_on_a_cold_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/analyze`` with citta+zona, cache emptied, then narrativa and POI: 200, not
    409.

    Between the two phases both the zone cache and the geocoding one are emptied,
    so the rebuild really redoes the Nominatim query: it must be the same as in
    phase 1, and it must lead back to the same POI list.
    """
    nominatim = _patch_nominatim(monkeypatch)
    client = _client()
    zone_context_cache.clear()

    phase1 = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"citta": " Roma ", "zona": "Colosseo"},
        ),
    )
    assert phase1.status_code == 200
    phase1_json = phase1.json()
    assert (phase1_json["citta"], phase1_json["zona_normalizzata"]) == (
        "Roma",
        "Colosseo",
    )

    body = {
        "citta": phase1_json["citta"],
        "zona": phase1_json["zona_normalizzata"],
        "contesto_hash": phase1_json["contesto_hash"],
    }

    zone_context_cache.clear()
    geocoding._CACHE.clear()  # pyright: ignore[reportPrivateUsage]
    narrative_resp = cast(
        httpx.Response,
        client.post("/analyze/narrativa", json=body),  # pyright: ignore[reportUnknownMemberType]
    )
    assert narrative_resp.status_code == 200
    assert narrative_resp.json()["fallback"] is False

    zone_context_cache.clear()
    geocoding._CACHE.clear()  # pyright: ignore[reportPrivateUsage]
    poi = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/poi", json={**body, "poi_id": phase1_json["poi"][0]["id"]}
        ),
    )
    assert poi.status_code == 200

    assert nominatim.queries == ["Colosseo, Roma"] * 3
