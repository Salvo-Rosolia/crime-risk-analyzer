"""Errori di dominio e mappatura centrale errore -> HTTP (#21).

Le eccezioni di dominio nascono nei rispettivi moduli (coesione):
``GeocodingError``/``ZoneNotFoundError`` in :mod:`~crime_risk_analyzer.geocoding`,
``OverpassError`` in :mod:`~crime_risk_analyzer.overpass_client`, ``LLMError`` in
:mod:`~crime_risk_analyzer.llm.client`. Qui si aggiunge solo l'errore mancante
(:class:`CityNotFoundError`) e si registra la **mappa errore -> risposta HTTP**
in un punto unico, via ``@app.exception_handler`` (orchestrator.md §"Gestione
errori"): niente ``try/except`` sparsi nei router.

Mappa (orchestrator.md):
  * :class:`ZoneNotFoundError`  -> ``422`` (zona non geocodificabile)
  * :class:`CityNotFoundError`  -> ``400`` + citta' supportate
  * :class:`GeocodingError`     -> ``503`` (servizio di geocoding non raggiungibile)
  * :class:`OverpassError`      -> ``503`` (Overpass non raggiungibile dopo retry)

**``LLMError`` non e' mappato qui di proposito.** In caso di Anthropic 429/5xx la
spec non prevede un codice HTTP uniforme ma una *decisione*: fuori demo si
ritornano solo i dati strutturati senza narrativa. **Nessun failover automatico
su Groq** (lo switch resta manuale via ``LLM_PROVIDER`` — _project.md §Stack,
spec-root §C1). Quella logica vive nell'orchestrator ``/analyze`` (#18), non
qui; finche' non esiste, un ``LLMError`` non gestito resta un 500.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from crime_risk_analyzer.geocoding import GeocodingError, ZoneNotFoundError
from crime_risk_analyzer.overpass_client import OverpassError


class CityNotFoundError(RuntimeError):
    """La citta' richiesta non e' tra quelle supportate/risolvibili in OSM.

    Porta con se' l'elenco delle citta' supportate, cosi' l'handler puo'
    suggerirle nel body della risposta ``400`` senza dipendere dalla config.
    """

    def __init__(self, city: str, *, supported: list[str] | None = None) -> None:
        self.city = city
        self.supported: list[str] = list(supported) if supported is not None else []
        super().__init__(f"Citta' non supportata: {city!r}")


async def _handle_zone_not_found(
    _request: Request, exc: ZoneNotFoundError
) -> JSONResponse:
    """``ZoneNotFoundError`` -> ``422`` (zona non geocodificabile)."""
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "errore": "zona_non_geocodificabile",
                "messaggio": str(exc),
            }
        },
    )


async def _handle_city_not_found(
    _request: Request, exc: CityNotFoundError
) -> JSONResponse:
    """``CityNotFoundError`` -> ``400`` con l'elenco delle citta' supportate."""
    return JSONResponse(
        status_code=400,
        content={
            "detail": {
                "errore": "citta_non_supportata",
                "messaggio": str(exc),
                "citta_supportate": exc.supported,
            }
        },
    )


async def _handle_geocoding_error(
    _request: Request, exc: GeocodingError
) -> JSONResponse:
    """``GeocodingError`` (non-zona) -> ``503`` servizio non raggiungibile."""
    return JSONResponse(
        status_code=503,
        content={
            "detail": {"errore": "geocoding_non_disponibile", "messaggio": str(exc)}
        },
    )


async def _handle_overpass_error(_request: Request, exc: OverpassError) -> JSONResponse:
    """``OverpassError`` -> ``503`` Overpass non raggiungibile dopo retry."""
    return JSONResponse(
        status_code=503,
        content={
            "detail": {"errore": "overpass_non_disponibile", "messaggio": str(exc)}
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Registra sull'``app`` la mappa centrale errore di dominio -> HTTP.

    Gli handler piu' specifici sono registrati prima: ``ZoneNotFoundError``
    (sottoclasse di ``GeocodingError``) ha un handler dedicato a 422, mentre il
    ``GeocodingError`` base cade su 503. Starlette risolve l'handler per tipo
    esatto, risalendo le superclassi: avere entrambi registrati garantisce che la
    zona vada a 422 e gli altri errori di geocoding a 503.

    ``LLMError`` non e' registrato di proposito (vedi docstring del modulo).
    """
    app.add_exception_handler(ZoneNotFoundError, _handle_zone_not_found)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(GeocodingError, _handle_geocoding_error)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(CityNotFoundError, _handle_city_not_found)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(OverpassError, _handle_overpass_error)  # pyright: ignore[reportArgumentType]
