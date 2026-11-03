"""FastAPI application entrypoint.

Exposes the :func:`create_app` factory and an ``app`` instance ready for Uvicorn
(``uvicorn crime_risk_analyzer.main:app``). Registers the domain endpoints —
``GET /health``, ``GET /cities``, ``GET /poi-types`` (#143), ``GET /geocode``
(#318), ``POST /analyze`` + ``POST
/analyze/narrativa`` (the two phases of the zone analysis, #259/#292), ``POST
/analyze/baseline`` and ``POST /analyze/poi`` (#197) — and configures CORS (#106)
and the resource warm-up in the ``lifespan``.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated, cast

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import AfterValidator, BaseModel
from rdflib import Graph

from crime_risk_analyzer import geocoding
from crime_risk_analyzer.analyze_narrative import (
    ZoneNarrativeRequest,
    ZoneNarrativeResponse,
    run_analysis_fast,
    run_zone_narrative,
)
from crime_risk_analyzer.area_search import resolve_circle, resolve_zone
from crime_risk_analyzer.config import Settings, get_settings
from crime_risk_analyzer.errors import register_exception_handlers
from crime_risk_analyzer.istat.data import istat_data, istat_data_or_none
from crime_risk_analyzer.llm.client import LLMClient, get_llm_client
from crime_risk_analyzer.ontology import get_ontology
from crime_risk_analyzer.orchestrator import (
    AnalyzeRequest,
    AnalyzeResponse,
    BaselineRequest,
    Center,
    run_baseline,
)
from crime_risk_analyzer.poi_narrative import (
    PoiNarrativeRequest,
    PoiNarrativeResponse,
    run_poi_narrative,
)
from crime_risk_analyzer.poi_types import PoiType, poi_types, resolve_poi_type
from crime_risk_analyzer.rag.retrieval import GeoSource
from crime_risk_analyzer.sources import routes as sources_routes
from crime_risk_analyzer.sources.context import current_executor
from crime_risk_analyzer.sources.session import SESSION_HEADER
from crime_risk_analyzer.sparql_module.query_executor import (
    RiskQueryExecutor,
    get_executor,
)


class HealthResponse(BaseModel):
    """Response of the health-check endpoint."""

    status: str
    ontology_triples: int


async def _resolve_area(
    request: AnalyzeRequest | BaselineRequest,
) -> tuple[str, str, GeoSource]:
    """Routes the body to the resolver of the mode it carries.

    The two search modes coexist and the body carries exactly one of them
    (invariant guaranteed by the validator of ``_AreaRequest``): here we only pick
    the resolver. Both return ``(citta, zona, geo_source)``, so from here
    downward the pipeline does not know which mode the user used.

    The ``cast`` relies on the validator's invariant, not on a local check:
    ``is_circle`` implies ``center``/``radius_m`` are set, and it is the same
    reason why the text branch can pass ``citta``/``zona`` without
    re-verifying them.
    """
    if request.is_circle:
        center = cast(Center, request.center)
        return await resolve_circle(
            center.lat, center.lon, cast(float, request.radius_m)
        )
    return await resolve_zone(cast(str, request.citta), cast(str, request.zona))


router = APIRouter()

#: Binds the session's source set (#416) to the request, if it has one.
_SESSION = [Depends(sources_routes.activate_session)]


@router.get("/health")
async def health(graph: Annotated[Graph, Depends(get_ontology)]) -> HealthResponse:
    """Health-check: service up + number of triples of the loaded ontology.

    The graph arrives via ``Depends(get_ontology)`` (loaded once in the
    ``lifespan``, no per-request I/O): ``ontology_triples`` signals that the
    ontology is actually in memory (see backend/orchestrator.md).
    """
    return HealthResponse(status="ok", ontology_triples=len(graph))


@router.get("/cities")
async def cities(settings: Annotated[Settings, Depends(get_settings)]) -> list[str]:
    """Lists the suggested cities for the city field autocomplete (not a constraint).

    Roma, Milano and Napoli are guaranteed and tested end-to-end; the others are
    best-effort (see backend/orchestrator.md). The list lives in the centralised
    config and is injected via ``Depends`` (no global state).
    """
    return settings.supported_cities


@router.get(
    "/poi-types",
    dependencies=[Depends(sources_routes.activate_session_readonly)],
)
async def list_poi_types() -> list[PoiType]:
    """Catalogue of the POI types accepted as ``tipo_poi`` (#143).

    The TERMINUS classes that the OSM mapping can produce, with the IT label of
    the controlled vocabulary, sorted by label. It serves the catalogue of the
    session's active set (#463), the same one ``tipo_poi`` is validated against;
    without a header, with a malformed one, without a set or with an expired set it
    serves the default (cached) one. It never answers 410 ``fonti_scadute`` nor 422
    (#438): the list must not break the panel. It reads the session with ``peek``,
    so it neither renews the TTL nor raises the expiry warning, which stays for the
    analysis routes. No network.
    """
    return list(poi_types())


def _non_empty_query(query: str) -> str:
    """Rejects a query without useful characters (#376); the valid one returns intact.

    The criterion is ``str.split()``, the same one with which
    ``geocoding._freeform_key`` compresses the spaces: a query passes only if its
    cache key is not empty. A regex ``pattern`` would not be enough: its
    ``\\s`` does not count the U+001C-U+001F separators, which for ``split`` are
    spaces.
    """
    if not query.split():
        raise ValueError("la query non puo' essere vuota o di soli spazi")
    return query


@router.get("/geocode")
async def geocode(
    query: Annotated[str, Query(max_length=200), AfterValidator(_non_empty_query)],
) -> dict[str, float]:
    """Forward geocode of a free place (#318): it only moves the map, it is not
    part of the analysis.

    It serves the frontend's "go to a place" box: no bbox, no
    zone/city — only a point to re-centre the map, from which the user then
    draws the circle that feeds ``POST /analyze``. ``GeocodingError``
    (service unreachable) is already mapped centrally -> 503 (#21); here
    only the "no result" outcome is handled, which is not a service
    error.

    An empty or whitespace-only query (:func:`_non_empty_query`, #376) is a 422
    validation error, like one over 200 characters, and does not reach
    Nominatim. The valid query passes intact, edge spaces included.
    """
    result = await run_in_threadpool(geocoding.geocode_freeform, query)
    if result is None:
        raise HTTPException(status_code=404, detail="luogo non trovato")
    lat, lon = result
    return {"lat": lat, "lon": lon}


@router.post("/analyze", dependencies=_SESSION)
async def analyze(
    request: AnalyzeRequest,
    executor: Annotated[RiskQueryExecutor, Depends(current_executor)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnalyzeResponse:
    """Phase 1 (#259/#292): area -> OSM -> SPARQL -> grounding -> JSON.

    **No LLM call here.** The route answers with the structured data and
    ``narrativa=None`` — not a fallback (``fallback`` stays ``False``), but
    "text on the way": the client renders map and list right away, then asks for
    the prose from ``POST /analyze/narrativa`` sending back the ``contesto_hash``
    of this response. Before, the map appeared only after the generation, i.e.
    after the whole latency of the provider.

    The body carries the area in ONE of the two modes (:func:`_resolve_area`): the
    circle drawn on the map (#318), from which ``resolve_circle`` derives a
    best-effort city/zone label via reverse geocode (never blocking), or the
    two fields ``citta``/``zona``, which ``resolve_zone`` geocodes into a bbox —
    a zone not found is ``ZoneNotFoundError`` -> 422. No city allowlist
    (#191): ``GET /cities`` suggests, does not constrain. Domain errors
    (Overpass down, etc.) propagate to the central handlers (#21).

    The free ``domanda`` (#119) stays with phase 2, which is the only one
    building a prompt. For the same reason this route depends neither on the LLM
    client nor on the token caps: they are arguments of phase 2. From ``Settings``
    it reads only the ISTAT switch (#346), which decides whether ``poi[].istat``
    reaches the client and whether the ISTAT data version enters
    ``contesto_hash`` (#354).
    """
    citta, zona, geo_source = await _resolve_area(request)
    return await run_analysis_fast(
        citta,
        zona,
        executor=executor,
        geo_source=geo_source,
        radius_m=request.radius_m,
        istat_context_enabled=settings.istat_context_enabled,
    )


@router.post("/analyze/narrativa", dependencies=_SESSION)
async def analyze_narrativa(
    request: ZoneNarrativeRequest,
    executor: Annotated[RiskQueryExecutor, Depends(current_executor)],
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ZoneNarrativeResponse:
    """Phase 2 (#259/#292): the zone narrative, generated separately.

    It reuses the context warmed by phase 1 (cache with TTL); on a cold cache it
    rebuilds it, at the cost of an Overpass call. ``contesto_hash`` (#242) is
    the fingerprint of the context the client is showing: if it does not identify
    the context the endpoint would use -> ``ContextMismatchError`` -> 409
    (central handler in :mod:`errors`, the same registry as ``/analyze/poi``),
    so the prose cannot arise on a POI list different from the one on
    screen — and the rejection arrives before any LLM call, so it costs no
    tokens. ``LLMError`` is handled in :func:`run_zone_narrative` as a
    fallback (200 with empty narrative and ``fallback=True``): the structured data
    is already on screen from phase 1.

    ``request.domanda`` (optional, #119) is propagated down to the prompt's
    ``user_content``. The total token cap of the request and the output
    ``max_tokens`` (#210) come from ``Settings`` (DI): the generation layer
    derives from them the allowance for user_content and limits the POIs passed
    to the LLM on dense zones, so the whole request does not exceed the
    provider's TPM. This is now the only call to ``generate_analysis`` in the
    product, so it is here that the cap must be respected.

    ``citta`` and ``zona`` remain client strings: on a cold cache the
    reconstruction passes them to ``retrieve`` and the zone ends up in the
    ``user_content``, normalised as untrusted data (``build_context_str``),
    as in the per-POI path. The fingerprint does not verify their PROVENANCE:
    it certifies the identity of the POI list, not that the two strings are
    the ones phase 1 returned.
    """
    return await run_zone_narrative(
        request.citta,
        request.zona,
        contesto_hash=request.contesto_hash,
        executor=executor,
        llm_client=llm_client,
        domanda=request.domanda,
        request_token_budget=settings.llm_request_token_budget,
        max_tokens=settings.llm_max_tokens,
        istat_context_enabled=settings.istat_context_enabled,
        istat_scelta_modello=settings.istat_scelta_modello,
    )


@router.post("/analyze/baseline", dependencies=_SESSION)
async def analyze_baseline(
    request: BaselineRequest,
    executor: Annotated[RiskQueryExecutor, Depends(current_executor)],
) -> AnalyzeResponse:
    """No-LLM variant for the ablation: only structured data from the grounding.

    Same two modes as ``/analyze`` (circle or city + zone), via the same
    :func:`_resolve_area`: the two arms of the ablation analyse the same area
    chosen in the same way. No city allowlist (#191).
    ``request.tipo_poi`` (optional, #119) filters the POIs server-side by TERMINUS
    class, applied after the radius filter; ``None``/empty = no filter.
    It arrives from a free text field: :func:`resolve_poi_type` normalises it
    to the canonical class of the ``GET /poi-types`` catalogue (case, spaces and
    IT label indifferent, #143) BEFORE geocoding and Overpass, so an unknown type
    is a 422 (``UnknownPoiTypeError``, central handler) that costs no network
    calls, instead of a silent empty list.
    """
    tipo_poi = resolve_poi_type(request.tipo_poi)
    citta, zona, geo_source = await _resolve_area(request)
    return await run_baseline(
        citta,
        zona,
        executor=executor,
        geo_source=geo_source,
        radius_m=request.radius_m,
        tipo_poi=tipo_poi,
    )


@router.post("/analyze/poi", dependencies=_SESSION)
async def analyze_poi(
    request: PoiNarrativeRequest,
    executor: Annotated[RiskQueryExecutor, Depends(current_executor)],
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PoiNarrativeResponse:
    """Narrative of the single selected POI (#197).

    It reuses the zone context computed by ``/analyze`` (cache with TTL); on a
    cold cache it rebuilds it, at the cost of an Overpass call. ``contesto_hash``
    (#242) is the fingerprint of the context the client is showing: if it does
    not identify the context the endpoint would use -> ``ContextMismatchError``
    -> 409, so the narrative cannot arise on a neighbourhood different from the
    one on screen. ``poi_id`` outside the context -> ``PoiNotFoundError`` -> 404
    (central handler). The RISK data is all re-derived by the server: of the
    point the client supplies only the id and an opaque fingerprint. ``citta`` and
    ``zona`` instead remain client strings: they reach the prompt normalised as
    untrusted data (#119), as in the zone path, but the fingerprint does not
    verify their provenance.
    """
    return await run_poi_narrative(
        request.citta,
        request.zona,
        request.poi_id,
        contesto_hash=request.contesto_hash,
        executor=executor,
        llm_client=llm_client,
        istat_context_enabled=settings.istat_context_enabled,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Startup warm-up (fail-fast): ontology, SPARQL executor and LLM client.

    Pre-builds at startup the expensive or critical resources exposed via
    ``Depends``, so the first ``POST /analyze`` does not pay the lazy cost and a
    misconfig blows up right at startup, not at the first request:

    * :func:`get_ontology` — loads and validates the ``.ttl`` graph (fail-fast if
      missing or invalid);
    * :func:`get_executor` — builds the SPARQL restriction index, an expensive
      and POI-independent part that belongs to startup and not to the first
      request (see the docstring of :class:`RiskQueryExecutor`);
    * :func:`get_llm_client` — instantiates the LLM client from the configured
      provider (fail-fast: ``LLMError`` at startup if the provider key is
      missing, instead of at the first ``/analyze``);
    * :func:`istat_data` — with ``istat_context_enabled``: loads and validates
      the ISTAT data (fail-fast); off, :func:`istat_data_or_none` preloads it
      without failing, because grounding computes the ISTAT rows anyway (R9,
      review 2).
    """
    get_ontology()
    get_executor()
    get_llm_client()
    # ISTAT data (#345): with the switch on, missing or invalid files stop
    # startup instead of silently producing narratives without data. Off, they
    # are loaded here anyway (non-fatal): otherwise the first grounding would
    # load them on the event loop, blocking it for about half a second.
    if get_settings().istat_context_enabled:
        istat_data()
    else:
        istat_data_or_none()
    yield


def create_app() -> FastAPI:
    """Builds and configures the FastAPI instance."""
    settings = get_settings()
    app = FastAPI(title="Crime Risk Analyzer", lifespan=lifespan)
    register_exception_handlers(app)
    # CORS (#106) as DEFENCE IN DEPTH, for a client on an origin different
    # from the API's. Today no frontend call depends on it:
    # ApiService uses relative paths and in development goes through the
    # ``ng serve`` proxy (``frontend/proxy.config.json`` is the only source of
    # what is proxied, #342). For this reason CORS cannot cover a route
    # forgotten in the proxy, and a deploy with the API on another origin
    # would also require a base URL in the frontend. EXPLICIT allowlist from
    # ``Settings`` (never wildcard ``*``); stateless API -> no cookie
    # (``allow_credentials=False``). Covers all routes.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", SESSION_HEADER],
    )
    # GZip (#346, O10): phase 1 of /analyze carries an IstatPoi per POI (+50-55%
    # bytes); no route is streaming (no StreamingResponse/SSE), so compressing
    # the whole body is safe. minimum_size avoids the overhead on tiny
    # responses (e.g. /health).
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.include_router(router)
    app.include_router(sources_routes.router)
    return app


app = create_app()
