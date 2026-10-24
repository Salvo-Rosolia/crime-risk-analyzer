"""API delle fonti caricate dall'utente (#416).

``POST /sources`` carica un set e lo attiva per la sessione, ``POST
/sources/example`` attiva quello d'esempio, ``GET /sources`` ne dice lo stato,
``DELETE /sources`` torna al default, ``GET /sources/templates/{nome}`` scarica i
modelli CSV. La sessione e' quella dell'intestazione ``X-Session-Id`` (vedi
:mod:`~crime_risk_analyzer.sources.session`).

:func:`activate_session` e' la dipendenza che le rotte di analisi aggiungono per
lavorare sul set della sessione: lega il set al contesto della richiesta
(:func:`~crime_risk_analyzer.sources.context.bind`), da cui cache di zona e
impronta del contesto prendono l'id. Chi LEGGE dal set attivo (executor, binding
OSM, ISTAT) sono le rotte di analisi, non questo modulo.
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
from crime_risk_analyzer.sources.build import build_source_set, fallback_luoghi
from crime_risk_analyzer.sources.context import bind
from crime_risk_analyzer.sources.example import example_bundle
from crime_risk_analyzer.sources.limits import (
    MAX_BYTES_CSV,
    MAX_BYTES_GEOJSON,
    MAX_BYTES_ONTOLOGIA,
    MAX_BYTES_RICHIESTA,
    MAX_CAMPI_MULTIPART,
    MAX_FILE_MULTIPART,
    MAX_PARTE_CAMPO,
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

__all__ = ["activate_session", "get_sessions", "router"]

router = APIRouter()

_ID_PATTERN = r"^[A-Za-z0-9_\-]{16,128}$"

#: Intestazione obbligatoria (le rotte ``/sources`` che scrivono) o facoltativa
#: (stato: senza intestazione si e' al default). Il formato e' controllato qui,
#: quindi un valore malformato e' un 422 prima di leggere qualunque file.
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
    """Archivio delle sessioni (singleton di processo, overridabile nei test)."""
    settings = get_settings()
    return SessionStore(
        ttl_seconds=settings.sources_session_ttl_seconds,
        max_sessions=settings.sources_max_sessions,
    )


Sessions = Annotated[SessionStore, Depends(get_sessions)]


class UploadGate:
    """Tetto agli upload/parse contemporanei di ``POST /sources``.

    Fail-fast: se i posti sono finiti si risponde 503 con ``Retry-After`` invece di
    accodare (come per gli altri servizi saturi dell'API, che rispondono 503); una
    coda terrebbe aperte connessioni con file da decine di MB in attesa.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.semaphore = asyncio.Semaphore(limit)


@lru_cache
def get_upload_gate() -> UploadGate:
    """Tetto di upload contemporanei (singleton di processo, come le sessioni)."""
    return UploadGate(get_settings().sources_max_concurrent_uploads)


def _occupato() -> JSONResponse:
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


def _troppo_grande() -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={
            "detail": {
                "errore": "richiesta_troppo_grande",
                "messaggio": (
                    f"il caricamento supera {MAX_BYTES_RICHIESTA // (1024 * 1024)} MB"
                ),
            }
        },
    )


class _UploadRoute(APIRoute):
    """Rotta di upload con i controlli che FastAPI non espone.

    FastAPI legge il multipart con i limiti predefiniti di Starlette (1000 file,
    1000 campi) e nessun tetto al corpo. Qui, PRIMA di leggere il corpo: tetto di
    ``Content-Length`` (413) e posti di upload disponibili (503); poi il multipart
    si legge con i limiti nostri (``request.form`` memorizza il risultato: la
    lettura di FastAPI, subito dopo, riusa questo form). Troppi file o campi, o un
    campo di testo troppo lungo, sono un 400 di Starlette.

    Un corpo senza ``Content-Length`` (chunked) non e' coperto dal tetto totale: lo
    limitano i tetti per file, applicati in lettura, e lo spazio su disco dei file
    temporanei; il reverse proxy di deploy deve imporre il proprio limite.
    """

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        originale = super().get_route_handler()

        async def handler(request: Request) -> Response:
            dichiarata = request.headers.get("content-length", "")
            if dichiarata.isdigit() and int(dichiarata) > MAX_BYTES_RICHIESTA:
                return _troppo_grande()
            gate = get_upload_gate()
            if gate.semaphore.locked():
                return _occupato()
            async with gate.semaphore:
                try:
                    await request.form(
                        max_files=MAX_FILE_MULTIPART,
                        max_fields=MAX_CAMPI_MULTIPART,
                        max_part_size=MAX_PARTE_CAMPO,
                    )
                    return await originale(request)
                finally:
                    await request.close()

        return handler


_upload_router = APIRouter(route_class=_UploadRoute)


async def activate_session(
    sessions: Sessions,
    x_session_id: Annotated[str | None, Header(alias=SESSION_HEADER)] = None,
) -> AsyncGenerator[None]:
    """Lega il set della sessione al contesto della richiesta, se ne ha uno.

    Senza intestazione, con un valore malformato o senza set la richiesta lavora
    sul default (invariato). Se il set della sessione e' scaduto solleva
    :class:`~crime_risk_analyzer.sources.session.SourcesExpiredError` (410): non
    si analizza sul default alle spalle di chi crede di usare le sue fonti.
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


class SetSummary(BaseModel):
    """Che cosa contiene il set attivo (per la schermata di stato)."""

    #: ``example`` per il set d'esempio, ``custom`` per quello caricato: da qui
    #: l'indicatore "Fonti: Esempio" / "Fonti: Personalizzate".
    kind: Literal["example", "custom"]
    classi: int
    selettori_osm: int
    versione_dati: str | None
    luoghi: list[str]
    avvisi: list[Problem]


class SourcesStatus(BaseModel):
    """Stato delle fonti della sessione."""

    stato: Literal["default", "attivo", "scaduto"]
    scade_tra_secondi: int | None
    set: SetSummary | None


def _stato(sessions: SessionStore, session_id: str | None) -> SourcesStatus:
    entry = sessions.peek(session_id) if session_id is not None else None
    if entry is not None and session_id is not None:
        return SourcesStatus(
            stato="attivo",
            scade_tra_secondi=sessions.remaining_seconds(session_id),
            set=_riepilogo(entry),
        )
    if session_id is not None and sessions.was_expired(session_id):
        return SourcesStatus(stato="scaduto", scade_tra_secondi=None, set=None)
    return SourcesStatus(stato="default", scade_tra_secondi=None, set=None)


def _riepilogo(entry: SessionEntry) -> SetSummary:
    s = entry.source_set
    dati = s.istat.dati
    return SetSummary(
        kind="example" if s.kind == "example" else "custom",
        classi=len(s.labels or {}),
        selettori_osm=len(s.osm.osm_to_class),
        versione_dati=s.istat.versione,
        luoghi=[luogo.nome for luogo in dati.luoghi] if dati is not None else [],
        avvisi=list(entry.warnings),
    )


@router.get("/sources")
async def sources_status(
    sessions: Sessions, x_session_id: OptionalSession = None
) -> SourcesStatus:
    """Stato delle fonti: ``default``, ``attivo`` (con riepilogo e scadenza) o
    ``scaduto``. Non rinnova la scadenza."""
    return _stato(sessions, x_session_id)


async def _leggi(upload: UploadFile, limite: int) -> bytes:
    """Legge al piu' ``limite + 1`` byte: oltre il limite il controllo dei file
    segnala il file troppo grande senza che il server lo carichi tutto."""
    return await upload.read(limite + 1)


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
    """Controlla i file e, se sono validi, attiva il set per la sessione.

    Il controllo raccoglie TUTTI i problemi: con errori risponde 422 con il report
    completo (``fonti_non_valide``) e non tocca il set gia' attivo. Namespace e
    nomi delle proprieta' non indicati valgono quelli TERMINUS. Un nuovo
    caricamento sostituisce il precedente e ne svuota la cache di zona.
    """
    vocabolario = OntologyVocabulary(
        namespace=namespace or TERMINUS_VOCABULARY.namespace,
        hazard=hazard or TERMINUS_VOCABULARY.hazard,
        critical_event=critical_event or TERMINUS_VOCABULARY.critical_event,
        performer=performer or TERMINUS_VOCABULARY.performer,
        vulnerability=tuple(vulnerability or TERMINUS_VOCABULARY.vulnerability),
    )
    files = UploadedFiles(
        ontology=await _leggi(ontology, MAX_BYTES_ONTOLOGIA),
        ontology_name=ontology.filename or "",
        osm_table=await _leggi(osm_table, MAX_BYTES_CSV),
        data=await _leggi(data, MAX_BYTES_CSV),
        hazard_table=await _leggi(hazard_table, MAX_BYTES_CSV),
        boundaries=(
            await _leggi(boundaries, MAX_BYTES_GEOJSON)
            if boundaries is not None
            else None
        ),
    )

    def _costruisci() -> tuple[SourceSet, list[Problem]]:
        parsed, report = check_sources(
            files, vocabolario, fallback_luoghi=fallback_luoghi()
        )
        if parsed is None:
            raise SourceValidationError(report)
        return build_source_set(parsed), report.warnings

    source_set, avvisi = await run_in_threadpool(_costruisci)
    sessions.activate(x_session_id, source_set, avvisi)
    return _stato(sessions, x_session_id)


router.include_router(_upload_router)


@router.post("/sources/example")
async def activate_example(
    sessions: Sessions, x_session_id: RequiredSession
) -> SourcesStatus:
    """Attiva il set d'esempio per la sessione, senza caricare file.

    Il set e' costruito una volta sola (alla prima richiesta, in un thread: legge
    e valida i file d'esempio) e condiviso fra le sessioni: e' immutabile. Come
    ``POST /sources`` sostituisce il set gia' attivo.
    """
    source_set, avvisi = await run_in_threadpool(example_bundle)
    sessions.activate(x_session_id, source_set, avvisi)
    return _stato(sessions, x_session_id)


@router.delete("/sources")
async def reset_sources(
    sessions: Sessions, x_session_id: RequiredSession
) -> SourcesStatus:
    """Torna alle fonti predefinite. Idempotente."""
    sessions.reset(x_session_id)
    return _stato(sessions, x_session_id)


@router.get("/sources/templates/{name}")
async def download_template(name: TemplateName) -> Response:
    """Modello CSV scaricabile: intestazione giusta e righe d'esempio."""
    return Response(
        content=template_csv(name),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{template_filename(name)}"'
        },
    )
