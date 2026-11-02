"""Central mapping domain error -> HTTP (#21).

Domain exceptions are born in their respective modules (cohesion):
``GeocodingError``/``ZoneNotFoundError`` in :mod:`~crime_risk_analyzer.geocoding`,
``OverpassError`` in :mod:`~crime_risk_analyzer.overpass_client`, ``LLMError`` in
:mod:`~crime_risk_analyzer.llm.client`. Here the **error -> HTTP response map**
is registered in a single place, via ``@app.exception_handler`` (orchestrator.md
§"Gestione errori"): no scattered ``try/except`` in the routers.

Map (orchestrator.md):
  * :class:`ZoneNotFoundError`  -> ``422`` (zone not geocodable)
  * :class:`GeocodingError`     -> ``503`` (geocoding service unreachable)
  * :class:`OverpassError`      -> ``503`` (Overpass unreachable, or a 200
    response with an interruption remark, after retry: #372, can cost ~2x26 s)
  * :class:`PoiNotFoundError`   -> ``404`` (POI outside the current analysis, #197)
  * :class:`ContextMismatchError` -> ``409`` (zone context out of sync, #242)
  * :class:`UnknownPoiTypeError` -> ``422`` (``tipo_poi`` outside the catalogue, #143)
  * :class:`SourceValidationError` -> ``422`` (invalid source files, #416)
  * :class:`SourcesExpiredError` -> ``410`` (session sources expired, #416)

No city allowlist (#191): a non-existent Italian city is not rejected upstream,
but fails at geocoding as :class:`ZoneNotFoundError` (422).

**``LLMError`` is deliberately not mapped here.** On Anthropic 429/5xx the spec
does not foresee a uniform HTTP code but a *decision*: outside the demo the
response is returned without narrative. **No automatic failover to Groq** (the
switch stays manual via ``LLM_PROVIDER`` — _project.md §Stack, spec-root §C1).
That logic lives in the functions that call the model — today
:func:`~crime_risk_analyzer.analyze_narrative.run_zone_narrative` and
:func:`~crime_risk_analyzer.poi_narrative.run_poi_narrative` for the routes, plus
the evaluation paths in :mod:`~crime_risk_analyzer.orchestrator` — which catch
the error and answer ``200`` with ``fallback=True``; an ``LLMError`` that escaped
those branches remains a 500.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from crime_risk_analyzer.geocoding import GeocodingError, ZoneNotFoundError
from crime_risk_analyzer.overpass_client import OverpassError
from crime_risk_analyzer.poi_narrative import ContextMismatchError, PoiNotFoundError
from crime_risk_analyzer.poi_types import UnknownPoiTypeError
from crime_risk_analyzer.sources.report import SourceValidationError
from crime_risk_analyzer.sources.session import SourcesExpiredError


async def _handle_zone_not_found(
    _request: Request, exc: ZoneNotFoundError
) -> JSONResponse:
    """``ZoneNotFoundError`` -> ``422`` (zone not geocodable)."""
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "errore": "zona_non_geocodificabile",
                "messaggio": str(exc),
            }
        },
    )


async def _handle_geocoding_error(
    _request: Request, exc: GeocodingError
) -> JSONResponse:
    """``GeocodingError`` (non-zone) -> ``503`` service unreachable."""
    return JSONResponse(
        status_code=503,
        content={
            "detail": {"errore": "geocoding_non_disponibile", "messaggio": str(exc)}
        },
    )


async def _handle_overpass_error(_request: Request, exc: OverpassError) -> JSONResponse:
    """``OverpassError`` -> ``503`` Overpass unreachable after retry.

    Even a 200 response carrying an interruption remark is retried like a
    timeout and, once the attempts are exhausted, ends up here (#372): in
    interactive mode it costs up to 2 attempts of ~26 s each before the 503.
    """
    return JSONResponse(
        status_code=503,
        content={
            "detail": {"errore": "overpass_non_disponibile", "messaggio": str(exc)}
        },
    )


async def _handle_poi_not_found(
    _request: Request, exc: PoiNotFoundError
) -> JSONResponse:
    """``PoiNotFoundError`` -> ``404`` (POI outside the current analysis, #197).

    It is not a service error but a reference error: the client asked for the
    narrative of a POI that the current zone context does not contain (zone
    re-analysed, POI vanished from OSM). The message says what to do (re-run
    the analysis), so the UI can propose it again to the operator.
    """
    return JSONResponse(
        status_code=404,
        content={"detail": {"errore": "poi_non_nel_contesto", "messaggio": str(exc)}},
    )


async def _handle_context_mismatch(
    _request: Request, exc: ContextMismatchError
) -> JSONResponse:
    """``ContextMismatchError`` -> ``409`` (context out of sync, #242).

    It is not a non-existent reference (404) but a state conflict: the context
    shown to the user and the one available to the server diverge, and the
    operation becomes possible again by repeating the zone analysis. The message
    says what to do, so the UI can propose it again to the operator.
    """
    return JSONResponse(
        status_code=409,
        content={"detail": {"errore": "contesto_disallineato", "messaggio": str(exc)}},
    )


async def _handle_unknown_poi_type(
    _request: Request, exc: UnknownPoiTypeError
) -> JSONResponse:
    """``UnknownPoiTypeError`` -> ``422`` (``tipo_poi`` outside the catalogue, #143).

    Before, an unrecognised type gave an empty list indistinguishable from "no
    POI of that type in the area". The valid catalogue is ``GET /poi-types``.
    """
    return JSONResponse(
        status_code=422,
        content={
            "detail": {"errore": "tipo_poi_non_riconosciuto", "messaggio": str(exc)}
        },
    )


async def _handle_source_validation(
    _request: Request, exc: SourceValidationError
) -> JSONResponse:
    """``SourceValidationError`` -> ``422`` with the full report (#416).

    The report lists ALL the problems (errors and warnings), so whoever uploads
    fixes the files in one go; ``file`` ties each message to its field.
    """
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "errore": "fonti_non_valide",
                "messaggio": "i file caricati non sono validi: correggi e riprova",
                "errors": [p.model_dump() for p in exc.report.errors],
                "warnings": [p.model_dump() for p in exc.report.warnings],
            }
        },
    )


async def _handle_sources_expired(
    _request: Request, exc: SourcesExpiredError
) -> JSONResponse:
    """``SourcesExpiredError`` -> ``410`` (#416).

    The sources uploaded by the session are gone: instead of silently analysing on
    the default, the user is asked to upload them again or return to the default.
    """
    return JSONResponse(
        status_code=410,
        content={"detail": {"errore": "fonti_scadute", "messaggio": str(exc)}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Registers on ``app`` the central domain error -> HTTP map.

    The most specific handlers are registered first: ``ZoneNotFoundError``
    (subclass of ``GeocodingError``) has a dedicated handler at 422, while the
    base ``GeocodingError`` falls on 503. Starlette resolves the handler by exact
    type, walking up the superclasses: having both registered guarantees that the
    zone goes to 422 and the other geocoding errors to 503.

    ``LLMError`` is deliberately not registered (see the module docstring).
    """
    app.add_exception_handler(ZoneNotFoundError, _handle_zone_not_found)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(GeocodingError, _handle_geocoding_error)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(OverpassError, _handle_overpass_error)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(PoiNotFoundError, _handle_poi_not_found)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(ContextMismatchError, _handle_context_mismatch)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(UnknownPoiTypeError, _handle_unknown_poi_type)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(SourceValidationError, _handle_source_validation)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(SourcesExpiredError, _handle_sources_expired)  # pyright: ignore[reportArgumentType]
