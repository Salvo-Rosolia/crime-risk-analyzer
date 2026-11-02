"""Unit tests for the /analyze orchestrator (#18)."""

from __future__ import annotations

import inspect
import logging

import pytest
from pydantic import ValidationError

from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.istat.rows import IstatPoi, IstatRow, Link
from crime_risk_analyzer.llm.client import GROQ_MODEL, LLMError, LLMResponse
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.orchestrator import (
    AnalyzeRequest,
    AnalyzeResponse,
    BaselineRequest,
    Center,
    PoiOut,
    _build_poi_list,  # pyright: ignore[reportPrivateUsage]
    _filter_pois_by_radius,  # pyright: ignore[reportPrivateUsage]
    _filter_pois_by_type,  # pyright: ignore[reportPrivateUsage]
    _generated_response,  # pyright: ignore[reportPrivateUsage]
    _risk_models_from_grounded,  # pyright: ignore[reportPrivateUsage]
    _structured_response,  # pyright: ignore[reportPrivateUsage]
    run_analysis,
    run_baseline,
    run_no_ontology_prompt,
)
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.rag.generation import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_REQUEST_TOKEN_BUDGET,
    SYSTEM_PROMPT,
    USER_INPUT_FENCE_OPEN,
    SourceProse,
    _estimate_tokens,  # pyright: ignore[reportPrivateUsage]
)
from crime_risk_analyzer.rag.grounding import GroundedContext
from crime_risk_analyzer.rag.no_ontology_generation import (
    LLM_SYNTHESIS_BLOCK_HEADER,
    NO_ONTOLOGY_SYSTEM_PROMPT,
)
from crime_risk_analyzer.rag.retrieval import RetrievalContext, RetrievalStats
from tests.eval._doubles import FakeLLMClient as _FakeLLMClient
from tests.eval._doubles import FakeProfiler as _FakeProfiler
from tests.eval._doubles import default_llm_response as _llm_response
from tests.eval._doubles import poi_lines
from tests.istat._factories import BANKROB, istat_poi


def _poi(poi_id: str, name: str, terminus_class: str) -> dict[str, object]:
    return {
        "id": poi_id,
        "name": name,
        "lat": 41.89,
        "lon": 12.49,
        "osm_tags": "amenity=bank",
        "terminus_class": terminus_class,
        "citta": "Roma",
    }


def _vr(
    poi: str, terminus_class: str, hazards: list[str], *, poi_id: str
) -> dict[str, object]:
    """Synthetic validated risk. ``poi_id`` is MANDATORY and keyword-only: with a
    default, a fixture could pair a POI with id ``"1"`` to risks with an empty id
    — the same divergence this story closes — without any test noticing."""
    risks = [
        {
            "hazard": h,
            "tag": "ONTOLOGIA",
            "confidence": "verificato",
            "source": f"{terminus_class} → havingHazard → {h}",
        }
        for h in hazards
    ]
    return {
        "poi": poi,
        "poi_id": poi_id,
        "terminus_class": terminus_class,
        "risks": risks,
        # The three non-hazard axes besides the hazards (#256/#270): empty by
        # default, the tests that check them populate them explicitly.
        "critical_events": [],
        "vulnerabilities": [],
        "stakeholders": [],
        "sparql_path": risks[0]["source"] if risks else None,
    }


class _RaisingLLMClient:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        raise LLMError("provider down")


class _RecordingLLMClient:
    """Spy of the LLM client: records ``(system, user)`` of every call."""

    def __init__(self, response: LLMResponse | None = None) -> None:
        self._response: LLMResponse = response or _llm_response()
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        self.calls.append((system_prompt, user_content))
        return self._response


def _patch_io(monkeypatch: pytest.MonkeyPatch, pois: list[Poi] | None = None) -> None:
    from crime_risk_analyzer.models.geo import Bbox
    from crime_risk_analyzer.rag import retrieval

    resolved_pois: list[Poi] = (
        pois
        if pois is not None
        else [
            {
                "id": "1",
                "name": "Banca A",
                "lat": 41.89,
                "lon": 12.49,
                "osm_tags": "amenity=bank",
                "terminus_class": "Bank",
                "citta": "Roma",
            }
        ]
    )

    geo: dict[str, object] = {
        "lat": 41.89,
        "lon": 12.49,
        "bbox": Bbox(41.88, 12.48, 41.90, 12.50),
    }

    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        return geo

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return resolved_pois

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode)
    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)


async def _geo_source(citta: str, zona: str) -> GeoResult:
    """Geocoding double for the ``_structured_response`` tests with a pending
    narrative (#259): avoids Nominatim, as ``_poi_source`` avoids Overpass."""
    return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))


async def _poi_source(bbox: Bbox, citta: str) -> list[Poi]:
    return [
        {
            "id": "node/1",
            "name": "Colosseo",
            "lat": 41.8902,
            "lon": 12.4922,
            "osm_tags": "historic=monument",
            "terminus_class": "Historical_monument",
            "citta": citta,
        }
    ]


_BANK_PROFILE = PoiRiskProfile(
    terminus_class="Bank",
    hazards=["Bank_robbery"],
    sparql_paths=["Bank → havingHazard → Bank_robbery"],
)

_SCHOOL_PROFILE = PoiRiskProfile(
    terminus_class="School",
    hazards=["Vandalism"],
    sparql_paths=["School → havingHazard → Vandalism"],
)


def test_build_poi_list_confidence_and_path() -> None:
    retrieval_ctx = {
        "pois": [_poi("1", "Banca A", "Bank"), _poi("2", "Bar Roma", "GenericUrbanPOI")]
    }
    grounded = {
        "validated_risks": [
            _vr("Banca A", "Bank", ["Bank_robbery"], poi_id="1"),
            _vr("Bar Roma", "GenericUrbanPOI", [], poi_id="2"),
        ]
    }
    out = _build_poi_list(retrieval_ctx, grounded)  # type: ignore[arg-type]
    assert [p.confidence for p in out] == ["verificato", None]
    assert out[0].sparql_path == "Bank → havingHazard → Bank_robbery"
    assert out[0].id == "1"
    assert out[1].sparql_path is None


def test_build_poi_list_confidence_unified_with_per_risk() -> None:
    # #202/M1: the per-POI confidence is unified with the grounding's per-risk level:
    # named+risks -> verificato; anonymous+risks -> da_confermare;
    # no-risks -> None (POI outside the ontology: no confidence to qualify, #220).
    retrieval_ctx = {
        "pois": [
            _poi("1", "Banca A", "Bank"),
            _poi("2", "", "Bank"),
            _poi("3", "Bar Roma", "GenericUrbanPOI"),
        ]
    }
    grounded = {
        "validated_risks": [
            _vr("Banca A", "Bank", ["Bank_robbery"], poi_id="1"),
            _vr("", "Bank", ["Bank_robbery"], poi_id="2"),
            _vr("Bar Roma", "GenericUrbanPOI", [], poi_id="3"),
        ]
    }
    out = _build_poi_list(retrieval_ctx, grounded)  # type: ignore[arg-type]
    assert [p.confidence for p in out] == ["verificato", "da_confermare", None]


def test_build_poi_list_poi_outside_ontology_confidence_none() -> None:
    # #220: a POI OUTSIDE THE ONTOLOGY (no risks) has no confidence to qualify
    # -> confidence None (the "ipotesi" level was removed). The None marks the
    # absence of risks, not a level of evidential strength.
    retrieval_ctx = {"pois": [_poi("1", "Bar Roma", "GenericUrbanPOI")]}
    grounded = {"validated_risks": [_vr("Bar Roma", "GenericUrbanPOI", [], poi_id="1")]}
    out = _build_poi_list(retrieval_ctx, grounded)  # type: ignore[arg-type]
    assert out[0].confidence is None


def test_build_poi_list_strict_zip_mismatch() -> None:
    with pytest.raises(ValueError):
        _build_poi_list(
            {"pois": [_poi("1", "Banca A", "Bank")]},  # type: ignore[arg-type]
            {"validated_risks": []},  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("in_grounding", "enabled"),
    [(True, True), (True, False), (False, True)],
    ids=["in-grounding-on", "in-grounding-off", "not-in-grounding"],
)
def test_build_poi_list_exposes_istat_only_if_in_grounding_and_enabled(
    in_grounding: bool, enabled: bool
) -> None:
    """#346: the ``IstatPoi`` reaches the contract only if the grounding carries it AND
    the switch is on. Off means off in the interface too (the zone cache always
    carries the ``IstatPoi``: the filter lives here); a grounding without the field
    (test contexts, doubles, POIs outside the polygon) stays ``None`` whatever the
    switch."""
    data = istat_poi(BANKROB)
    vr = _vr("Banca A", "Bank", ["Bank_robbery"], poi_id="1")
    if in_grounding:
        vr["istat"] = data
    out = _build_poi_list(
        {"pois": [_poi("1", "Banca A", "Bank")]},  # type: ignore[arg-type]
        {"validated_risks": [vr]},  # type: ignore[arg-type]
        istat_context_enabled=enabled,
    )
    assert out[0].istat == (data if in_grounding and enabled else None)


def test_build_poi_list_exposes_the_axes_with_labels_and_citation() -> None:
    """The four TERMINUS axes all reach the contract (#256/#270).

    The SPARQL executor has always extracted them on every request, but critical
    events and vulnerabilities were uncovered (#256), and the stakeholder stayed out
    until the controlled vocabulary also covered that category (#270). Each carries
    its own citation and the IT label from the controlled vocabulary, like the hazards.
    """
    retrieval_ctx = {"pois": [_poi("1", "Banca A", "Bank")]}
    vr = _vr("Banca A", "Bank", ["Bank_robbery"], poi_id="1")
    # REAL identifiers, present in the controlled vocabulary (#77): with an invented
    # name ``label_it`` would degrade to de-underscored English and the test would
    # verify the fallback believing it verifies the vocabulary.
    vr["critical_events"] = [
        {"name": "Hostages", "source": "Bank → havingCriticalEvent → Hostages"}
    ]
    vr["vulnerabilities"] = [
        {
            "name": "Poor_surveillance",
            "source": "Bank → isVulnerableTo → Poor_surveillance",
        }
    ]
    vr["stakeholders"] = [{"name": "Mayor", "source": "Bank → havingPerformer → Mayor"}]
    grounded = {"validated_risks": [vr]}

    out = _build_poi_list(retrieval_ctx, grounded)[0]  # type: ignore[arg-type]

    assert [e.name for e in out.critical_events] == ["Hostages"]
    assert out.critical_events[0].source == "Bank → havingCriticalEvent → Hostages"
    assert out.critical_events[0].label_it == "Ostaggi"
    assert out.vulnerabilities[0].label_it == "Sorveglianza insufficiente"
    assert out.stakeholders[0].name == "Mayor"
    assert out.stakeholders[0].source == "Bank → havingPerformer → Mayor"
    assert out.stakeholders[0].label_it == "Sindaco"


def test_build_poi_list_rejects_id_misalignment() -> None:
    """Equal-length lists that are misaligned by identity must fail loudly.

    ``zip(strict=True)`` only checks the LENGTHS: two lists ordered differently
    would pass, and each POI would receive the confidence and ``sparql_path`` of
    another point — the same silent misattribution this story closes, by a
    different route. Now that both lists carry the id, the misalignment is
    detectable.
    """
    with pytest.raises(ValueError):
        _build_poi_list(
            {"pois": [_poi("1", "Banca A", "Bank"), _poi("2", "Scuola", "School")]},  # type: ignore[arg-type]
            {
                "validated_risks": [
                    _vr("Scuola", "School", ["Vandalism"], poi_id="2"),
                    _vr("Banca A", "Bank", ["Bank_robbery"], poi_id="1"),
                ]
            },  # type: ignore[arg-type]
        )


def test_risk_models_from_grounded() -> None:
    grounded = {
        "validated_risks": [
            _vr("Banca A", "Bank", ["Bank_robbery", "Theft"], poi_id="1"),
            _vr("Bar Roma", "GenericUrbanPOI", [], poi_id="2"),
        ]
    }
    models = _risk_models_from_grounded(grounded)  # type: ignore[arg-type]
    assert [(m.poi_id, m.poi) for m in models] == [("1", "Banca A"), ("2", "Bar Roma")]
    assert [r.hazard for r in models[0].risks] == ["Bank_robbery", "Theft"]
    assert models[0].risks[0].tag == "ONTOLOGIA"
    assert models[1].risks == []


def test_risk_models_from_grounded_propagates_source() -> None:
    grounded = {
        "validated_risks": [
            _vr("Banca A", "Bank", ["Bank_robbery"], poi_id="1"),
        ]
    }
    models = _risk_models_from_grounded(grounded)  # type: ignore[arg-type]
    assert models[0].risks[0].source == "Bank → havingHazard → Bank_robbery"


def test_structured_response_no_llm() -> None:
    grounded = {
        "zona": "Centro",
        "validated_risks": [_vr("Banca A", "Bank", ["Bank_robbery"], poi_id="1")],
        "confidence_summary": {"verificato": 1, "da_confermare": 0},
    }
    poi_out = _build_poi_list(
        {"pois": [_poi("1", "Banca A", "Bank")]},  # type: ignore[arg-type]
        grounded,  # type: ignore[arg-type]
    )
    resp = _structured_response(
        "Roma",
        "Centro",
        poi_out,
        grounded,  # type: ignore[arg-type]
        latenza_ms=5,
        fallback=False,
        # The context fingerprint (#242) comes from the caller: here it is a
        # literal, because the test checks the assembly of the response
        # without LLM, not the computation of the fingerprint.
        contesto_hash="h-ctx",
        geo=GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50)),
    )
    assert resp.narrativa == ""
    assert resp.contesto_hash == "h-ctx"
    assert resp.llm_used == ""
    assert resp.cache_hit is False
    assert resp.fallback is False
    assert resp.repro.prompt_hash == ""
    assert resp.risk_models[0].risks[0].hazard == "Bank_robbery"
    assert resp.confidence_summary.verificato == 1
    assert (resp.zona_geo.lat, resp.zona_geo.lon) == (41.89, 12.49)
    assert resp.zona_geo.bbox_min_lat == 41.88
    assert resp.zona_geo.bbox_max_lon == 12.50
    # A POI exists (Banca A): no empty-coverage message.
    assert resp.messaggio is None


async def test_structured_response_narrativa_none_when_pending() -> None:
    """``_structured_response`` with ``narrativa=None`` produces a response with a
    pending narrative (phase 1 of #259): it is not a fallback, ``fallback`` stays
    what the caller passed."""
    from crime_risk_analyzer.rag.grounding import ground
    from crime_risk_analyzer.rag.retrieval import retrieve

    ctx = await retrieve(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    grounded = ground(ctx)
    poi_out = _build_poi_list(ctx, grounded)
    resp = _structured_response(
        "Roma",
        "Colosseo",
        poi_out,
        grounded,
        latenza_ms=0,
        fallback=False,
        contesto_hash="h",
        narrativa=None,
        geo=ctx["geo"],
    )
    assert resp.narrativa is None
    assert resp.fallback is False
    assert resp.zona_geo.lat == ctx["geo"]["lat"]
    assert resp.zona_geo.lon == ctx["geo"]["lon"]
    assert resp.messaggio is None


def test_structured_response_default_narrativa_is_empty_string() -> None:
    """Default unchanged: whoever does not pass ``narrativa`` (``run_baseline``, the
    fallback of ``run_analysis``) keeps receiving ``""``, not ``None`` — no
    regression."""
    # No await needed: we build a minimal GroundedContext by hand,
    # explicitly annotated (an unannotated literal dict would not pass
    # pyright strict as a GroundedContext-typed argument).
    grounded: GroundedContext = {
        "zona": "Colosseo",
        "validated_risks": [],
        "confidence_summary": {},
    }
    resp = _structured_response(
        "Roma",
        "Colosseo",
        [],
        grounded,
        latenza_ms=0,
        fallback=False,
        contesto_hash="h",
        geo=GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50)),
    )
    assert resp.narrativa == ""


def test_structured_response_explicit_messaggio_when_zero_poi() -> None:
    """#260: with an empty ``poi`` the response explicitly states that the zone was
    geocoded but the OSM/TERMINUS coverage found no points — without this, a wrong
    zone and a zone-without-coverage are indistinguishable on screen (in both
    cases the map does not move)."""
    grounded: GroundedContext = {
        "zona": "Colosseo",
        "validated_risks": [],
        "confidence_summary": {},
    }
    resp = _structured_response(
        "Roma",
        "Colosseo",
        [],
        grounded,
        latenza_ms=0,
        fallback=False,
        contesto_hash="h",
        geo=GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50)),
    )
    assert resp.messaggio is not None
    assert "OSM" in resp.messaggio or "TERMINUS" in resp.messaggio


def test_structured_response_explicit_messaggio_with_whitespace_only_narrativa() -> (
    None
):
    """#260 (review finding): a whitespace-only narrative is not real coverage —
    without the strip before the truth check, such a value (falsy only if empty, but
    ``"   "`` is truthy) would suppress the explicit message leaving the user with
    no explanation about an empty zone."""
    grounded: GroundedContext = {
        "zona": "Colosseo",
        "validated_risks": [],
        "confidence_summary": {},
    }
    resp = _structured_response(
        "Roma",
        "Colosseo",
        [],
        grounded,
        latenza_ms=0,
        fallback=False,
        contesto_hash="h",
        geo=GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50)),
        narrativa="   ",
    )
    assert resp.messaggio is not None


async def test_run_analysis_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_FakeLLMClient(_llm_response()),
    )
    assert resp.citta == "Roma"
    assert resp.zona_normalizzata == "Centro"
    assert resp.fallback is False
    assert resp.narrativa is not None
    assert resp.narrativa.startswith("Analisi:")
    assert resp.llm_used == "claude-sonnet-4-6"
    assert [p.confidence for p in resp.poi] == ["verificato"]
    assert resp.latenza_ms >= 0
    assert (resp.zona_geo.lat, resp.zona_geo.lon) == (41.89, 12.49)
    assert resp.messaggio is None


async def test_run_analysis_llm_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_RaisingLLMClient(),
    )
    assert resp.fallback is True
    assert resp.narrativa == ""
    assert resp.llm_used == ""
    assert resp.cache_hit is False
    assert [m.poi for m in resp.risk_models] == ["Banca A"]
    assert resp.risk_models[0].risks[0].hazard == "Bank_robbery"
    assert resp.confidence_summary.verificato == 1


async def test_run_analysis_llm_fallback_logs_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """#210: the fallback on LLMError emits a warning with the exception message.

    Before, the error was swallowed without a trace: a structured warning makes
    future fallbacks diagnosable (why the narrative is empty)."""
    _patch_io(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="crime_risk_analyzer.orchestrator"):
        resp = await run_analysis(
            "Roma",
            "Centro",
            executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
            llm_client=_RaisingLLMClient(),
        )
    assert resp.fallback is True
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "the fallback must emit at least one warning"
    assert any("provider down" in r.getMessage() for r in warnings)


async def test_run_analysis_llm_timeout_triggers_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An LLM provider past the timeout triggers the 200 fallback (no hang/500)."""
    import asyncio

    from crime_risk_analyzer.llm.client import LLMClient

    _patch_io(monkeypatch)

    class _HangingMessages:
        async def create(self, **_kwargs: object) -> object:
            await asyncio.sleep(1)  # past the timeout: it will be cancelled
            raise AssertionError("create should have been cancelled by the timeout")

    class _HangingAnthropic:
        def __init__(self) -> None:
            self.messages = _HangingMessages()

    llm = LLMClient.for_claude(_HangingAnthropic(), timeout=0.01)  # pyright: ignore[reportArgumentType]

    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=llm,
    )

    assert resp.fallback is True
    assert resp.narrativa == ""
    assert resp.tokens_input == 0
    assert [m.poi for m in resp.risk_models] == ["Banca A"]


async def test_run_analysis_anonymous_poi_da_confermare_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#202/m3: an ANONYMOUS POI with ontological risks propagates ``da_confermare`` all
    the way to the AnalyzeResponse. risk_models[].risks[].confidence, confidence_summary
    and poi[].confidence are consistent (no badge-vs-risks divergence, M1)."""
    anon: list[Poi] = [
        {
            "id": "1",
            "name": "",
            "lat": 41.89,
            "lon": 12.49,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": "Roma",
        }
    ]
    _patch_io(monkeypatch, pois=anon)
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_FakeLLMClient(_llm_response()),
    )
    assert resp.risk_models[0].risks[0].confidence == "da_confermare"
    assert resp.confidence_summary.da_confermare == 1
    assert resp.confidence_summary.verificato == 0
    assert [p.confidence for p in resp.poi] == ["da_confermare"]


async def test_risk_models_distinguish_two_anonymous_pois_of_different_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two anonymous OSM features of different class stay attributable to the point.

    Whoever consumes the response attaches the risks to the POI. If the only
    identifier is the ``name``, two nameless POIs collapse onto the first and the
    detail of one shows the risks of the other: OSM names are neither unique nor
    always present, so the ``id`` is the only key that holds.
    """
    anonymous: list[Poi] = [
        {
            "id": "11",
            "name": "",
            "lat": 41.89,
            "lon": 12.49,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": "Roma",
        },
        {
            "id": "22",
            "name": "",
            "lat": 41.90,
            "lon": 12.50,
            "osm_tags": "amenity=school",
            "terminus_class": "School",
            "citta": "Roma",
        },
    ]
    _patch_io(monkeypatch, pois=anonymous)
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE, "School": _SCHOOL_PROFILE}),
        llm_client=_FakeLLMClient(_llm_response()),
    )
    hazards_by_id = {m.poi_id: [r.hazard for r in m.risks] for m in resp.risk_models}
    assert hazards_by_id == {"11": ["Bank_robbery"], "22": ["Vandalism"]}


async def test_run_analysis_zero_pois(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch, pois=[])
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({}),
        llm_client=_FakeLLMClient(_llm_response()),
    )
    assert resp.poi == []
    assert resp.risk_models == []
    assert resp.confidence_summary.verificato == 0
    assert resp.confidence_summary.da_confermare == 0
    assert resp.fallback is False
    # #260: zero POIs but the zone was geocoded regularly — the frontend map
    # can re-centre on ``zona_geo`` instead of staying still.
    assert (resp.zona_geo.lat, resp.zona_geo.lon) == (41.89, 12.49)
    # The FakeLLMClient writes real prose anyway (it does not know the context is
    # empty): that prose is already the information for the reader, so no
    # redundant message (review finding #260).
    assert resp.narrativa
    assert resp.messaggio is None


async def test_run_analysis_zero_pois_llm_fallback_has_explicit_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#260: zero POIs AND the LLM down (empty narrative) — here the explicit message
    is the only information available on why there is nothing to see."""
    _patch_io(monkeypatch, pois=[])
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({}),
        llm_client=_RaisingLLMClient(),
    )
    assert resp.narrativa == ""
    assert resp.messaggio is not None


async def test_run_baseline_no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    resp = await run_baseline(
        "Roma", "Centro", executor=_FakeProfiler({"Bank": _BANK_PROFILE})
    )
    assert resp.fallback is False
    assert resp.narrativa == ""
    assert resp.llm_used == ""
    assert [m.poi for m in resp.risk_models] == ["Banca A"]
    assert resp.risk_models[0].risks[0].hazard == "Bank_robbery"
    assert resp.confidence_summary.verificato == 1
    assert resp.latenza_ms >= 0
    assert (resp.zona_geo.lat, resp.zona_geo.lon) == (41.89, 12.49)
    assert resp.messaggio is None


async def test_run_analysis_exposes_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_FakeLLMClient(_llm_response()),
    )
    assert resp.tokens_input == 10
    assert resp.tokens_output == 20


async def test_run_analysis_fallback_zero_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_io(monkeypatch)
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_RaisingLLMClient(),
    )
    assert resp.tokens_input == 0
    assert resp.tokens_output == 0


async def test_run_analysis_accepts_poi_source(monkeypatch: pytest.MonkeyPatch) -> None:
    from crime_risk_analyzer.models.geo import Bbox
    from crime_risk_analyzer.rag import retrieval

    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        return {"lat": 41.89, "lon": 12.49, "bbox": Bbox(41.88, 12.48, 41.90, 12.50)}

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode)

    async def src(bbox: object, citta: str) -> list[dict[str, object]]:
        return [
            {
                "id": "1",
                "name": "Banca A",
                "lat": 41.89,
                "lon": 12.49,
                "osm_tags": "amenity=bank",
                "terminus_class": "Bank",
                "citta": "Roma",
            }
        ]

    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_FakeLLMClient(_llm_response()),
        poi_source=src,  # type: ignore[arg-type]
    )
    assert [p.name for p in resp.poi] == ["Banca A"]


# --- #119: domanda propagated by run_analysis down to the prompt's user_content ---


async def test_run_analysis_passes_domanda_to_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_io(monkeypatch)
    client = _RecordingLLMClient()
    await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=client,
        domanda="Rischi per i pedoni?",
    )
    assert len(client.calls) == 1
    _system, user = client.calls[0]
    assert "Rischi per i pedoni?" in user
    assert USER_INPUT_FENCE_OPEN in user


async def test_run_analysis_without_domanda_omits_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_io(monkeypatch)
    client = _RecordingLLMClient()
    await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=client,
    )
    _system, user = client.calls[0]
    assert USER_INPUT_FENCE_OPEN not in user


# --- #196: narrativa_fonti exposes the prose per source (additive, display) ---


async def test_run_analysis_populates_narrativa_fonti(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The LLM's block prose is exposed per source in ``narrativa_fonti``
    WITHOUT altering ``narrativa`` (whole string, read by the eval)."""
    _patch_io(monkeypatch)
    narrative = (
        "Sintesi.\n\n"
        "Rischi da ontologia [ONTOLOGIA]\nFurto.\n\n"
        "Rischi dal contesto [CONTESTO]\nBorseggio."
    )
    response = LLMResponse(
        text=narrative,
        llm_used="claude-sonnet-4-6",
        tokens_input=10,
        tokens_output=20,
        cache_hit=False,
        temperature=0.2,
        seed=42,
        prompt_hash="abc123",
    )
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_FakeLLMClient(response),
    )
    assert resp.narrativa == narrative  # unchanged
    assert resp.narrativa_fonti.overview == "Sintesi."
    assert resp.narrativa_fonti.ontologia == "Furto."
    assert resp.narrativa_fonti.contesto == "Borseggio."
    assert resp.narrativa_fonti.speculativo == ""


async def test_run_analysis_llm_fallback_narrativa_fonti_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In the LLM fallback the per-source prose stays empty (default ``SourceProse()``),
    consistent with ``narrativa == ""``."""
    _patch_io(monkeypatch)
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_RaisingLLMClient(),
    )
    assert resp.fallback is True
    assert resp.narrativa == ""
    assert resp.narrativa_fonti == SourceProse()


# --- #318: radius filter shared with the tipo_poi one ---


def _ctx_with_two_pois() -> RetrievalContext:
    near: Poi = {
        "id": "node/1",
        "name": "Vicino",
        "lat": 41.900,
        "lon": 12.500,
        "osm_tags": "amenity=bank",
        "terminus_class": "Bank",
        "citta": "Roma",
    }
    far: Poi = {
        "id": "node/2",
        "name": "Lontano",
        "lat": 42.100,
        "lon": 12.700,
        "osm_tags": "amenity=bank",
        "terminus_class": "Bank",
        "citta": "Roma",
    }
    return RetrievalContext(
        citta="Roma",
        zona="Trastevere",
        geo={"lat": 41.900, "lon": 12.500, "bbox": Bbox(41.8, 12.4, 42.0, 12.6)},
        pois=[near, far],
        profiles={"Bank": PoiRiskProfile(terminus_class="Bank")},
        stats=RetrievalStats(n_pois=2, n_classes=1),
    )


def test_filter_pois_by_radius_excludes_the_far_ones() -> None:
    ctx = _ctx_with_two_pois()
    filtered = _filter_pois_by_radius(ctx, 41.900, 12.500, radius_m=500.0)
    assert [p["id"] for p in filtered["pois"]] == ["node/1"]
    assert filtered["stats"]["n_pois"] == 1


def test_filter_pois_by_type_unchanged_after_sharing() -> None:
    ctx = _ctx_with_two_pois()
    filtered = _filter_pois_by_type(ctx, "Bank")
    assert len(filtered["pois"]) == 2  # both are Bank, none excluded


def test_center_validates_the_bounds() -> None:
    with pytest.raises(ValidationError):
        Center(lat=95.0, lon=12.0)


# --- #119: tipo_poi filters the POIs server-side in the baseline ---


def _two_pois() -> list[Poi]:
    return [
        {
            "id": "1",
            "name": "Banca A",
            "lat": 41.89,
            "lon": 12.49,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": "Roma",
        },
        {
            "id": "2",
            "name": "Bar Roma",
            "lat": 41.90,
            "lon": 12.50,
            "osm_tags": "amenity=bar",
            "terminus_class": "GenericUrbanPOI",
            "citta": "Roma",
        },
    ]


async def test_run_baseline_filters_by_tipo_poi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_io(monkeypatch, pois=_two_pois())
    resp = await run_baseline(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        tipo_poi="Bank",
    )
    # only the POIs of TERMINUS class "Bank": the GenericUrbanPOI is excluded
    assert [p.terminus_class for p in resp.poi] == ["Bank"]
    assert [p.name for p in resp.poi] == ["Banca A"]
    assert [m.poi for m in resp.risk_models] == ["Banca A"]


async def test_run_baseline_no_filter_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_io(monkeypatch, pois=_two_pois())
    resp = await run_baseline(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
    )
    # default (None): no filter, all POIs pass (behaviour unchanged)
    assert [p.terminus_class for p in resp.poi] == ["Bank", "GenericUrbanPOI"]


async def test_run_baseline_blank_tipo_poi_is_no_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_io(monkeypatch, pois=_two_pois())
    resp = await run_baseline(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        tipo_poi="   ",
    )
    # empty/whitespace tipo_poi = no filter (not an empty set of POIs)
    assert [p.terminus_class for p in resp.poi] == ["Bank", "GenericUrbanPOI"]


async def test_run_baseline_tipo_poi_no_match_yields_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_io(monkeypatch, pois=_two_pois())
    resp = await run_baseline(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        tipo_poi="Hospital",
    )
    # no POI of that class -> empty list, no error
    assert resp.poi == []
    assert resp.risk_models == []


# --- #318: radius_m filters the POIs server-side in the baseline ---


def _pois_for_radius() -> list[Poi]:
    return [
        {
            "id": "1",
            "name": "Banca A",
            "lat": 41.89,
            "lon": 12.49,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": "Roma",
        },
        {
            "id": "2",
            "name": "Bar Roma",
            "lat": 41.90,
            "lon": 12.50,
            "osm_tags": "amenity=bar",
            "terminus_class": "GenericUrbanPOI",
            "citta": "Roma",
        },
        {
            "id": "3",
            "name": "Banca Lontana",
            "lat": 42.10,
            "lon": 12.70,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": "Roma",
        },
    ]


async def test_run_baseline_filters_by_radius_m(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``radius_m`` filters the POIs server-side from the geocoded centre (#318).

    The centre geocoded by ``_patch_io`` is (41.89, 12.49), which coincides with
    ``Banca A``: the other two POIs are beyond 500m and are excluded.
    """
    _patch_io(monkeypatch, pois=_pois_for_radius())
    resp = await run_baseline(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        radius_m=500.0,
    )
    assert [p.name for p in resp.poi] == ["Banca A"]


async def test_run_baseline_no_radius_filter_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_io(monkeypatch, pois=_pois_for_radius())
    resp = await run_baseline(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
    )
    # default (None): no radius filter, all POIs pass
    assert [p.name for p in resp.poi] == ["Banca A", "Bar Roma", "Banca Lontana"]


async def test_run_baseline_radius_and_tipo_poi_compose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two server-side filters compose (intersection, #318).

    ``Banca Lontana`` is of class ``Bank`` but out of radius; ``Bar Roma`` is within
    the radius but is not ``Bank``: only ``Banca A`` satisfies both filters.
    """
    _patch_io(monkeypatch, pois=_pois_for_radius())
    resp = await run_baseline(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        radius_m=500.0,
        tipo_poi="Bank",
    )
    assert [p.name for p in resp.poi] == ["Banca A"]


# --- #236: ablation arm «LLM without ontological contribution in the prompt» ---


async def test_run_no_ontology_prompt_hides_the_ontology_from_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model sees the points, not the risks the ontology associates to the classes.

    It is the only variable the arm manipulates: if the hazards ended up in the
    prompt anyway, the comparison with ``analyze`` would isolate nothing.
    """
    _patch_io(monkeypatch)
    client = _RecordingLLMClient()

    await run_no_ontology_prompt(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=client,
    )

    system, user = client.calls[0]
    assert system == NO_ONTOLOGY_SYSTEM_PROMPT
    assert "Bank_robbery" not in user
    assert "Hazard verificati" not in user
    assert "  POI: Banca A (Bank)" in user


def _banks_and_schools(n: int) -> list[Poi]:
    """Alternating POIs: the schools have more risks than the banks, so the
    truncation by relevance does NOT simply keep the first ones of the list."""
    pois: list[Poi] = []
    for i in range(n):
        class_name = "School" if i % 2 else "Bank"
        pois.append(
            {
                "id": str(i),
                "name": f"Punto {i:02d}",
                "lat": 41.89,
                "lon": 12.49,
                "osm_tags": "amenity=x",
                "terminus_class": class_name,
                "citta": "Roma",
            }
        )
    return pois


_SCHOOL_PROFILE_RICH = PoiRiskProfile(
    terminus_class="School",
    hazards=["Vandalism", "School_theft", "Damage_in_the_school"],
    sparql_paths=[
        "School → havingHazard → Vandalism",
        "School → havingHazard → School_theft",
        "School → havingHazard → Damage_in_the_school",
    ],
)


@pytest.mark.parametrize("truncate", [True, False], ids=["truncated", "full"])
async def test_the_two_arms_see_the_same_pois(
    truncate: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#349: the arm without ontology lists the SAME SET of POIs that the full arm
    kept after the truncation by budget, but in the original order and with a note
    on the cut that does not state the criterion.

    Before, it always sent all the points (20 on the evaluation zones) while the
    full one kept about half: the comparison was not at input parity and a
    difference in the metrics could come from the number of POIs, not from the
    ontology. The order by relevance and the words "piu' rilevanti" stay out because
    they come from the ontology (more hazards = more relevant).
    """
    _patch_io(monkeypatch, pois=_banks_and_schools(12))
    profiler = _FakeProfiler({"Bank": _BANK_PROFILE, "School": _SCHOOL_PROFILE_RICH})
    budget = (
        _estimate_tokens(SYSTEM_PROMPT) + DEFAULT_MAX_TOKENS + 900
        if truncate
        else DEFAULT_REQUEST_TOKEN_BUDGET
    )
    full, ablated = _RecordingLLMClient(), _RecordingLLMClient()

    full_resp = await run_analysis(
        "Roma",
        "Centro",
        executor=profiler,
        llm_client=full,
        request_token_budget=budget,
        max_tokens=DEFAULT_MAX_TOKENS,
    )
    resp = await run_no_ontology_prompt(
        "Roma",
        "Centro",
        executor=profiler,
        llm_client=ablated,
        request_token_budget=budget,
        max_tokens=DEFAULT_MAX_TOKENS,
    )

    full_lines = poi_lines(full.calls[0][1])
    ablated_lines = poi_lines(ablated.calls[0][1])
    ablated_user = ablated.calls[0][1]
    # Same SET of points, but in the original order of the retrieval: the order by
    # relevance comes from the ontology (more hazards first) and must not pass.
    assert sorted(ablated_lines) == sorted(full_lines)
    assert ablated_lines == sorted(ablated_lines)  # "Punto 00", "Punto 01", ...
    # Only the prompt changes: the response stays that of all the points.
    assert len(resp.poi) == len(resp.risk_models) == 12
    # The parity is verifiable downstream: both responses carry the ids of the
    # POIs that entered the prompt, in the order of the respective prompt.
    assert full_resp.poi_nel_prompt is not None
    assert resp.poi_nel_prompt is not None
    assert len(resp.poi_nel_prompt) == len(ablated_lines)
    assert set(resp.poi_nel_prompt) == set(full_resp.poi_nel_prompt)
    assert resp.poi_nel_prompt == sorted(resp.poi_nel_prompt, key=int)
    # No "rilevant" in the ablated prompt, with or without the cut (#349).
    assert "rilevant" not in ablated_user.lower()
    if truncate:
        assert 0 < len(full_lines) < 12
        # The full arm chooses by relevance (schools first), not the first N.
        assert full_lines[0].startswith("  POI: Punto 01")
        # The cut keeps schools AND banks: only so can the order by relevance
        # (schools first) be told apart from the original order (alternating).
        assert any("(Bank)" in r for r in full_lines)
        assert ablated_lines != full_lines
        # Neutral note: it says how many points out of how many, not by what criterion.
        note = f"sono analizzati {len(ablated_lines)} POI su 12"
        assert note in ablated_user
        assert len(resp.poi_nel_prompt) < 12
    else:
        assert len(full_lines) == 12
        assert "NB:" not in ablated_user


async def test_run_no_ontology_prompt_keeps_the_structured_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same response as ``run_analysis``: the prompt changes, not the contract.

    ``risk_models``, ``sparql_path`` and ``confidence_summary`` stay ontological
    because they are the anchored data with which ``eval/metrics.py`` builds the
    anchors: if they diverged between the arms, the proxy would measure different
    denominators and the comparison would not be readable.
    """
    _patch_io(monkeypatch)
    resp = await run_no_ontology_prompt(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_FakeLLMClient(_llm_response()),
    )
    reference = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_FakeLLMClient(_llm_response()),
    )

    assert resp.fallback is False
    assert resp.narrativa is not None
    assert resp.narrativa.startswith("Analisi:")
    assert resp.risk_models == reference.risk_models
    assert resp.confidence_summary == reference.confidence_summary
    assert [(p.id, p.confidence, p.sparql_path) for p in resp.poi] == [
        (p.id, p.confidence, p.sparql_path) for p in reference.poi
    ]
    assert resp.contesto_hash == reference.contesto_hash


async def test_run_no_ontology_prompt_splits_prose_on_its_own_block_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-source prose is split on the label that the ablated prompt asks for.

    That prompt makes the model write ``[SINTESI-LLM]`` (#236: the arm consulted no
    ontology and does not claim to). Splitting the narrative on the label of the
    OTHER arm, the measured block would not be recognized and everything would end
    up in ``overview``: a field saying «no attribution» where the model did in fact
    attribute, on the same text that the eval grades correctly. Two divergent
    readings of the same file.
    """
    _patch_io(monkeypatch)
    narrative = (
        "Sintesi.\n\n"
        f"{LLM_SYNTHESIS_BLOCK_HEADER}\nFurto.\n\n"
        "Rischi dal contesto [CONTESTO]\nBorseggio."
    )
    response = LLMResponse(
        text=narrative,
        llm_used=GROQ_MODEL,
        tokens_input=10,
        tokens_output=20,
        cache_hit=False,
        temperature=0.0,
        seed=0,
        prompt_hash="abc123",
    )
    resp = await run_no_ontology_prompt(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_FakeLLMClient(response),
    )
    assert resp.narrativa == narrative  # unchanged, as in the full arm
    assert resp.narrativa_fonti.overview == "Sintesi."
    assert resp.narrativa_fonti.ontologia == "Furto."
    assert resp.narrativa_fonti.contesto == "Borseggio."


def test_generated_response_has_no_default_measured_token() -> None:
    """The measured block's token is declared by the caller, always.

    With a default, a third arm that forgot it would inherit ``[ONTOLOGIA]``:
    ``parse_source_prose`` would not find its label, all the prose would end up in
    ``overview`` and its narrative would be measured as NON-ATTRIBUTION (0.0/1.0)
    without any error — the class of bug that #236 exists to prevent. The type
    prevents it (pyright), this test keeps the default out even from a future
    «convenience».
    """
    param = inspect.signature(_generated_response).parameters["measured_token"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty


async def test_run_no_ontology_prompt_falls_back_on_llm_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same structured fallback branch as the full arm."""
    _patch_io(monkeypatch)
    resp = await run_no_ontology_prompt(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_RaisingLLMClient(),
    )
    assert resp.fallback is True
    assert resp.narrativa == ""
    assert resp.risk_models[0].risks[0].hazard == "Bank_robbery"


async def test_run_no_ontology_prompt_does_not_touch_the_zone_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The experimental arm does not deposit context for ``/analyze/poi``.

    The zone cache serves the user's clicks (a click on a POI must not redo
    Overpass) and is filled by phase 1 of ``/analyze``. This arm is served by no
    route: leaving there a context built for an ablation would be process state
    that nobody asked for.
    """
    from crime_risk_analyzer import zone_context_cache

    _patch_io(monkeypatch)
    zone_context_cache.clear()
    try:
        await run_no_ontology_prompt(
            "Roma",
            "Centro",
            executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
            llm_client=_FakeLLMClient(_llm_response()),
        )
        assert zone_context_cache.get("Roma", "Centro") is None
    finally:
        zone_context_cache.clear()


async def test_run_analysis_does_not_touch_the_zone_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The full evaluation arm too leaves the zone cache alone.

    Since #292 no route calls ``run_analysis``: it is the EVALUATION path
    (``eval/harness``, ``mode='analyze'``), and in the evaluation path nobody reads
    that cache. Depositing the context there was a dead side effect, identical to
    the one the ablation twin deliberately avoids above: process state that nobody
    asked for, and that with a full cache would evict a real user's zone to make
    room for an offline run.
    """
    from crime_risk_analyzer import zone_context_cache

    _patch_io(monkeypatch)
    zone_context_cache.clear()
    try:
        await run_analysis(
            "Roma",
            "Centro",
            executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
            llm_client=_FakeLLMClient(_llm_response()),
        )
        assert zone_context_cache.get("Roma", "Centro") is None
    finally:
        zone_context_cache.clear()


async def test_run_analysis_exposes_the_istat_fields_and_hides_the_raw() -> None:
    from tests.eval._doubles import FakeLLMClient

    class _FakeProfilerRome:
        def profile(self, terminus_class: str) -> PoiRiskProfile:
            return PoiRiskProfile(
                terminus_class="Bank",
                hazards=["Bank_robbery", "Property_theft"],
                sparql_paths=["Bank → havingHazard → Bank_robbery"],
            )

    async def _poi_source_rome(bbox: Bbox, citta: str) -> list[Poi]:
        return [
            {
                "id": "node/1",
                "name": "Banca A",
                "lat": 41.8902,
                "lon": 12.4922,
                "osm_tags": "amenity=bank",
                "terminus_class": "Bank",
                "citta": citta,
            }
        ]

    async def _geo_source_rome(citta: str, zona: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    resp = await run_analysis(
        "Roma",
        "Colosseo",
        executor=_FakeProfilerRome(),
        llm_client=FakeLLMClient(),
        poi_source=_poi_source_rome,
        geo_source=_geo_source_rome,
        istat_context_enabled=True,
    )
    assert resp.istat_attivo is True
    assert resp.narrativa_grezza is not None
    body = resp.model_dump()
    assert "narrativa_grezza" not in body and "controllo_istat" not in body
    # #349: the prompt's POIs are also for the harness only.
    assert resp.poi_nel_prompt is not None
    assert "poi_nel_prompt" not in body


@pytest.mark.parametrize("enabled", [True, False], ids=["istat-on", "istat-off"])
async def test_run_analysis_forwards_the_switch_to_build_poi_list(
    enabled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#346: ``run_analysis`` (synchronous evaluation arm) shares
    ``_build_poi_list`` with phase 1 of the route — without forwarding the switch,
    ``poi[].istat`` would never appear on this path."""
    from crime_risk_analyzer import orchestrator
    from crime_risk_analyzer.rag.grounding import ground as real_ground

    data = istat_poi(BANKROB)

    def _ground_with_istat(ctx: RetrievalContext) -> GroundedContext:
        grounded = real_ground(ctx)
        for vr in grounded["validated_risks"]:
            vr["istat"] = data
        return grounded

    monkeypatch.setattr(orchestrator, "ground", _ground_with_istat)
    out = await run_analysis(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_poi_source,
        geo_source=_geo_source,
        istat_context_enabled=enabled,
    )
    assert (out.poi[0].istat is not None) is enabled


# --- area contract: circle (center/radius_m) OR citta + zona ---


def test_analyze_request_center_and_radius() -> None:
    req = AnalyzeRequest(center=Center(lat=41.9, lon=12.5), radius_m=500.0)
    assert req.is_circle is True
    assert req.center is not None and req.center.lat == 41.9
    assert req.radius_m == 500.0


def test_analyze_request_citta_and_zona() -> None:
    """The second mode is the TWO fields citta + zona, without geometry."""
    req = AnalyzeRequest(citta="Roma", zona="Colosseo")
    assert req.is_circle is False
    assert req.citta == "Roma"
    assert req.zona == "Colosseo"
    assert req.center is None
    assert req.radius_m is None


def test_analyze_request_citta_and_zona_stripped_of_spaces() -> None:
    """Edge spaces do not enter the Nominatim query nor the cache."""
    req = AnalyzeRequest(citta="  Roma ", zona=" Colosseo  ")
    assert req.citta == "Roma"
    assert req.zona == "Colosseo"


def test_analyze_request_two_modes_together_rejected() -> None:
    """Circle and citta/zona together: ambiguous about WHICH area -> rejected."""
    with pytest.raises(ValidationError):
        AnalyzeRequest(
            center=Center(lat=41.9, lon=12.5),
            radius_m=500.0,
            citta="Roma",
            zona="Colosseo",
        )


@pytest.mark.parametrize("empty", ["", "   "])
def test_analyze_request_circle_with_empty_text_fields_is_a_circle(
    empty: str,
) -> None:
    """An empty or whitespace-only text field counts as ABSENT.

    A client that serializes the form with empty boxes is not asking for a second
    mode: the body stays a valid circle.
    """
    req = AnalyzeRequest(
        center=Center(lat=41.9, lon=12.5), radius_m=500.0, citta=empty, zona=empty
    )
    assert req.is_circle is True
    assert req.citta is None
    assert req.zona is None


def test_analyze_request_all_text_fields_empty_without_circle_rejected() -> None:
    """Empty = absent: without a circle no mode is left -> rejected."""
    with pytest.raises(ValidationError):
        AnalyzeRequest(citta="  ", zona="")


def test_analyze_request_circle_and_a_single_text_field_rejected() -> None:
    """Even a single text field next to the circle is a second mode."""
    with pytest.raises(ValidationError):
        AnalyzeRequest(center=Center(lat=41.9, lon=12.5), radius_m=500.0, citta="Roma")


@pytest.mark.parametrize(
    ("citta", "zona"),
    [("Roma", None), (None, "Colosseo"), ("Roma", "   "), ("  ", "Colosseo")],
)
def test_analyze_request_citta_or_zona_missing_rejected(
    citta: str | None, zona: str | None
) -> None:
    """BOTH fields are needed: a zone without a city (or vice versa) is not an area.

    Only one half would end up at Nominatim as an ambiguous query ("Colosseo" in all
    of Italy) or too wide (a whole city): better a 422 than an area different from
    the one the user believes they asked for.
    """
    with pytest.raises(ValidationError):
        AnalyzeRequest(citta=citta, zona=zona)


def test_analyze_request_citta_outside_the_suggestions_accepted() -> None:
    """No allowlist (#191): ``supported_cities`` suggests, does not constrain."""
    citta = "Matera"
    assert citta not in get_settings().supported_cities
    req = AnalyzeRequest(citta=citta, zona="Sassi")
    assert req.citta == citta


def test_analyze_request_citta_too_long_rejected() -> None:
    """max_length=100 on citta: a municipality name fits comfortably (#170)."""
    AnalyzeRequest(citta="x" * 100, zona="Centro")
    with pytest.raises(ValidationError):
        AnalyzeRequest(citta="x" * 101, zona="Centro")


def test_analyze_request_strip_before_the_length_cap() -> None:
    """The cap applies to the STRIPPED value: edge spaces do not count.

    ``"Roma"`` followed by 100 spaces is "Roma"; and a whitespace-only box, however
    long, stays an empty box next to the circle, not a 422.
    """
    req = AnalyzeRequest(citta="Roma" + " " * 100, zona="Colosseo" + " " * 200)
    assert (req.citta, req.zona) == ("Roma", "Colosseo")

    circle = AnalyzeRequest(
        center=Center(lat=41.9, lon=12.5), radius_m=500.0, citta=" " * 101
    )
    assert circle.is_circle is True
    assert circle.citta is None


def test_analyze_request_zona_too_long_rejected() -> None:
    """max_length closes the free-text surface towards Nominatim and _CACHE (#170)."""
    with pytest.raises(ValidationError):
        AnalyzeRequest(citta="Roma", zona="x" * 201)


def test_analyze_request_no_mode_rejected() -> None:
    """There is no default area: an empty body is an error."""
    with pytest.raises(ValidationError):
        AnalyzeRequest()


def test_analyze_request_incomplete_circle_rejected() -> None:
    """The centre alone is not a circle: both fields are needed."""
    with pytest.raises(ValidationError):
        AnalyzeRequest(center=Center(lat=41.9, lon=12.5))


def test_analyze_request_radius_below_the_minimum_rejected() -> None:
    with pytest.raises(ValidationError):
        AnalyzeRequest(center=Center(lat=41.9, lon=12.5), radius_m=1.0)


def test_analyze_request_radius_above_the_maximum_rejected() -> None:
    with pytest.raises(ValidationError):
        AnalyzeRequest(center=Center(lat=41.9, lon=12.5), radius_m=50_000.0)


def test_baseline_request_center_radius_and_tipo_poi() -> None:
    req = BaselineRequest(
        center=Center(lat=41.9, lon=12.5), radius_m=500.0, tipo_poi="Bank"
    )
    assert req.tipo_poi == "Bank"


def test_analyze_request_surface_is_circle_or_citta_zona() -> None:
    """Phase 1 asks WHERE (the area), not what to tell (#292/#318).

    The area arrives in one of the TWO modes that coexist — ``center``+``radius_m``
    (drawn circle) or ``citta``+``zona`` (the two text fields) — and the validator of
    ``_AreaRequest`` requires the body to carry exactly one.

    ``domanda`` stays out: without an LLM call on this route there is no prompt in
    which to inject it, and keeping it in the contract meant declaring an input that
    the server accepted and ignored — the kind of field a client fills in believing
    to get something. It lives in ``ZoneNarrativeRequest``, the request that really
    carries the text to the model. The exact set also keeps out the return of a
    ``tipo_poi``/``score`` by way of the «after all it's optional»."""
    assert set(AnalyzeRequest.model_fields) == {"center", "radius_m", "citta", "zona"}


def test_baseline_request_surface_is_circle_or_citta_zona_tipo_poi() -> None:
    """Guard on the iso-input asymmetry between the two arms (#263).

    ``BaselineRequest`` carries ``tipo_poi`` but not ``domanda``;
    ``ZoneNarrativeRequest`` (phase 2 of the full system, in
    ``analyze_narrative.py``) carries ``domanda`` but not ``tipo_poi``. For a truly
    iso-input ablation comparison the two arms should accept the same
    parameters — today they do not: an accepted and documented asymmetry (#263,
    closed). This test makes the gap verifiable instead of merely described: if
    one day ``domanda`` appears here (or ``tipo_poi`` disappears), it must be
    updated together with the docstrings of
    ``BaselineRequest``/``ZoneNarrativeRequest``."""
    assert set(BaselineRequest.model_fields) == {
        "center",
        "radius_m",
        "citta",
        "zona",
        "tipo_poi",
    }


# --- #184: anti-scoring guard extended to the /analyze response contract ---
# Same exact-set pattern as #118 (test_risk.py::PoiRiskProfile): the set of the
# fields is locked down, so a future numeric danger-scoring field
# (e.g. ``score``/``risk_level``/``livello_rischio``) fails the test and forces
# a conscious review of the legal constraint (_project.md §Vincoli).


def test_analyze_response_has_no_numeric_danger_scoring_field() -> None:
    """``/analyze`` response contract: no numeric danger scoring
    (_project.md §Vincoli). The numeric fields present
    (``latenza_ms``/``tokens_input``/``tokens_output``) measure the cost and
    performance of the run, NOT the magnitude of danger: they are legitimate. A
    rating field added here would break the exact set.

    ``contesto_hash`` (#242) is an opaque IDENTITY digest of the context, not a
    measure: it grades nothing and is not comparable by order.

    ``zona_geo`` (#260) carries the coordinates of the geocoded zone (centre +
    bbox), not a score: it only serves to re-centre the map. ``messaggio``
    is explanatory text, not a quantitative datum."""
    assert set(AnalyzeResponse.model_fields) == {
        "citta",
        "zona_normalizzata",
        "poi",
        "risk_models",
        "narrativa",
        "narrativa_fonti",
        "confidence_summary",
        "llm_used",
        "latenza_ms",
        "tokens_input",
        "tokens_output",
        "repro",
        "cache_hit",
        "fallback",
        "contesto_hash",
        "zona_geo",
        "messaggio",
        "istat_attivo",
        "istat_versione_dati",
        "istat_frasi_scartate",
        "narrativa_grezza",
        "controllo_istat",
        "poi_nel_prompt",
    }


def test_poi_out_has_no_numeric_danger_scoring_field() -> None:
    """The POI of the ``/analyze`` schema carries coordinates (``lat``/``lon``,
    legitimately numeric) and a QUALITATIVE ``confidence`` (evidential strength, not
    danger). The exact set prevents sneaking in a per-POI risk score (e.g.
    ``risk_score``), forbidden by _project.md §Vincoli."""
    assert set(PoiOut.model_fields) == {
        "id",
        "name",
        "terminus_class",
        "lat",
        "lon",
        "confidence",
        "sparql_path",
        "terminus_label_it",
        "terminus_label_en",
        # #256/#270: the TERMINUS axes besides the hazards. They are QUALITATIVE
        # LISTS of anchored entities, no count and no gradation: they do not open
        # the scoring vector this test defends.
        "critical_events",
        "vulnerabilities",
        "stakeholders",
        # #346: ISTAT data already computed in the grounding (rates/counts of the
        # municipality or province, never of the POI), not a score derived from
        # the POI itself.
        # The subtree (IstatPoi/IstatRow/Link) has its own exact-set guard
        # in test_istat_subtree_has_no_numeric_danger_scoring_field.
        "istat",
    }


def test_istat_subtree_has_no_numeric_danger_scoring_field() -> None:
    """Exact set of the fields of ``IstatPoi``/``IstatRow``/``Link`` (#346).

    A derived ``rapporto``/``peso``/score field added to one of these models would
    end up in EVERY ``/analyze`` response (via ``PoiOut.istat``), against D9/O6: the
    weight for the risk ordering stays computed by the FRONTEND from the already
    published rates (O10), never serialized here. Empty ``model_computed_fields``:
    no ``@computed_field`` could bypass the exact set on the declared
    ``model_fields``."""
    assert set(IstatPoi.model_fields) == {"cornice", "righe"}
    assert IstatPoi.model_computed_fields == {}
    assert set(IstatRow.model_fields) == {
        "luogo_codice",
        "luogo_nome",
        "luogo_breve",
        "luogo_tipo",
        "voce",
        "voce_label",
        "anno",
        "anno_confronto",
        "delitti",
        "delitti_confronto",
        "tasso",
        "tasso_sotto_soglia",
        "tasso_italia",
        "tasso_italia_sotto_soglia",
        "variazione_pct",
        "motivo_senza_variazione",
        "rottura_2016",
        "collegamenti",
    }
    assert IstatRow.model_computed_fields == {}
    assert set(Link.model_fields) == {
        "hazard",
        "hazard_label_it",
        "corrispondenza",
    }
    assert Link.model_computed_fields == {}


def test_poi_out_ontology_axes_reject_numeric_value() -> None:
    """Vector beyond the exact set: change of an axis's TYPE into a number.

    The exact set catches the ADDITION of a field, not the replacement of a
    qualitative list with a count — which would be scoring in disguise (#184 had
    recognized the same vector for ``confidence``). Pydantic rejects it: here it is
    pinned, so a future refactor does not open it silently."""
    for axis in ("critical_events", "vulnerabilities", "stakeholders"):
        with pytest.raises(ValidationError):
            PoiOut(
                id="1",
                name="Banca A",
                terminus_class="Bank",
                lat=41.9,
                lon=12.5,
                **{axis: 3},  # pyright: ignore[reportArgumentType]
            )


def test_ontology_item_has_no_numeric_danger_scoring_field() -> None:
    """The entity of a non-hazard axis carries name, citation and labels.

    No numeric field and no level: a ``peso``/``gravita'`` here would be exactly the
    forbidden danger scoring (_project.md §Vincoli), and it is the most likely place
    to sneak it in now that the axes are four."""
    from crime_risk_analyzer.orchestrator import OntologyItem

    assert set(OntologyItem.model_fields) == {
        "name",
        "source",
        "label_it",
        "label_en",
    }


def test_poi_out_confidence_rejects_numeric_value() -> None:
    """#184 vector beyond the exact set (change of TYPE, not addition of a field): the
    POI's ``confidence`` is categorical (Literal). A NUMERIC value is rejected, so it
    cannot become a per-POI risk score in disguise (_project.md §Vincoli): the test
    turns red if the field switched to float."""
    with pytest.raises(ValidationError):
        PoiOut(
            id="1",
            name="Banca A",
            terminus_class="Bank",
            lat=41.89,
            lon=12.49,
            confidence=0.5,  # pyright: ignore[reportArgumentType]
        )
