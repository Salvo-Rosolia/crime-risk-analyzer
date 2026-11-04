"""API of the sources uploaded by the user (#416).

``POST /sources`` uploads a set and activates it for the session, ``POST
/sources/example`` activates the example one, ``GET /sources`` tells its status,
``DELETE /sources`` returns to the default, ``GET /sources/templates/{nome}`` downloads
the CSV templates. The session is the one of the ``X-Session-Id`` header (see
:mod:`~crime_risk_analyzer.sources.session`).

:func:`activate_session` is the dependency that the analysis routes add in order to
work on the session's set: it binds the set to the request context
(:func:`~crime_risk_analyzer.sources.context.bind`), from which the zone cache and
the context fingerprint take the id. Whoever READS from the active set (executor, OSM
binding, ISTAT) are the analysis routes, not this module.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable, Coroutine
from functools import lru_cache
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel

from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.sources.build import build_source_set, fallback_places
from crime_risk_analyzer.sources.context import bind
from crime_risk_analyzer.sources.example import example_bundle
from crime_risk_analyzer.sources.limits import (
    MAX_BYTES_CSV,
    MAX_BYTES_GEOJSON,
    MAX_BYTES_ONTOLOGY,
    MAX_BYTES_REQUEST,
    MAX_FIELD_PART_BYTES,
    MAX_MULTIPART_FIELDS,
    MAX_MULTIPART_FILES,
)
from crime_risk_analyzer.sources.model import SourceSet
from crime_risk_analyzer.sources.parsing import UploadedFiles, check_sources
from crime_risk_analyzer.sources.report import Problem, SourceValidationError
from crime_risk_analyzer.sources.session import (
    SESSION_HEADER,
    SessionEntry,
    SessionStore,
    is_valid_session_id,
)
from crime_risk_analyzer.sources.templates import (
    TemplateName,
    template_csv,
    template_filename,
)
from crime_risk_analyzer.sources.vocabulary import (
    TERMINUS_VOCABULARY,
    OntologyVocabulary,
)

__all__ = ["activate_session", "get_sessions", "router", "session_scoped_response"]

router = APIRouter()

_ID_PATTERN = r"^[A-Za-z0-9_\-]{16,128}$"

#: Mandatory header (the ``/sources`` routes that write) or optional
#: (status: without a header we are at the default). The format is checked here,
#: so a malformed value is a 422 before reading any file.
RequiredSession = Annotated[
    str,
    Header(
        alias=SESSION_HEADER,
        pattern=_ID_PATTERN,
        description="Token di sessione scelto dal client (16-128 caratteri).",
    ),
]
OptionalSession = Annotated[
    str | None,
    Header(alias=SESSION_HEADER, pattern=_ID_PATTERN),
]


@lru_cache
def get_sessions() -> SessionStore:
    """Session store (process singleton, overridable in the tests)."""
    settings = get_settings()
    return SessionStore(
        ttl_seconds=settings.sources_session_ttl_seconds,
        max_sessions=settings.sources_max_sessions,
    )


Sessions = Annotated[SessionStore, Depends(get_sessions)]


class UploadGate:
    """Cap on the concurrent uploads/parses of ``POST /sources``.

    Fail-fast: if the seats are over, answer 503 with ``Retry-After`` instead of
    queueing (like for the other saturated services of the API, which answer 503); a
    queue would keep open connections with files of tens of MB waiting.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.semaphore = asyncio.Semaphore(limit)


@lru_cache
def get_upload_gate() -> UploadGate:
    """Cap on concurrent uploads (process singleton, like the sessions)."""
    return UploadGate(get_settings().sources_max_concurrent_uploads)


def _occupied() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "5"},
        content={
            "detail": {
                "errore": "caricamento_occupato",
                "messaggio": "ci sono troppi caricamenti in corso: riprova tra poco",
            }
        },
    )


def _too_large() -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={
            "detail": {
                "errore": "richiesta_troppo_grande",
                "messaggio": (
                    f"il caricamento supera {MAX_BYTES_REQUEST // (1024 * 1024)} MB"
                ),
            }
        },
    )


class _UploadRoute(APIRoute):
    """Upload route with the checks that FastAPI does not expose.

    FastAPI reads the multipart with Starlette's default limits (1000 files,
    1000 fields) and no cap on the body. Here, BEFORE reading the body: cap on
    ``Content-Length`` (413) and available upload seats (503); then the multipart
    is read with our own limits (``request.form`` stores the result: FastAPI's
    reading, right after, reuses this form). Too many files or fields, or a
    text field too long, are a Starlette 400.

    A body without ``Content-Length`` (chunked) is not covered by the total cap: it is
    limited by the per-file caps, applied while reading, and by the disk space of the
    temporary files; the deploy reverse proxy must impose its own limit.
    """

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > MAX_BYTES_REQUEST:
                return _too_large()
            gate = get_upload_gate()
            if gate.semaphore.locked():
                return _occupied()
            async with gate.semaphore:
                try:
                    await request.form(
                        max_files=MAX_MULTIPART_FILES,
                        max_fields=MAX_MULTIPART_FIELDS,
                        max_part_size=MAX_FIELD_PART_BYTES,
                    )
                    return await original(request)
                finally:
                    await request.close()

        return handler


_upload_router = APIRouter(route_class=_UploadRoute)


async def activate_session(
    sessions: Sessions,
    x_session_id: Annotated[str | None, Header(alias=SESSION_HEADER)] = None,
) -> AsyncGenerator[None]:
    """Binds the session's set to the request context, if it has one.

    Without a header, with a malformed value or without a set the request works
    on the default (unchanged). If the session's set has expired it raises
    :class:`~crime_risk_analyzer.sources.session.SourcesExpiredError` (410): we do not
    analyse on the default behind the back of whoever believes they are using their
    sources.
    """
    entry = (
        sessions.get(x_session_id)
        if x_session_id is not None and is_valid_session_id(x_session_id)
        else None
    )
    if entry is None:
        yield
        return
    with bind(entry.source_set):
        yield


async def activate_session_readonly(
    sessions: Sessions,
    x_session_id: Annotated[str | None, Header(alias=SESSION_HEADER)] = None,
) -> AsyncGenerator[None]:
    """Like :func:`activate_session`, for routes that only read the active set.

    It reads the session with ``peek``: it neither renews the TTL nor raises the
    expiry warning, and an expired set is not an error (410) but the default.
    """
    entry = (
        sessions.peek(x_session_id)
        if x_session_id is not None and is_valid_session_id(x_session_id)
        else None
    )
    if entry is None:
        yield
        return
    with bind(entry.source_set):
        yield


async def session_scoped_response(response: Response) -> None:
    """Marks a response whose body depends on ``X-Session-Id`` as per-session (#469).

    ``Vary`` makes shared caches key on the header and ``Cache-Control: private``
    keeps them from storing it at all, so one session never receives another's body.
    """
    response.headers["Vary"] = SESSION_HEADER
    response.headers["Cache-Control"] = "private"


class SetSummary(BaseModel):
    """What the active set contains (for the status screen)."""

    #: ``example`` for the example set, ``custom`` for the uploaded one: from here
    #: the "Fonti: Esempio" / "Fonti: Personalizzate" indicator.
    kind: Literal["example", "custom"]
    classi: int
    selettori_osm: int
    versione_dati: str | None
    luoghi: list[str]
    avvisi: list[Problem]


class SourcesStatus(BaseModel):
    """Status of the session sources."""

    stato: Literal["default", "attivo", "scaduto"]
    scade_tra_secondi: int | None
    set: SetSummary | None


def _status(sessions: SessionStore, session_id: str | None) -> SourcesStatus:
    entry = sessions.peek(session_id) if session_id is not None else None
    if entry is not None and session_id is not None:
        return SourcesStatus(
            stato="attivo",
            scade_tra_secondi=sessions.remaining_seconds(session_id),
            set=_summary(entry),
        )
    if session_id is not None and sessions.was_expired(session_id):
        return SourcesStatus(stato="scaduto", scade_tra_secondi=None, set=None)
    return SourcesStatus(stato="default", scade_tra_secondi=None, set=None)


def _summary(entry: SessionEntry) -> SetSummary:
    s = entry.source_set
    dati = s.istat.dati
    return SetSummary(
        kind="example" if s.kind == "example" else "custom",
        classi=len(s.labels or {}),
        selettori_osm=len(s.osm.osm_to_class),
        versione_dati=s.istat.versione,
        luoghi=[place.nome for place in dati.luoghi] if dati is not None else [],
        avvisi=list(entry.warnings),
    )


@router.get("/sources", dependencies=[Depends(session_scoped_response)])
async def sources_status(
    sessions: Sessions, x_session_id: OptionalSession = None
) -> SourcesStatus:
    """Status of the sources: ``default``, ``attivo`` (with summary and expiry) or
    ``scaduto``. It does not renew the expiry."""
    return _status(sessions, x_session_id)


async def _read(upload: UploadFile, limit: int) -> bytes:
    """Reads at most ``limit + 1`` bytes: beyond the limit the file check
    reports the file as too large without the server loading all of it."""
    return await upload.read(limit + 1)


@_upload_router.post("/sources")
async def upload_sources(
    sessions: Sessions,
    x_session_id: RequiredSession,
    ontology: Annotated[UploadFile, File(description="Turtle o OWL/RDF-XML")],
    osm_table: Annotated[UploadFile, File(description="CSV osm_tag,classe")],
    data: Annotated[UploadFile, File(description="CSV dei dati statistici")],
    hazard_table: Annotated[UploadFile, File(description="CSV hazard -> voce")],
    boundaries: Annotated[
        UploadFile | None, File(description="GeoJSON dei confini (facoltativo)")
    ] = None,
    namespace: Annotated[str | None, Form()] = None,
    hazard: Annotated[str | None, Form()] = None,
    critical_event: Annotated[str | None, Form()] = None,
    performer: Annotated[str | None, Form()] = None,
    vulnerability: Annotated[list[str] | None, Form()] = None,
) -> SourcesStatus:
    """Checks the files and, if they are valid, activates the set for the session.

    The check collects ALL the problems: with errors it answers 422 with the complete
    report (``fonti_non_valide``) and does not touch the already active set. Namespace
    and property names not indicated default to the TERMINUS ones. A new
    upload replaces the previous one and empties its zone cache.
    """
    vocabulary = OntologyVocabulary(
        namespace=namespace or TERMINUS_VOCABULARY.namespace,
        hazard=hazard or TERMINUS_VOCABULARY.hazard,
        critical_event=critical_event or TERMINUS_VOCABULARY.critical_event,
        performer=performer or TERMINUS_VOCABULARY.performer,
        vulnerability=tuple(vulnerability or TERMINUS_VOCABULARY.vulnerability),
    )
    files = UploadedFiles(
        ontology=await _read(ontology, MAX_BYTES_ONTOLOGY),
        ontology_name=ontology.filename or "",
        osm_table=await _read(osm_table, MAX_BYTES_CSV),
        data=await _read(data, MAX_BYTES_CSV),
        hazard_table=await _read(hazard_table, MAX_BYTES_CSV),
        boundaries=(
            await _read(boundaries, MAX_BYTES_GEOJSON)
            if boundaries is not None
            else None
        ),
    )

    def _construct() -> tuple[SourceSet, list[Problem]]:
        parsed, report = check_sources(
            files, vocabulary, fallback_places=fallback_places()
        )
        if parsed is None:
            raise SourceValidationError(report)
        return build_source_set(parsed), report.warnings

    source_set, warnings = await run_in_threadpool(_construct)
    sessions.activate(x_session_id, source_set, warnings)
    return _status(sessions, x_session_id)


router.include_router(_upload_router)


@router.post("/sources/example")
async def activate_example(
    sessions: Sessions, x_session_id: RequiredSession
) -> SourcesStatus:
    """Activates the example set for the session, without uploading files.

    The set is built only once (at the first request, in a thread: it reads
    and validates the example files) and shared among the sessions: it is immutable.
    Like ``POST /sources`` it replaces the already active set.
    """
    source_set, warnings = await run_in_threadpool(example_bundle)
    sessions.activate(x_session_id, source_set, warnings)
    return _status(sessions, x_session_id)


@router.delete("/sources")
async def reset_sources(
    sessions: Sessions, x_session_id: RequiredSession
) -> SourcesStatus:
    """Back to the default sources. Idempotent."""
    sessions.reset(x_session_id)
    return _status(sessions, x_session_id)


@router.get("/sources/templates/{name}")
async def download_template(name: TemplateName) -> Response:
    """Downloadable CSV template: the right header and example rows."""
    return Response(
        content=template_csv(name),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{template_filename(name)}"'
        },
    )
