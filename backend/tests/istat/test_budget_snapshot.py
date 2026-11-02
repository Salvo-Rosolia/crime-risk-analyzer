"""Prompt budget with ISTAT on, on the 4 evaluation zones (#345, D14).

Uses the real ontology (ghost): in CI the test is skipped. Run it locally before the
PR and at every change of budget, prompt or data.
"""

from __future__ import annotations

import pytest
from scripts.istat_budget import ONTOLOGY, contexts, measure

from crime_risk_analyzer.rag.generation import DEFAULT_REQUEST_TOKEN_BUDGET

pytestmark = pytest.mark.skipif(
    not ONTOLOGY.exists(), reason="real ontology missing (it is not in the repo)"
)


async def test_with_istat_on_every_zone_has_the_block_and_fits_the_budget() -> None:
    cases = await contexts()
    assert len(cases) == 4
    for zone, ctx in cases:
        off = measure(zone, ctx, istat=False)
        on = measure(zone, ctx, istat=True)
        assert on.istat_items > 0, zone  # the reserve keeps the block in the prompt
        assert on.estimated_total <= DEFAULT_REQUEST_TOKEN_BUDGET, zone
        assert off.estimated_total <= DEFAULT_REQUEST_TOKEN_BUDGET, zone
        assert on.pois_included <= off.pois_included, zone
