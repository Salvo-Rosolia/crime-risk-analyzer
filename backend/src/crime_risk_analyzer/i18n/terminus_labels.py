"""Loader of the controlled EN→IT vocabulary (#77).

Single source: loads ``terminus_labels.json`` (identifier/label_en/label_it/
category) and exposes the lookups used by the UI (via API), the narrative and the eval.
The lookups degrade gracefully (normalised form of the identifier) if an entry is
missing, so the absence of a label does not break the flow at runtime.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import TypedDict, cast

_DATA_PATH = Path(__file__).parent / "terminus_labels.json"


class LabelRecord(TypedDict):
    """Vocabulary entry: real identifier + display labels + category."""

    identifier: str
    label_en: str
    label_it: str
    category: str


def _normalize(identifier: str) -> str:
    """Fallback display form: underscore→space, first letter capitalised."""
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


def _spaced(identifier: str) -> str:
    """Class name with spaces in place of separators (custom set)."""
    text = identifier.replace("_", " ").replace("-", " ").strip()
    return " ".join(text.split()) or identifier


def _set_labels(identifier: str) -> tuple[str, str] | None:
    """``(it, en)`` pair of a set that carries its own labels, otherwise None.

    ``None`` also when the set uses the TERMINUS JSON (``labels is None``):
    in that case we proceed on the controlled vocabulary as for the default.
    """
    # Local import: ``sources`` imports modules that import these labels.
    from crime_risk_analyzer.sources.context import current_labels

    labels = current_labels()
    if labels is None:
        return None
    return labels.get(identifier, ("", ""))


def label_it(identifier: str) -> str:
    """IT label of the class from the active set (TERMINUS JSON for the default).

    Set with its own labels: IT, then EN, then the name with spaces. For the
    TERMINUS JSON: IT, then EN, then the normalised name.
    """
    own_labels = _set_labels(identifier)
    if own_labels is not None:
        return own_labels[0] or own_labels[1] or _spaced(identifier)
    rec = _records().get(identifier)
    if rec is not None and rec["label_it"]:
        return rec["label_it"]
    if rec is not None and rec["label_en"]:
        return rec["label_en"]
    return _normalize(identifier)


def label_en(identifier: str) -> str:
    """EN label of the class from the active set (see :func:`label_it`)."""
    own_labels = _set_labels(identifier)
    if own_labels is not None:
        return own_labels[1] or _spaced(identifier)
    rec = _records().get(identifier)
    if rec is not None and rec["label_en"]:
        return rec["label_en"]
    return _normalize(identifier)


def controlled_vocab_for(identifiers: Iterable[str]) -> list[str]:
    """Allowed IT terms (deduplicated, order of first appearance)."""
    seen: dict[str, None] = {}
    for ident in identifiers:
        term = label_it(ident)
        if term not in seen:
            seen[term] = None
    return list(seen)
