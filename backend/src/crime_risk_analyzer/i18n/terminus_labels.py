"""Loader del vocabolario controllato EN→IT (#77).

Sorgente unica: carica ``terminus_labels.json`` (identifier/label_en/label_it/
category) ed espone i lookup usati da UI (via API), narrativa ed eval. I lookup
degradano con grazia (forma normalizzata dell'identifier) se una voce manca, così
l'assenza di un'etichetta non rompe il flusso a runtime.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import TypedDict, cast

_DATA_PATH = Path(__file__).parent / "terminus_labels.json"


class LabelRecord(TypedDict):
    """Voce del vocabolario: identifier reale + etichette display + categoria."""

    identifier: str
    label_en: str
    label_it: str
    category: str


def _normalize(identifier: str) -> str:
    """Forma display di fallback: underscore→spazio, prima lettera maiuscola."""
    text = identifier.replace("_", " ").strip()
    if not text:
        return identifier
    return text[:1].upper() + text[1:]


@lru_cache(maxsize=1)
def _records() -> dict[str, LabelRecord]:
    if not _DATA_PATH.exists():
        return {}
    raw = cast(list[LabelRecord], json.loads(_DATA_PATH.read_text(encoding="utf-8")))
    return {rec["identifier"]: rec for rec in raw}


def _spaziata(identifier: str) -> str:
    """Nome della classe con gli spazi al posto dei separatori (set custom)."""
    text = identifier.replace("_", " ").replace("-", " ").strip()
    return " ".join(text.split()) or identifier


def _etichette_del_set(identifier: str) -> tuple[str, str] | None:
    """Coppia ``(it, en)`` di un set che porta le proprie etichette, altrimenti None.

    ``None`` anche quando il set usa il JSON TERMINUS (``labels is None``):
    in quel caso si prosegue sul vocabolario controllato come per il default.
    """
    # Import locale: ``sources`` importa moduli che importano queste etichette.
    from crime_risk_analyzer.sources.context import current_labels

    labels = current_labels()
    if labels is None:
        return None
    return labels.get(identifier, ("", ""))


def label_it(identifier: str) -> str:
    """Etichetta IT della classe dal set attivo (JSON TERMINUS per il default).

    Set con etichette proprie: IT, poi EN, poi il nome con gli spazi. Per il
    JSON TERMINUS: IT, poi EN, poi il nome normalizzato.
    """
    propria = _etichette_del_set(identifier)
    if propria is not None:
        return propria[0] or propria[1] or _spaziata(identifier)
    rec = _records().get(identifier)
    if rec is not None and rec["label_it"]:
        return rec["label_it"]
    if rec is not None and rec["label_en"]:
        return rec["label_en"]
    return _normalize(identifier)


def label_en(identifier: str) -> str:
    """Etichetta EN della classe dal set attivo (vedi :func:`label_it`)."""
    propria = _etichette_del_set(identifier)
    if propria is not None:
        return propria[1] or _spaziata(identifier)
    rec = _records().get(identifier)
    if rec is not None and rec["label_en"]:
        return rec["label_en"]
    return _normalize(identifier)


def controlled_vocab_for(identifiers: Iterable[str]) -> list[str]:
    """Termini IT ammessi (deduplicati, ordine di prima apparizione)."""
    seen: dict[str, None] = {}
    for ident in identifiers:
        term = label_it(ident)
        if term not in seen:
            seen[term] = None
    return list(seen)
