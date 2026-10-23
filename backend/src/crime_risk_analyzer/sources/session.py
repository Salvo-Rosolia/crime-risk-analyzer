"""Sessioni con un set di fonti caricato dall'utente (#416).

Il set vale solo per la sessione di chi lo carica. La sessione e' identificata da
un'intestazione ``X-Session-Id`` scelta dal client: un token casuale (per esempio
``crypto.randomUUID()``) che il client genera una volta e rimanda a ogni
richiesta. Il server non emette identificativi e non li lega a nulla di
personale: chi non conosce il token non puo' ne' vedere ne' usare ne' togliere il
set di un altro, per questo il formato impone una lunghezza minima.

Lo stato vive in memoria del processo (stesso modello della cache di zona e del
geocoding: deploy single-worker, #170). Un riavvio azzera le sessioni; con piu'
worker ognuno avrebbe le sue. Il tempo e' iniettabile (``clock``) per i test.

Scadenza a finestra mobile: ogni uso rinnova il TTL, cosi' chi sta lavorando non
perde il set a meta' analisi. Un set scaduto o sfrattato NON ricade in silenzio sul
default: la prima lettura successiva solleva :class:`SourcesExpiredError` (410),
perche' un'analisi sul set sbagliato, se l'utente crede di usare il suo, sarebbe
un errore silenzioso. Lo stato "scaduto" e' PERSISTENTE: ogni lettura solleva
:class:`SourcesExpiredError` (cosi' anche due richieste parallele, per esempio
``/analyze`` e ``/analyze/narrativa``, ricevono lo stesso avviso) finche' l'utente
non sceglie: un nuovo caricamento valido o il ritorno al default (DELETE).

Memoria: i flag di scadenza sono al piu' ``_MAX_SCADUTE`` (i piu' recenti, LRU per
ordine di scadenza); oltre il tetto il piu' vecchio e' dimenticato e quella sessione
ricade sul default senza avviso. Un flag pesa pochi byte (una chiave), quindi il
tetto e' largo rispetto al tetto di sessioni attive; non serve un TTL a parte.
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

#: Token url-safe di 16-128 caratteri (ASCII): abbastanza lungo da non essere
#: indovinabile, abbastanza corto da stare in un'intestazione.
_SESSION_ID = re.compile(r"[A-Za-z0-9_\-]{16,128}")

#: Quante sessioni scadute/sfrattate ricordare per l'avviso (memoria limitata).
_MAX_SCADUTE = 256


def is_valid_session_id(value: str) -> bool:
    """``True`` se ``value`` ha la forma di un identificativo di sessione."""
    return _SESSION_ID.fullmatch(value) is not None


class SourcesExpiredError(Exception):
    """Le fonti caricate dalla sessione sono scadute o sono state sfrattate."""

    def __init__(self) -> None:
        super().__init__(
            "le fonti caricate in questa sessione sono scadute: caricale di nuovo "
            "o torna alle fonti predefinite"
        )


@dataclass
class SessionEntry:
    """Set attivo di una sessione, con gli avvisi del caricamento."""

    source_set: SourceSet
    warnings: Sequence[Problem]
    expires_at: float


class SessionStore:
    """Archivio in memoria ``session_id -> set`` con TTL e tetto di sessioni."""

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
        self._scadute: OrderedDict[str, None] = OrderedDict()

    @property
    def ttl_seconds(self) -> float:
        return self._ttl

    def count(self) -> int:
        """Sessioni con un set attivo (le scadute non ancora potate incluse)."""
        self._pota()
        return len(self._entries)

    def activate(
        self, session_id: str, source_set: SourceSet, warnings: Sequence[Problem]
    ) -> None:
        """Attiva ``source_set`` per la sessione, sostituendo quello precedente."""
        self._pota()
        self._scadute.pop(session_id, None)
        precedente = self._entries.pop(session_id, None)
        if precedente is not None:
            zone_context_cache.purge(precedente.source_set.id)
        while len(self._entries) >= self._max:
            piu_vecchia = min(self._entries, key=lambda k: self._entries[k].expires_at)
            self._elimina(piu_vecchia, ricorda=True)
        self._entries[session_id] = SessionEntry(
            source_set=source_set,
            warnings=tuple(warnings),
            expires_at=self._clock() + self._ttl,
        )

    def get(self, session_id: str) -> SessionEntry | None:
        """Il set della sessione (rinnovando la scadenza), o ``None`` se non ce n'e'.

        Raises:
            SourcesExpiredError: la sessione aveva un set, scaduto o sfrattato;
                si solleva a ogni lettura finche' non c'e' un nuovo caricamento o
                un :meth:`reset`.
        """
        self._pota()
        entry = self._entries.get(session_id)
        if entry is not None:
            entry.expires_at = self._clock() + self._ttl
            return entry
        if session_id in self._scadute:
            raise SourcesExpiredError
        return None

    def peek(self, session_id: str) -> SessionEntry | None:
        """Come :meth:`get` ma senza rinnovare la scadenza ne' sollevare l'avviso."""
        self._pota()
        return self._entries.get(session_id)

    def remaining_seconds(self, session_id: str) -> int | None:
        """Secondi alla scadenza (senza rinnovarla), ``None`` senza set attivo."""
        entry = self.peek(session_id)
        if entry is None:
            return None
        return max(0, round(entry.expires_at - self._clock()))

    def was_expired(self, session_id: str) -> bool:
        """``True`` se il set e' scaduto e l'utente non ha ancora scelto cosa fare."""
        self._pota()
        return session_id in self._scadute

    def reset(self, session_id: str) -> None:
        """Torna al default: toglie il set e l'eventuale avviso di scadenza."""
        self._scadute.pop(session_id, None)
        self._elimina(session_id, ricorda=False)

    def _pota(self) -> None:
        adesso = self._clock()
        for sid in [k for k, e in self._entries.items() if e.expires_at <= adesso]:
            self._elimina(sid, ricorda=True)

    def _elimina(self, session_id: str, *, ricorda: bool) -> None:
        entry = self._entries.pop(session_id, None)
        if entry is None:
            return
        zone_context_cache.purge(entry.source_set.id)
        if ricorda:
            self._scadute[session_id] = None
            while len(self._scadute) > _MAX_SCADUTE:
                self._scadute.popitem(last=False)
