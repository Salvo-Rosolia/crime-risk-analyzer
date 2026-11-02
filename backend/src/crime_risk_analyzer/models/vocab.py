"""Typed vocabulary of the citation layer (confidence + tag).

Single point of truth for the canonical values crossing grounding,
generation and JSON output. Making them :data:`Literal` turns a domain
invariant into a constraint verified by the types (pyright) and by Pydantic validation:
a ``confidence="alto"`` or a wrong casing (``"Confermato"``) fail instead
of silently propagating.

Canonical casing (``_project.md`` §Confidence/§Citation):
- ``confidence`` -> **lowercase**: ``verificato`` / ``da_confermare``.
- ``tag`` -> **uppercase**: ``ONTOLOGIA`` / ``CONTESTO`` / ``SPECULATIVO``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: Qualitative confidence level (never a numeric score). Canonical lowercase
#: casing, aligned with ``ConfidenceSummary`` and the demo data.
Confidence = Literal["verificato", "da_confermare"]

#: Source tag of the citation layer (anti-hallucination). Canonical uppercase casing.
Tag = Literal["ONTOLOGIA", "CONTESTO", "SPECULATIVO"]


class ConfidenceSummary(BaseModel):
    """Count of the risks per confidence level.

    Replaces the old ``dict[str, int]``: the two canonical levels become
    typed fields (default 0, non-negative), so the shape is guaranteed by the
    model instead of conventional.
    """

    verificato: int = Field(default=0, ge=0, description="Rischi verificati.")
    da_confermare: int = Field(default=0, ge=0, description="Rischi da confermare.")
