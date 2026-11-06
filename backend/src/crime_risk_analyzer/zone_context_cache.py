"""Bounded cache of the already computed zone context (#197).

``/analyze/poi`` needs the POI's neighbourhood, which lives in the zone context.
Rebuilding it on every click would mean one Overpass call per click, against a
free public service whose retry is already insufficient (#232); having the
client send it back would mean letting the prompt be driven by unverified
data. So what ``/analyze`` has just computed is kept.

Same model as the ``_CACHE`` of :mod:`~crime_risk_analyzer.geocoding`: a
module with bounded state, not a service. TTL because OpenStreetMap is a live
source. Time is injectable (``now``) for tests without real waits.
"""

from __future__ import annotations

import time
from typing import TypedDict

from crime_risk_analyzer.rag.grounding import GroundedContext
from crime_risk_analyzer.rag.retrieval import RetrievalContext
from crime_risk_analyzer.sources.context import current_id, current_session_id

__all__ = [
    "MAX_ZONES",
    "TTL_SECONDS",
    "ZoneContext",
    "clear",
    "get",
    "purge",
    "purge_session",
    "put",
]

#: Maximum number of zones kept: beyond it, the oldest is evicted.
MAX_ZONES = 32

#: Validity of an entry, in seconds (30 minutes).
TTL_SECONDS = 1800.0


class ZoneContext(TypedDict):
    """Reusable zone context: output of ``retrieve`` + output of ``ground``."""

    retrieval: RetrievalContext
    grounded: GroundedContext


_STORE: dict[tuple[str, str, str, str], tuple[float, ZoneContext]] = {}


def _key(citta: str, zona: str) -> tuple[str, str, str, str]:
    """Tolerant key: the client sends the zone back as it received it.

    The key is the LABEL, not the area: a circle whose reverse-geocode label
    is ("Roma", "Monti") and the city + zone mode with "Roma"/"Monti"
    typed share the same slot, although they are different areas. Pre-existing
    since #318 (two different circles with the same label already collided). It
    does not produce narratives on a wrong area: phase 2 compares
    ``contesto_hash`` with the fingerprint of the context in the slot, and a
    context overwritten by the other area gives ``ContextMismatchError`` -> 409,
    which invites re-running the analysis.

    The first element is the client session id (#495): the example and default
    sets have a single id shared by all sessions, so the set id alone would let
    one session overwrite or purge another's slot (spurious 409). The second is the
    id of the active source set (#416). Without a session id (no header) the
    session element is empty and requests share the slot, as before.
    """
    return (
        current_session_id(),
        current_id(),
        citta.strip().casefold(),
        zona.strip().casefold(),
    )


def put(citta: str, zona: str, ctx: ZoneContext, *, now: float | None = None) -> None:
    """Stores the context, evicting the oldest entry beyond the cap."""
    stamp = time.monotonic() if now is None else now
    key = _key(citta, zona)
    if len(_STORE) >= MAX_ZONES and key not in _STORE:
        oldest = min(_STORE, key=lambda k: _STORE[k][0])
        _STORE.pop(oldest)
    _STORE[key] = (stamp, ctx)


def get(citta: str, zona: str, *, now: float | None = None) -> ZoneContext | None:
    """The context if present and not expired, otherwise ``None`` (miss)."""
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


def purge(set_id: str) -> None:
    """Removes the entries of a source set (replaced, reset or expired)."""
    for key in [k for k in _STORE if k[1] == set_id]:
        _STORE.pop(key, None)


def purge_session(session_id: str) -> None:
    """Removes the entries of one client session, whatever set they were built on."""
    for key in [k for k in _STORE if k[0] == session_id]:
        _STORE.pop(key, None)


def clear() -> None:
    """Empties the cache: needed by the tests, which share the process.

    It is not hooked to the ``lifespan``: a freshly started process already has
    an empty cache, so there it would have nothing to do.
    """
    _STORE.clear()
