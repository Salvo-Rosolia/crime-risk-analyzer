"""POI narrative with the ISTAT data (#345, spec 4.5)."""

from __future__ import annotations

import dataclasses

import pytest

from crime_risk_analyzer.istat.block import ISTAT_DATA_HEADER
from crime_risk_analyzer.istat.rows import IstatPoi
from crime_risk_analyzer.llm.client import LLMResponse
from crime_risk_analyzer.rag import poi_generation as poi_mod
from crime_risk_analyzer.rag.grounding import GroundedRisk
from crime_risk_analyzer.rag.poi_context import NeighbourPoi
from crime_risk_analyzer.rag.poi_generation import (
    POI_SYSTEM_PROMPT,
    POI_SYSTEM_PROMPT_ISTAT,
    build_poi_context_str,
    generate_poi_narrative,
)
from crime_risk_analyzer.sources.context import bind, default_set
from crime_risk_analyzer.sources.model import IstatSource
from tests.istat._factories import BANK_ROBBERIES, istat_poi


class _Spy:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        self.calls.append((system_prompt, user_content))
        return LLMResponse(
            text=self.text,
            llm_used="openai/gpt-oss-120b",
            tokens_input=1,
            tokens_output=1,
            cache_hit=False,
            temperature=0.0,
            seed=0,
            prompt_hash="h",
        )


_RISKS = [
    GroundedRisk(
        hazard="Bank_robbery",
        tag="ONTOLOGIA",
        confidence="verificato",
        source="Bank → havingHazard → Bank_robbery",
    )
]


def _context(istat: IstatPoi | None = None) -> str:
    return build_poi_context_str(
        citta="Roma",
        zona="Colosseo",
        poi_name="Banca A",
        poi_label_it="Banca",
        risks=_RISKS,
        vulnerabilities=[],
        sparql_path="Bank → havingHazard → Bank_robbery",
        neighbours=[NeighbourPoi(name="Liceo", label_it="Scuola", distance_m=40)],
        zone_summary="2 punti di interesse nella zona.",
        istat=istat,
    )


async def _generate(
    text: str, istat: IstatPoi | None
) -> tuple[_Spy, poi_mod.PoiGenerationResult]:
    spy = _Spy(text)
    out = await generate_poi_narrative(
        citta="Roma",
        zona="Colosseo",
        poi_name="Banca A",
        poi_label_it="Banca",
        risks=_RISKS,
        vulnerabilities=[],
        sparql_path="Bank → havingHazard → Bank_robbery",
        neighbours=[NeighbourPoi(name="Liceo", label_it="Scuola", distance_m=40)],
        zone_summary="2 punti di interesse nella zona.",
        llm_client=spy,
        istat=istat,
    )
    return spy, out


def test_context_without_istat_unchanged() -> None:
    without = _context()
    assert "DATI ISTAT" not in without
    assert without == build_poi_context_str(
        citta="Roma",
        zona="Colosseo",
        poi_name="Banca A",
        poi_label_it="Banca",
        risks=_RISKS,
        vulnerabilities=[],
        sparql_path="Bank → havingHazard → Bank_robbery",
        neighbours=[NeighbourPoi(name="Liceo", label_it="Scuola", distance_m=40)],
        zone_summary="2 punti di interesse nella zona.",
    )


def test_context_with_istat_before_neighbourhood_without_involved_pois() -> None:
    text = _context(istat_poi(BANK_ROBBERIES))
    assert text.index(ISTAT_DATA_HEADER) < text.index("VICINATO")
    assert "- Comune di Roma, 2024: rapine in banca: " in text
    assert "BANKROB" not in text
    assert "POI coinvolti" not in text


async def test_generation_with_istat_uses_the_variant_and_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(poi_mod, "istat_data_version", lambda: "2026-10-06")
    text = (
        "[ONTOLOGIA]\nLa Banca A conta 46 rapine in banca. Rischio di rapina. "
        "Secondo i dati ISTAT del Comune di Roma le rapine in banca hanno un tasso "
        "piu' alto di quello italiano.\n\n[CONTESTO]\nZona di transito.\n"
    )
    spy, out = await _generate(text, istat_poi(BANK_ROBBERIES))
    assert spy.calls[0][0] == POI_SYSTEM_PROMPT_ISTAT
    assert out.narrativa_grezza == text
    assert "46" not in out.narrativa
    # #365: no [ISTAT] block, the data in words sit in [ONTOLOGIA]
    assert out.narrativa_fonti.istat == ""
    assert "Secondo i dati ISTAT del Comune di Roma" in out.narrativa_fonti.ontologia
    assert (out.istat_attivo, out.istat_versione_dati, out.istat_frasi_scartate) == (
        True,
        "2026-10-06",
        1,
    )


async def test_generation_without_istat_as_before() -> None:
    spy, out = await _generate("[ONTOLOGIA]\nRischio di rapina.\n", None)
    assert spy.calls[0][0] == POI_SYSTEM_PROMPT
    assert out.narrativa == "[ONTOLOGIA]\nRischio di rapina.\n"
    assert (out.istat_attivo, out.istat_frasi_scartate) == (False, 0)


async def test_data_version_from_bound_set_without_monkeypatch() -> None:
    active = default_set()
    custom = dataclasses.replace(
        active,
        id="x",
        kind="custom",
        istat=IstatSource(
            dati=active.istat.dati,
            mappatura=active.istat.mappatura,
            voci_rottura=active.istat.voci_rottura,
            versione="X",
        ),
    )
    with bind(custom):
        _, out = await _generate(
            "[ONTOLOGIA]\nRischio di rapina.\n", istat_poi(BANK_ROBBERIES)
        )
    assert (out.istat_attivo, out.istat_versione_dati) == (True, "X")
