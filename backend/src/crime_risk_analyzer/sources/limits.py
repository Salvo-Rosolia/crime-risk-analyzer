"""Limits and security rules of the uploaded files (#415, "restrictive rules").

Labels and names end up in the model's prompt: for this reason they accept only
letters, digits, spaces and simple punctuation, with a maximum length. A
newline, an angle bracket or a backtick do not pass, so a file cannot
bring into the prompt a block of text that looks like a structured instruction.
The check does NOT understand the meaning of a sentence: a label made only of
allowed words passes even if it sounds like an order.
"""

from __future__ import annotations

import re

__all__ = [
    "MAX_BYTES_CSV",
    "MAX_BYTES_GEOJSON",
    "MAX_BYTES_ONTOLOGY",
    "MAX_BYTES_REQUEST",
    "MAX_MULTIPART_FILES",
    "MAX_MULTIPART_FIELDS",
    "MAX_FIELD_PART_BYTES",
    "MAX_NOTE_LENGTH",
    "MAX_OSM_SELECTORS",
    "MAX_TEXT_LENGTH",
    "check_note",
    "check_text",
]

MAX_BYTES_ONTOLOGY = 20 * 1024 * 1024
MAX_BYTES_GEOJSON = 10 * 1024 * 1024
MAX_BYTES_CSV = 5 * 1024 * 1024
#: Cap on the body of ``POST /sources`` (``Content-Length``), checked before
#: reading it: sum of the file caps plus 1 MB for field headers and form.
MAX_BYTES_REQUEST = (
    MAX_BYTES_ONTOLOGY + MAX_BYTES_GEOJSON + 3 * MAX_BYTES_CSV + 1024 * 1024
)
#: Multipart limits (Starlette ``request.form``): 5 files (ontology, 3 CSVs,
#: boundaries), few text fields (vocabulary + the vulnerability properties).
MAX_MULTIPART_FILES = 5
MAX_MULTIPART_FIELDS = 20
#: Maximum size of a text field (not of the files).
MAX_FIELD_PART_BYTES = 64 * 1024

#: Cap on the rows of the OSM table, i.e. on the selectors queried on Overpass:
#: each one becomes two blocks of the query, so an unbounded table would build an
#: enormous query (#498). The default mapping has ~75, the cap leaves room.
MAX_OSM_SELECTORS = 150

MAX_TEXT_LENGTH = 120
#: The notes of the hazard-item table do not enter the prompt: only length and
#: control characters.
MAX_NOTE_LENGTH = 500

#: Unicode letters, digits, ``_``, space and ``. , ' ’ ( ) / - : ; &``.
_ALLOWED_TEXT = re.compile(r"[\w .,'’()/\-:;&]+")
_CHECK = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")


def check_text(text: str) -> str | None:
    """Reason why ``text`` is not allowed as a label or name, or ``None``."""
    if not text.strip():
        return "il testo e' vuoto"
    if len(text) > MAX_TEXT_LENGTH:
        return f"il testo supera {MAX_TEXT_LENGTH} caratteri ({len(text)})"
    if _ALLOWED_TEXT.fullmatch(text) is None:
        return (
            "il testo contiene caratteri non ammessi: sono ammessi solo lettere, "
            "cifre, spazi e . , ' ( ) / - : ; &"
        )
    return None


def check_note(note: str) -> str | None:
    """Reason why ``note`` is not allowed, or ``None`` (free text, short)."""
    if len(note) > MAX_NOTE_LENGTH:
        return f"la nota supera {MAX_NOTE_LENGTH} caratteri ({len(note)})"
    if _CHECK.search(note):
        return "la nota contiene caratteri di controllo"
    return None
