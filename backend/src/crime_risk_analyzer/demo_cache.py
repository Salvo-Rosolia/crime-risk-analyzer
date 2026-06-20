"""Loader della cache di analisi precalcolata per la demo (#21).

Contratto (generation.md §"Cache locale per demo", spec-root §C1): prima della
discussione si salva **un file JSON per scenario** in ``demo/cache/{id}.json``;
quando un'API esterna e' down e la cache demo e' abilitata, il sistema serve
quel payload precalcolato invece di fallire. Questo e' l'**unico** ripiego
previsto: **nessun failover automatico su Groq** (lo switch Claude/Groq resta
manuale, ``LLM_PROVIDER`` — _project.md §Stack, spec-root §C1).

Confini: questo modulo legge e valida il file di cache in isolamento. La
*decisione* di ricorrere alla cache (catturare l'errore d'API, verificare il
flag ``use_demo_cache``, risolvere lo ``scenario_id`` della richiesta) spetta
all'orchestrator ``/analyze`` (#18), non implementato qui.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

#: Tipo del payload di cache: lo schema canonico di ``/analyze`` e' un oggetto JSON.
DemoCachePayload = dict[str, Any]


class DemoCacheError(RuntimeError):
    """La cache demo non e' caricabile (assente, illeggibile o malformata)."""


class DemoCacheNotFoundError(DemoCacheError):
    """Non esiste un file di cache per lo ``scenario_id`` richiesto."""


def _resolve_cache_file(scenario_id: str, cache_dir: Path) -> Path:
    """Risolve il file ``{scenario_id}.json`` dentro ``cache_dir``.

    Lo ``scenario_id`` e' una *chiave* (es. ``"colosseo"``), non un percorso:
    qualunque separatore di path o componente relativa lo rende invalido, cosi'
    non si puo' uscire da ``cache_dir`` (no directory traversal).
    """
    if not scenario_id or "/" in scenario_id or "\\" in scenario_id:
        raise DemoCacheError(f"scenario_id non valido: {scenario_id!r}")
    if Path(scenario_id).name != scenario_id:
        raise DemoCacheError(f"scenario_id non valido: {scenario_id!r}")
    return cache_dir / f"{scenario_id}.json"


def load_demo_cache(scenario_id: str, *, cache_dir: Path) -> DemoCachePayload:
    """Carica la risposta di ``/analyze`` precalcolata per ``scenario_id``.

    Legge ``cache_dir/{scenario_id}.json`` e lo restituisce come dizionario.
    Solleva :class:`DemoCacheNotFoundError` se il file non esiste e
    :class:`DemoCacheError` se non e' leggibile o non e' un oggetto JSON valido.
    """
    cache_file = _resolve_cache_file(scenario_id, cache_dir)
    try:
        raw = cache_file.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DemoCacheNotFoundError(
            f"Cache demo assente per scenario {scenario_id!r}: {cache_file}"
        ) from exc
    except OSError as exc:
        raise DemoCacheError(
            f"Cache demo illeggibile per scenario {scenario_id!r}: {exc}"
        ) from exc

    try:
        payload: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DemoCacheError(
            f"Cache demo non e' JSON valido per scenario {scenario_id!r}: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise DemoCacheError(
            f"Cache demo malformata per scenario {scenario_id!r}: atteso oggetto JSON"
        )
    # ``json.loads`` produce ``dict[Any, Any]``: le chiavi di un oggetto JSON sono
    # sempre stringhe, quindi il cast a ``DemoCachePayload`` (``dict[str, Any]``)
    # e' lecito senza reintrospezione.
    return cast(DemoCachePayload, payload)
