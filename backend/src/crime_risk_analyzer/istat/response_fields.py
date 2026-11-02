"""Shared response fields about ISTAT data in the narrative (#345).

The three HTTP responses that expose a narrative -- ``AnalyzeResponse``
(:mod:`~crime_risk_analyzer.orchestrator`), ``ZoneNarrativeResponse``
(:mod:`~crime_risk_analyzer.analyze_narrative`) and ``PoiNarrativeResponse``
(:mod:`~crime_risk_analyzer.poi_narrative`) -- report the SAME three observables
about the ISTAT switch: whether the prompt used them (``istat_attivo``), which
version of the data (``istat_versione_dati``) and how many sentences the figures
check discarded (``istat_frasi_scartate``).

Before this module the three ``Field`` definitions were copied identically in
three different files: a future divergence (description, default or constraint
changed in only one of the three places) would have gone unnoticed.
:class:`IstatResponseFields` is the common base the three responses inherit from,
so the contract lives in a single place.

It lives under ``istat/`` (not in ``rag/generation.py``, which already has
HOMONYMOUS fields on :class:`~crime_risk_analyzer.rag.generation.GenerationResult`
with deliberately different descriptions -- those describe a fact of the
generation layer, "the prompt contained the block", not the contract of the HTTP
response) and is importable from all three without cycles: the ``istat`` package
depends only on ``models.geo``/``i18n.terminus_labels``, never on
``orchestrator``/``analyze_narrative``/``poi_narrative``/``rag.*``.

``narrativa_grezza``/``controllo_istat`` (harness only, ``exclude=True``) are NOT
part of this base: they stay only on ``AnalyzeResponse``, the only one of the
three responses that exposes them.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["IstatResponseFields"]


class IstatResponseFields(BaseModel):
    """Common base of the three ISTAT fields exposed by responses with a narrative."""

    istat_attivo: bool = Field(
        default=False,
        description=(
            "True se la narrativa e' stata scritta coi dati ISTAT nel prompt (#345)."
        ),
    )
    istat_versione_dati: str | None = Field(
        default=None, description="Data di estrazione dei dati ISTAT usati (#345)."
    )
    istat_frasi_scartate: int = Field(
        default=0,
        ge=0,
        description=(
            "Frasi tolte dal controllo delle cifre (#345): trasparenza sul filtro, "
            "non una misura di pericolosita'."
        ),
    )
