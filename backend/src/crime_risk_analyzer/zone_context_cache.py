"""Cache limitata del contesto di zona già calcolato (#197).

``/analyze/poi`` ha bisogno del vicinato del POI, che vive nel contesto di zona.
Ricostruirlo a ogni clic significherebbe una chiamata Overpass per clic, contro
un servizio pubblico gratuito il cui retry e' gia' insufficiente (#232); farlo
rimandare dal client significherebbe far guidare il prompt da dati non
verificati. Quindi si conserva quello che ``/analyze`` ha appena calcolato.

Stesso modello del ``_CACHE`` di :mod:`~crime_risk_analyzer.geocoding`: modulo
con stato limitato, non un servizio. TTL perche' OpenStreetMap e' una sorgente
viva. Il tempo e' iniettabile (``now``) per test senza attese reali.
"""

from __future__ import annotations

import time
from typing import TypedDict

from crime_risk_analyzer.rag.grounding import GroundedContext
from crime_risk_analyzer.rag.retrieval import RetrievalContext

__all__ = ["MAX_ZONES", "TTL_SECONDS", "ZoneContext", "clear", "get", "put"]

#: Numero massimo di zone conservate: oltre, si sfratta la più vecchia.
MAX_ZONES = 32

#: Validità di una voce, in secondi (30 minuti).
TTL_SECONDS = 1800.0


class ZoneContext(TypedDict):
    """Contesto di zona riusabile: output di ``retrieve`` + output di ``ground``."""

    retrieval: RetrievalContext
    grounded: GroundedContext


_STORE: dict[tuple[str, str], tuple[float, ZoneContext]] = {}


def _key(citta: str, zona: str) -> tuple[str, str]:
    """Chiave tollerante: il client rimanda la zona come l'ha ricevuta."""
    return (citta.strip().casefold(), zona.strip().casefold())


def put(citta: str, zona: str, ctx: ZoneContext, *, now: float | None = None) -> None:
    """Memorizza il contesto, sfrattando la voce più vecchia oltre il tetto."""
    stamp = time.monotonic() if now is None else now
    key = _key(citta, zona)
    if len(_STORE) >= MAX_ZONES and key not in _STORE:
        oldest = min(_STORE, key=lambda k: _STORE[k][0])
        _STORE.pop(oldest)
    _STORE[key] = (stamp, ctx)


def get(citta: str, zona: str, *, now: float | None = None) -> ZoneContext | None:
    """Il contesto se presente e non scaduto, altrimenti ``None`` (miss)."""
    stamp = time.monotonic() if now is None else now
    key = _key(citta, zona)
    entry = _STORE.get(key)
    if entry is None:
        return None
    stored_at, ctx = entry
    if stamp - stored_at > TTL_SECONDS:
        _STORE.pop(key, None)
        return None
    return ctx


def clear() -> None:
    """Svuota la cache (usata dai test e dal lifespan)."""
    _STORE.clear()
