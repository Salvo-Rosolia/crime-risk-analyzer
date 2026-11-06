"""Sessions with a source set uploaded by the user (#416).

The set is valid only for the session of whoever uploads it. The session is identified
by an ``X-Session-Id`` header chosen by the client: a random token (for example
``crypto.randomUUID()``) that the client generates once and sends back with every
request. The server does not issue identifiers and does not link them to anything
personal: whoever does not know the token can neither see nor use nor remove the
set of another, which is why the format imposes a minimum length.

The state lives in the process memory (same model as the zone cache and the
geocoding: single-worker deploy, #170). A restart resets the sessions; with several
workers each would have its own. Time is injectable (``clock``) for the tests.

Sliding-window expiry: every use renews the TTL, so whoever is working does not
lose the set mid-analysis. An expired or evicted set does NOT silently fall back to the
default: the next read raises :class:`SourcesExpiredError` (410),
because an analysis on the wrong set, if the user believes they are using their own,
would be a silent error. The "expired" state is PERSISTENT: every read raises
:class:`SourcesExpiredError` (so even two parallel requests, for example
``/analyze`` and ``/analyze/narrativa``, receive the same warning) until the user
chooses: a new valid upload or the return to the default (DELETE).

Memory: the expiry flags are at most ``_MAX_EXPIRED`` (the most recent, LRU by
order of expiry); beyond the cap the oldest is forgotten and that session
falls back to the default without warning. A flag weighs a few bytes (a key), so the
cap is wide compared to the cap of active sessions; no separate TTL is needed.
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from crime_risk_analyzer import zone_context_cache
from crime_risk_analyzer.sources.model import SourceSet
from crime_risk_analyzer.sources.report import Problem

__all__ = [
    "SESSION_HEADER",
    "SessionEntry",
    "SessionStore",
    "SourcesExpiredError",
    "is_valid_session_id",
]

SESSION_HEADER = "X-Session-Id"

#: URL-safe token of 16-128 characters (ASCII): long enough not to be
#: guessable, short enough to fit in a header.
_SESSION_ID = re.compile(r"[A-Za-z0-9_\-]{16,128}")

#: How many expired/evicted sessions to remember for the warning (bounded memory).
_MAX_EXPIRED = 256


def is_valid_session_id(value: str) -> bool:
    """``True`` if ``value`` has the form of a session identifier."""
    return _SESSION_ID.fullmatch(value) is not None


class SourcesExpiredError(Exception):
    """The sources uploaded by the session have expired or have been evicted."""

    def __init__(self) -> None:
        super().__init__(
            "le fonti caricate in questa sessione sono scadute: caricale di nuovo "
            "o torna alle fonti predefinite"
        )


@dataclass
class SessionEntry:
    """Active set of a session, with the warnings of the upload."""

    source_set: SourceSet
    warnings: Sequence[Problem]
    expires_at: float


class SessionStore:
    """In-memory store ``session_id -> set`` with TTL and cap on sessions."""

    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_sessions: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_sessions
        self._clock = clock
        self._entries: dict[str, SessionEntry] = {}
        self._expired: OrderedDict[str, None] = OrderedDict()

    @property
    def ttl_seconds(self) -> float:
        return self._ttl

    def count(self) -> int:
        """Sessions with an active set (including the expired ones not yet pruned)."""
        self._prune()
        return len(self._entries)

    def activate(
        self, session_id: str, source_set: SourceSet, warnings: Sequence[Problem]
    ) -> None:
        """Activates ``source_set`` for the session, replacing the previous one."""
        self._prune()
        self._expired.pop(session_id, None)
        self._entries.pop(session_id, None)
        zone_context_cache.purge_session(session_id)
        while len(self._entries) >= self._max:
            oldest = min(self._entries, key=lambda k: self._entries[k].expires_at)
            self._delete(oldest, remember=True)
        self._entries[session_id] = SessionEntry(
            source_set=source_set,
            warnings=tuple(warnings),
            expires_at=self._clock() + self._ttl,
        )

    def get(self, session_id: str) -> SessionEntry | None:
        """The session's set (renewing the expiry), or ``None`` if there is none.

        Raises:
            SourcesExpiredError: the session had a set, expired or evicted;
                it is raised on every read until there is a new upload or
                a :meth:`reset`.
        """
        self._prune()
        entry = self._entries.get(session_id)
        if entry is not None:
            entry.expires_at = self._clock() + self._ttl
            return entry
        if session_id in self._expired:
            raise SourcesExpiredError
        return None

    def peek(self, session_id: str) -> SessionEntry | None:
        """Like :meth:`get` but without renewing the expiry nor raising the warning."""
        self._prune()
        return self._entries.get(session_id)

    def remaining_seconds(self, session_id: str) -> int | None:
        """Seconds to expiry (without renewing it), ``None`` without an active set."""
        entry = self.peek(session_id)
        if entry is None:
            return None
        return max(0, round(entry.expires_at - self._clock()))

    def was_expired(self, session_id: str) -> bool:
        """``True`` if the set expired and the user has not yet chosen what to do."""
        self._prune()
        return session_id in self._expired

    def reset(self, session_id: str) -> None:
        """Back to the default: removes the set and any expiry warning."""
        self._expired.pop(session_id, None)
        self._delete(session_id, remember=False)

    def _prune(self) -> None:
        now = self._clock()
        for sid in [k for k, e in self._entries.items() if e.expires_at <= now]:
            self._delete(sid, remember=True)

    def _delete(self, session_id: str, *, remember: bool) -> None:
        entry = self._entries.pop(session_id, None)
        if entry is None:
            return
        zone_context_cache.purge_session(session_id)
        if remember:
            self._expired[session_id] = None
            while len(self._expired) > _MAX_EXPIRED:
                self._expired.popitem(last=False)
