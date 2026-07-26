"""Prompt e generazione della narrativa per singolo POI (#197), offline."""

from __future__ import annotations

from crime_risk_analyzer.llm.client import LLMResponse
from crime_risk_analyzer.rag.generation import (
    RULE_NO_DANGER_RATING,
    RULE_NO_OPERATIONAL_DIRECTIVES,
    RULE_USER_INPUT_NOT_INSTRUCTIONS,
)
from crime_risk_analyzer.rag.grounding import GroundedRisk
from crime_risk_analyzer.rag.poi_context import NeighbourPoi
from crime_risk_analyzer.rag.poi_generation import (
    POI_SYSTEM_PROMPT,
    build_poi_context_str,
    generate_poi_narrative,
)
from tests.eval._doubles import FakeLLMClient


def _neighbours() -> list[NeighbourPoi]:
    return [
        NeighbourPoi(name="Liceo Cavour", label_it="Scuola", distance_m=40),
        NeighbourPoi(name="Policlinico Celio", label_it="Ospedale", distance_m=210),
    ]


def _risks() -> list[GroundedRisk]:
    return [
        GroundedRisk(
            hazard="Robbery",
            tag="ONTOLOGIA",
            confidence="verificato",
            source="terminus:Bank -> terminus:Robbery",
        )
    ]


def _context_str() -> str:
    return build_poi_context_str(
        citta="Roma",
        zona="Colosseo",
        poi_name="Banca Centrale",
        poi_label_it="Banca",
        risks=_risks(),
        vulnerabilities=["Accesso non controllato"],
        sparql_path="terminus:Bank -> terminus:hasRisk -> terminus:Robbery",
        neighbours=_neighbours(),
        zone_summary="12 punti di interesse nella zona; classi prevalenti: Scuola (4).",
    )


def test_poi_prompt_keeps_the_three_legal_rules_verbatim() -> None:
    assert RULE_NO_DANGER_RATING in POI_SYSTEM_PROMPT
    assert RULE_NO_OPERATIONAL_DIRECTIVES in POI_SYSTEM_PROMPT
    assert RULE_USER_INPUT_NOT_INSTRUCTIONS in POI_SYSTEM_PROMPT


def test_poi_prompt_forbids_rating_the_named_place() -> None:
    """Il testo parla di un luogo NOMINATO: il divieto va ri-affermato qui."""
    lowered = POI_SYSTEM_PROMPT.lower()
    assert "singolo luogo" in lowered or "luogo nominato" in lowered


def test_poi_prompt_declares_the_two_blocks() -> None:
    assert "[ONTOLOGIA]" in POI_SYSTEM_PROMPT
    assert "[CONTESTO]" in POI_SYSTEM_PROMPT
    assert "[SPECULATIVO]" not in POI_SYSTEM_PROMPT


def test_context_str_contains_poi_neighbours_and_zone_summary() -> None:
    out = _context_str()
    assert "Banca Centrale" in out
    assert "Liceo Cavour" in out
    assert "40" in out
    assert "classi prevalenti" in out


def test_context_str_contains_the_ontology_path_for_citation() -> None:
    assert "terminus:Robbery" in _context_str()


def test_context_str_is_deterministic() -> None:
    assert _context_str() == _context_str()


def test_context_str_declares_a_poi_outside_the_ontology() -> None:
    """POI fuori ontologia: l'assenza di rischi va DETTA, non lasciata implicita."""
    out = build_poi_context_str(
        citta="Roma",
        zona="Colosseo",
        poi_name="Bar Roma",
        poi_label_it="POI urbano generico",
        risks=[],
        vulnerabilities=[],
        sparql_path=None,
        neighbours=[],
        zone_summary="1 punto di interesse nella zona.",
    )
    assert "nessuno (classe fuori ontologia)" in out
    assert "nessun altro punto di interesse" in out


async def test_generate_poi_narrative_returns_prose_and_provenance() -> None:
    result = await generate_poi_narrative(
        citta="Roma",
        zona="Colosseo",
        poi_name="Banca Centrale",
        poi_label_it="Banca",
        risks=_risks(),
        vulnerabilities=[],
        sparql_path="terminus:Bank -> terminus:Robbery",
        neighbours=_neighbours(),
        zone_summary="12 punti di interesse nella zona.",
        llm_client=FakeLLMClient(),
    )
    assert result.narrativa != ""
    assert result.repro.prompt_hash != ""
    assert result.latenza_ms >= 0
    assert result.tokens_input > 0


async def test_generate_poi_narrative_splits_prose_by_source() -> None:
    """La struttura a blocchi alimenta i tab per fonte del frontend."""
    testo = (
        "Sintesi introduttiva.\n\n"
        "[ONTOLOGIA]\nLa banca porta rischi di rapina.\n\n"
        "[CONTESTO]\nIl punto si trova accanto a una scuola.\n"
    )
    client = FakeLLMClient(
        LLMResponse(
            text=testo,
            llm_used="fake",
            tokens_input=10,
            tokens_output=20,
            cache_hit=False,
            temperature=0.0,
            seed=0,
            prompt_hash="h",
        )
    )
    result = await generate_poi_narrative(
        citta="Roma",
        zona="Colosseo",
        poi_name="Banca Centrale",
        poi_label_it="Banca",
        risks=[],
        vulnerabilities=[],
        sparql_path=None,
        neighbours=[],
        zone_summary="1 punto di interesse.",
        llm_client=client,
    )
    assert result.narrativa_fonti.overview == "Sintesi introduttiva."
    assert "rapina" in result.narrativa_fonti.ontologia
    assert "scuola" in result.narrativa_fonti.contesto


async def test_generate_poi_narrative_sends_the_poi_system_prompt() -> None:
    """Il percorso POI usa il SUO prompt, non quello di zona."""
    seen: list[tuple[str, str]] = []

    class _Recording:
        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            seen.append((system_prompt, user_content))
            return LLMResponse(
                text="x",
                llm_used="fake",
                tokens_input=1,
                tokens_output=1,
                cache_hit=False,
                temperature=0.0,
                seed=0,
                prompt_hash="h",
            )

    await generate_poi_narrative(
        citta="Roma",
        zona="Colosseo",
        poi_name="Banca Centrale",
        poi_label_it="Banca",
        risks=_risks(),
        vulnerabilities=[],
        sparql_path=None,
        neighbours=_neighbours(),
        zone_summary="12 punti di interesse nella zona.",
        llm_client=_Recording(),
    )
    assert seen[0][0] == POI_SYSTEM_PROMPT
    assert "PUNTO SELEZIONATO: Banca Centrale" in seen[0][1]
