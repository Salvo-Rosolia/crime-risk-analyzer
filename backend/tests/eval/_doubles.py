"""Shared test doubles and helpers for test_orchestrator, test_harness and
test_no_ontology_generation (#34, #349).

This is not a test file (no test_* function): pytest collects nothing.
Extracted from test_orchestrator.py to avoid duplication.
"""

from __future__ import annotations

from pathlib import Path

from crime_risk_analyzer.eval.snapshots import save_snapshot
from crime_risk_analyzer.llm.client import LLMResponse
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.overpass_client import Poi

#: Sample area for snapshots written as fixtures.
TEST_BBOX = Bbox(41.0, 12.0, 41.1, 12.1)


def write_snapshot(path: Path, pois: list[Poi], *, citta: str = "Roma") -> None:
    """``save_snapshot`` with a sample provenance.

    Since #241 area and city are mandatory in ``save_snapshot``: a provenance
    that omits the area queried is of no use to anyone. The tests that use the
    snapshot only as a FIXTURE (idempotence, replay, skip) have nothing to say
    about the provenance: they go through here instead of repeating values they are not
    verifying. Whoever verifies the provenance calls ``save_snapshot`` directly.
    """
    save_snapshot(path, pois, bbox=TEST_BBOX, citta=citta)


class FakeProfiler:
    """RiskProfiler double for tests without SPARQL.

    Constructible without arguments (harness test); accepts an optional dictionary
    for the orchestrator tests that inject specific profiles.
    """

    def __init__(self, profiles: dict[str, PoiRiskProfile] | None = None) -> None:
        self._profiles: dict[str, PoiRiskProfile] = profiles or {}

    def profile(self, terminus_class: str) -> PoiRiskProfile:
        return self._profiles.get(
            terminus_class, PoiRiskProfile(terminus_class=terminus_class)
        )


class FakeLLMClient:
    """_LLMClientLike double for tests without a real LLM provider.

    Constructible without arguments (harness test); accepts an optional response
    for the orchestrator tests that check specific values.
    """

    def __init__(self, response: LLMResponse | None = None) -> None:
        self._response: LLMResponse = response or default_llm_response()

    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        return self._response


def default_llm_response() -> LLMResponse:
    """Default LLM response used by FakeLLMClient() without arguments."""
    return LLMResponse(
        text="Analisi: Banca A presenta rischio rapina.",
        llm_used="claude-sonnet-4-6",
        tokens_input=10,
        tokens_output=20,
        cache_hit=False,
        temperature=0.2,
        seed=42,
        prompt_hash="abc123",
    )


def poi_lines(user_content: str) -> list[str]:
    """Header lines of the points (``  POI: ...``) of a user_content.

    Single helper for both arms (#349): the lines are the same by
    construction (``generation.poi_line``), so is whoever extracts them.
    """
    return [r for r in user_content.splitlines() if r.startswith("  POI: ")]
