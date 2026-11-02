"""Shared base of the ISTAT response fields (#345, fix round 1 review Task 13).

The three HTTP responses with a narrative (``AnalyzeResponse``,
``ZoneNarrativeResponse``, ``PoiNarrativeResponse``) inherit the same three
``istat_*`` fields from :class:`IstatResponseFields` instead of redefining them
each: a future divergence
(description/default/constraint changed in a single place) would break here, not
silently in only one of the three files.
"""

from __future__ import annotations

from crime_risk_analyzer.analyze_narrative import ZoneNarrativeResponse
from crime_risk_analyzer.istat.response_fields import IstatResponseFields
from crime_risk_analyzer.orchestrator import AnalyzeResponse
from crime_risk_analyzer.poi_narrative import PoiNarrativeResponse

_ISTAT_FIELDS = {"istat_attivo", "istat_versione_dati", "istat_frasi_scartate"}


def test_istat_response_fields_exposes_exactly_the_three_fields() -> None:
    assert set(IstatResponseFields.model_fields) == _ISTAT_FIELDS
    assert IstatResponseFields.model_fields["istat_attivo"].default is False
    assert IstatResponseFields.model_fields["istat_versione_dati"].default is None
    assert IstatResponseFields.model_fields["istat_frasi_scartate"].default == 0


def test_the_three_responses_inherit_the_same_istat_base() -> None:
    """The three responses do not redefine the fields: they get them from a single base.

    ``issubclass`` proves the inheritance. Pydantic rebuilds a ``FieldInfo`` for
    each subclass (never the same instance, even without redeclaration: identity is
    therefore not a useful test), so the comparison is on the ``repr`` -- same
    type, default, constraints and description: if one of the three had
    redeclared the field with a divergent description or default, the
    ``repr`` would differ and the test would turn red.
    """
    for response in (AnalyzeResponse, ZoneNarrativeResponse, PoiNarrativeResponse):
        assert issubclass(response, IstatResponseFields)
        assert _ISTAT_FIELDS <= set(response.model_fields)
        for field in _ISTAT_FIELDS:
            assert repr(response.model_fields[field]) == repr(
                IstatResponseFields.model_fields[field]
            )


def test_raw_narrative_and_istat_check_stay_only_on_analyze_response() -> None:
    """``narrativa_grezza``/``controllo_istat`` are not in the shared base:
    only ``AnalyzeResponse`` (harness) exposes them."""
    assert "narrativa_grezza" not in IstatResponseFields.model_fields
    assert "controllo_istat" not in IstatResponseFields.model_fields
    assert {"narrativa_grezza", "controllo_istat"} <= set(AnalyzeResponse.model_fields)
    assert "narrativa_grezza" not in ZoneNarrativeResponse.model_fields
    assert "narrativa_grezza" not in PoiNarrativeResponse.model_fields
