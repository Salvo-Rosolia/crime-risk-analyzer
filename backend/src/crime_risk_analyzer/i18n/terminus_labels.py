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


def label_it(identifier: str) -> str:
    rec = _records().get(identifier)
    if rec is not None and rec["label_it"]:
        return rec["label_it"]
    if rec is not None and rec["label_en"]:
        return rec["label_en"]
    return _normalize(identifier)


def label_en(identifier: str) -> str:
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
