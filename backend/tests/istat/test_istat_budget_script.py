"""Budget measuring script (#345, D14, F9 of the final review).

Without the real ontology: synthetic contexts. The script must prepare the request
EXACTLY like ``generate_analysis`` (same function), and the budget search must
also look above the default.
"""

from __future__ import annotations

from typing import Any

from scripts.istat_budget import measure, suggested_budget

from crime_risk_analyzer.rag.generation import (
    DEFAULT_MAX_TOKENS,
    SYSTEM_PROMPT_ISTAT,
    _estimate_tokens,  # pyright: ignore[reportPrivateUsage]
    generate_analysis,
    prepara_richiesta_zona,
)
from tests.istat._factories import BANKROB, istat_poi
from tests.test_generation_istat import (
    _ctx,  # pyright: ignore[reportPrivateUsage]
    _poi,  # pyright: ignore[reportPrivateUsage]
    _Spia,  # pyright: ignore[reportPrivateUsage]
)


def _many_pois(con_istat: bool) -> dict[str, Any]:
    return _ctx(
        *(
            _poi(f"node/{i}", istat=istat_poi(BANKROB) if con_istat else None)
            for i in range(40)
        )
    )


def _tight_budget() -> int:
    """A budget leaving little room with the ISTAT prompt: the POI selection changes."""
    return _estimate_tokens(SYSTEM_PROMPT_ISTAT) + DEFAULT_MAX_TOKENS + 200


def test_istat_on_without_rows_measures_like_istat_off() -> None:
    """The ``generate_analysis`` gate: without ISTAT rows, everything as when off."""
    ctx = _many_pois(con_istat=False)
    on = measure("z", ctx, istat=True, budget=_tight_budget())
    off = measure("z", ctx, istat=False, budget=_tight_budget())
    assert on._replace(istat=False) == off


async def test_the_measure_is_the_request_that_generate_analysis_sends() -> None:
    for con_istat in (False, True):
        ctx = _many_pois(con_istat)
        for istat in (False, True):
            spy = _Spia()
            await generate_analysis(
                ctx, spy, istat=istat, request_token_budget=_tight_budget()
            )
            request = prepara_richiesta_zona(
                ctx, istat=istat, request_token_budget=_tight_budget()
            )
            assert spy.calls == [(request.system_prompt, request.contesto.testo)]
            m = measure("z", ctx, istat=istat, budget=_tight_budget())
            assert m.estimated_total == (
                _estimate_tokens(request.system_prompt)
                + _estimate_tokens(request.contesto.testo)
                + DEFAULT_MAX_TOKENS
            )
            assert m.pois_included == request.contesto.poi_inclusi


def test_suggested_budget_also_searches_above_the_default() -> None:
    cases = [("z", _many_pois(con_istat=True))]
    # Counter that weighs nothing: every budget of the search fits under the limit,
    # so the suggested one is the highest of the interval, not the default.
    assert suggested_budget(cases, real=lambda _text: 0) == 12000


def test_suggested_budget_none_if_no_budget_fits_under_the_limit() -> None:
    cases = [("z", _many_pois(con_istat=True))]
    assert suggested_budget(cases, real=lambda _text: 10**6) is None
