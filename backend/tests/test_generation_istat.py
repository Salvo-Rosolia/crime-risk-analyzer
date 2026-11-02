"""Generation layer with the ISTAT data (#345, #365): parsing, context, filter.

Since #365 the prompt no longer asks for the [ISTAT] block: the parser still
recognizes it for the narratives written before, and the parsing tests use that
form.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from crime_risk_analyzer.istat.figures import BlockSpan, apply_check
from crime_risk_analyzer.istat.rows import IstatPoi
from crime_risk_analyzer.istat.selection import RULE_ISTAT_SELECTION, SelectionDiscards
from crime_risk_analyzer.llm.client import LLMResponse
from crime_risk_analyzer.rag import generation as generation_mod
from crime_risk_analyzer.rag.generation import (
    ISTAT_BLOCK_HEADER,
    ISTAT_RESERVE_MAX_TOKENS,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_ISTAT,
    SYSTEM_PROMPT_ISTAT_SELECTION,
    SourceProse,
    _estimate_tokens,  # pyright: ignore[reportPrivateUsage]
    build_context,
    build_context_str,
    generate_analysis,
    parse_source_prose,
    source_block_spans,
)
from crime_risk_analyzer.sources.context import bind, default_set
from crime_risk_analyzer.sources.model import IstatSource
from tests.istat._factories import BANK_ROBBERIES, BANKROB, istat_poi, make_row

#: Narrativa in the #345 form, with the third [ISTAT] block (old records, D4).
_NARRATIVE = (
    "Sintesi della zona.\n\n"
    "Rischi da ontologia [ONTOLOGIA]\nRapina in banca per Banca A.\n\n"
    "Rischi dal contesto [CONTESTO]\nZona di transito.\n\n"
    f"{ISTAT_BLOCK_HEADER}\nLe rapine in banca sono 3 nel 2024.\n"
)


def test_parse_splits_the_third_istat_block() -> None:
    assert parse_source_prose(_NARRATIVE) == SourceProse(
        overview="Sintesi della zona.",
        ontologia="Rapina in banca per Banca A.",
        contesto="Zona di transito.",
        istat="Le rapine in banca sono 3 nel 2024.",
    )


def test_parse_recognizes_decorated_istat_header_ignores_token_in_sentence() -> None:
    """Review Focus 4."""
    text = (
        "Sintesi: il tag [ISTAT] compare anche qui, dentro una frase.\n\n"
        "Rischi da ontologia [ONTOLOGIA]\nRapina.\n\n"
        "**Dati statistici ISTAT [ISTAT]**\nI furti sono 3.\n"
    )
    sources_id = parse_source_prose(text)
    assert sources_id.overview.startswith("Sintesi: il tag [ISTAT]")
    assert sources_id.ontologia == "Rapina."
    assert sources_id.istat == "I furti sono 3."


def test_narratives_without_istat_remain_identical() -> None:
    text = "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n"
    assert parse_source_prose(text).istat == ""
    assert parse_source_prose(text).ontologia == "Rapina."


def test_block_spans() -> None:
    spans = source_block_spans(_NARRATIVE)
    assert [s.campo for s in spans] == ["ontologia", "contesto", "istat"]
    assert all(isinstance(s, BlockSpan) for s in spans)
    istat = spans[2]
    assert _NARRATIVE[istat.inizio_riga : istat.inizio] == f"{ISTAT_BLOCK_HEADER}\n"
    assert istat.fine == len(_NARRATIVE)
    assert spans[0].fine == spans[1].inizio_riga
    assert source_block_spans("solo testo") == []


class _Spy:
    def __init__(
        self, text: str = "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n"
    ) -> None:
        self.testo = text
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        self.calls.append((system_prompt, user_content))
        return LLMResponse(
            text=self.testo,
            llm_used="openai/gpt-oss-120b",
            tokens_input=10,
            tokens_output=20,
            cache_hit=False,
            temperature=0.0,
            seed=0,
            prompt_hash="h",
        )


def _poi(poi_id: str = "node/1", istat: IstatPoi | None = None) -> dict[str, Any]:
    poi: dict[str, Any] = {
        "poi_id": poi_id,
        "poi": f"Banca {poi_id}",
        "terminus_class": "Bank",
        "risks": [
            {
                "hazard": "Bank_robbery",
                "tag": "ONTOLOGIA",
                "confidence": "verificato",
                "source": "Bank → havingHazard → Bank_robbery",
            }
        ],
        "vulnerabilities": [],
        "sparql_path": "Bank → havingHazard → Bank_robbery",
    }
    if istat is not None:
        poi["istat"] = istat
    return poi


def _ctx(*pois: dict[str, Any]) -> dict[str, Any]:
    return {
        "zona": "Colosseo",
        "validated_risks": list(pois),
        "confidence_summary": {"verificato": len(pois), "da_confermare": 0},
    }


async def test_istat_off_prompt_identical_even_with_rows_in_cache() -> None:
    """Review Focus 3: the cached context carries the rows, the switch is off."""
    with_rows, without = _Spy(), _Spy()
    out = await generate_analysis(
        _ctx(_poi(istat=istat_poi(BANK_ROBBERIES))), with_rows, istat=False
    )
    await generate_analysis(_ctx(_poi()), without)
    assert with_rows.calls == without.calls
    assert with_rows.calls[0][0] == SYSTEM_PROMPT
    assert (out.istat_attivo, out.istat_frasi_scartate, out.controllo_istat) == (
        False,
        0,
        None,
    )
    assert out.narrativa == out.narrativa_grezza


async def test_istat_on_puts_the_block_between_vocabulary_and_poi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generation_mod, "istat_data_version", lambda: "2026-10-06")
    spy = _Spy()
    out = await generate_analysis(
        _ctx(_poi(istat=istat_poi(BANK_ROBBERIES))), spy, istat=True
    )
    system, user = spy.calls[0]
    assert system == SYSTEM_PROMPT_ISTAT
    assert (
        user.index("VOCABOLARIO")
        < user.index("DATI ISTAT")
        < user.index("POI RILEVANTI")
    )
    assert (
        "- Comune di Roma, 2024: rapine in banca: tasso più alto di quello italiano"
        in user
    )
    assert "BANKROB" not in user
    assert "tasso più alto di quello italiano" in user
    assert "[ISTAT]" not in system
    assert (out.istat_attivo, out.istat_versione_dati) == (True, "2026-10-06")


async def test_voce_under_20_delitti_does_not_trigger_istat() -> None:
    """#365 D2: with only the 3 bank robberies there is no ISTAT DATA block, and the
    prompt is the one with ISTAT off."""
    enabled, disabled = _Spy(), _Spy()
    out = await generate_analysis(
        _ctx(_poi(istat=istat_poi(BANKROB))), enabled, istat=True
    )
    await generate_analysis(_ctx(_poi()), disabled, istat=False)
    assert enabled.calls == disabled.calls
    assert out.istat_attivo is False


async def test_istat_on_without_rows_is_identical_to_off() -> None:
    """Review Focus 2: POIs all outside the polygons (or without voci)."""
    enabled, disabled = _Spy(), _Spy()
    out = await generate_analysis(_ctx(_poi(), _poi("node/2")), enabled, istat=True)
    await generate_analysis(_ctx(_poi(), _poi("node/2")), disabled, istat=False)
    assert enabled.calls == disabled.calls
    assert out.istat_attivo is False and out.controllo_istat is None


async def test_figures_check_filters_the_narrativa_and_keeps_the_raw() -> None:
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        "Banca node/1 conta 46 rapine in banca. "
        "Rischio di rapina per Banca node/1. "
        "Secondo l'ISTAT, nel Comune di Roma le rapine in banca sono in calo.\n"
    )
    out = await generate_analysis(
        _ctx(_poi(istat=istat_poi(BANK_ROBBERIES))), _Spy(text), istat=True
    )
    assert out.narrativa_grezza == text
    assert "conta 46" not in out.narrativa
    assert "Rischio di rapina per Banca node/1." in out.narrativa
    assert out.istat_frasi_scartate == 1
    assert out.controllo_istat is not None
    assert "controllo_istat" not in out.model_dump()
    # #365: the ISTAT data in words stays in the [ONTOLOGIA] block, no [ISTAT]
    sources_id = parse_source_prose(out.narrativa)
    assert sources_id.istat == ""
    assert sources_id.ontologia.endswith("le rapine in banca sono in calo.")


def test_a_voce_shared_by_two_poi_appears_once() -> None:
    contesto = build_context(
        _ctx(
            _poi("node/1", istat_poi(BANK_ROBBERIES)),
            _poi("node/2", istat_poi(BANK_ROBBERIES)),
        ),
        istat=True,
    )
    assert contesto.testo.count("rapine in banca:") == 1
    assert "POI coinvolti" not in contesto.testo
    assert contesto.text_without_istat == build_context_str(
        _ctx(
            _poi("node/1", istat_poi(BANK_ROBBERIES)),
            _poi("node/2", istat_poi(BANK_ROBBERIES)),
        )
    )


def test_reserve_leaves_room_for_the_block_on_a_truncated_context() -> None:
    """Decision 10: without a reserve the block would disappear on the already
    truncated zones."""
    pois = [_poi(f"node/{i}", istat_poi(BANK_ROBBERIES)) for i in range(30)]
    budget = 1500
    disabled = build_context(_ctx(*pois), context_budget_tokens=budget)
    enabled = build_context(_ctx(*pois), context_budget_tokens=budget, istat=True)
    assert disabled.included_poi_count < 30  # already truncated with ISTAT off
    assert enabled.blocco_istat.testo != ""
    assert enabled.included_poi_count < disabled.included_poi_count
    assert _estimate_tokens(enabled.testo) <= budget
    assert 0 < ISTAT_RESERVE_MAX_TOKENS <= 1200


async def test_rows_lost_in_truncation_falls_back_to_the_off_branch() -> None:
    """Fix round 1 - IMPORTANT 1 (spec 4.10): the ISTAT rows are only on the least
    relevant POI, which the reduced budget reserved for the ISTAT attempt discards
    from the truncation. The block recomputed on the selected POIs then stays
    empty, but going back to the off branch ONLY for the block (leaving the
    selection already made with the smaller budget) would give fewer POIs and no
    note of how many a run with the switch off from the start would have: the
    whole request must be redone with the SYSTEM_PROMPT allowance, not just the
    block."""
    pois = [_poi(f"node/{i}") for i in range(5)] + [
        _poi("node/5", istat_poi(BANK_ROBBERIES))
    ]
    enabled, disabled = _Spy(), _Spy()
    out = await generate_analysis(
        _ctx(*pois), enabled, istat=True, request_token_budget=2390, max_tokens=0
    )
    await generate_analysis(
        _ctx(*pois), disabled, istat=False, request_token_budget=2390, max_tokens=0
    )
    assert enabled.calls == disabled.calls
    assert out.istat_attivo is False and out.controllo_istat is None
    assert "POI piu' rilevanti" not in enabled.calls[0][1]  # no POI discarded


def test_voci_truncation_note_does_not_touch_the_quoted_figure() -> None:
    """Fix round 1 - MINOR 2: when ``istat_block_for_zone`` cuts some voci because of
    the budget, the note "NB: per limiti di lunghezza ..." ends up in the zone
    user_content and its number stays an ALLOWED figure (it appears in the ISTAT
    DATA block itself): a sentence quoting it is not discarded by the figures
    check."""
    pois = [
        # #365: 22 voci, one more than those that fit in the reserve (rows in words, D7:
        # shorter than those with the figures).
        _poi(f"node/{i}", istat_poi(make_row(f"V{i:02d}", label=f"voce numero {i}")))
        for i in range(22)
    ]
    budget = _estimate_tokens(build_context_str(_ctx(*pois))) + 1200
    contesto = build_context(_ctx(*pois), context_budget_tokens=budget, istat=True)
    assert contesto.included_poi_count == 22  # no POI discarded, only the voci
    assert contesto.blocco_istat.voci_tagliate == 1
    note = "NB: per limiti di lunghezza 1 voce ISTAT non e' riportata."
    assert note in contesto.testo

    narrativa = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        "Rischio di rapina per Banca node/0. "
        "Nel Comune di Roma 1 voce ISTAT non compare per limiti di spazio.\n"
    )
    filtered_text, check_outcome = apply_check(
        narrativa,
        block=contesto.blocco_istat,
        spans=source_block_spans(narrativa),
        context=contesto.text_without_istat,
    )
    assert check_outcome is not None
    assert filtered_text == narrativa
    assert check_outcome.frasi_scartate == 0


async def test_data_version_from_the_bound_set_without_monkeypatch() -> None:
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
        out = await generate_analysis(
            _ctx(_poi(istat=istat_poi(BANK_ROBBERIES))), _Spy(), istat=True
        )
    assert (out.istat_attivo, out.istat_versione_dati) == (True, "X")


# --- #366: the model chooses the voci, the app composes the sentences ---------

_SELECTION = "SCELTA DATI ISTAT:\nRapina in banca | rapine in banca | alto\n"


async def test_selection_prompt_and_request_without_a_rule_in_words() -> None:
    spy = _Spy()
    await generate_analysis(
        _ctx(_poi(istat=istat_poi(BANK_ROBBERIES))),
        spy,
        istat=True,
        istat_scelta=True,
    )
    system, user = spy.calls[0]
    assert system == SYSTEM_PROMPT_ISTAT_SELECTION
    assert system != SYSTEM_PROMPT_ISTAT
    assert RULE_ISTAT_SELECTION in system
    assert "NON scrivere frasi sui dati ISTAT" in system
    assert "DATI ISTAT" in user


async def test_selection_off_or_istat_off_changes_nothing() -> None:
    base, selection_without_istat, istat_without_selection = _Spy(), _Spy(), _Spy()
    ctx = _ctx(_poi(istat=istat_poi(BANK_ROBBERIES)))
    await generate_analysis(ctx, base, istat=False)
    await generate_analysis(
        ctx, selection_without_istat, istat=False, istat_scelta=True
    )
    await generate_analysis(ctx, istat_without_selection, istat=True)
    assert base.calls == selection_without_istat.calls
    assert istat_without_selection.calls[0][0] == SYSTEM_PROMPT_ISTAT


async def test_selection_the_app_composes_the_sentence_and_removes_the_block() -> None:
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRischio di rapina per Banca "
        "node/1.\n\nRischi dal contesto [CONTESTO]\nZona di transito.\n\n" + _SELECTION
    )
    out = await generate_analysis(
        _ctx(_poi(istat=istat_poi(BANK_ROBBERIES))),
        _Spy(text),
        istat=True,
        istat_scelta=True,
    )
    assert "SCELTA DATI ISTAT" not in out.narrativa
    assert out.narrativa_grezza == text
    sources_id = parse_source_prose(out.narrativa)
    assert sources_id.ontologia.startswith("Rischio di rapina per Banca node/1.")
    assert (
        "Secondo i dati ISTAT del Comune di Roma (2024), la voce «rapine in banca» "
        "(rischio: Rapina in banca) ha un tasso più alto di quello italiano e un "
        "andamento in calo dal 2014." in sources_id.ontologia
    )
    assert sources_id.contesto == "Zona di transito."
    assert [s.hazard for s in out.istat_scelta] == ["Bank_robbery"]
    assert out.istat_scelta_scarti == SelectionDiscards()
    assert "istat_scelta_scarti" not in out.model_dump()
    assert "istat_scelta" not in out.model_dump()


async def test_selection_unanchored_produces_no_sentences() -> None:
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nProsa.\n\n"
        "SCELTA DATI ISTAT:\nRapina in banca | furti d'auto | alto\n"
    )
    out = await generate_analysis(
        _ctx(_poi(istat=istat_poi(BANK_ROBBERIES))),
        _Spy(text),
        istat=True,
        istat_scelta=True,
    )
    assert out.narrativa == "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nProsa."
    assert out.istat_scelta == []
    assert out.istat_scelta_scarti.voce_non_nel_blocco == 1


async def test_selection_the_check_remains_a_safety_net_on_the_model_text() -> None:
    text = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        "Banca node/1 conta 46 rapine in banca. "
        "Rischio di rapina per Banca node/1.\n\n" + _SELECTION
    )
    out = await generate_analysis(
        _ctx(_poi(istat=istat_poi(BANK_ROBBERIES))),
        _Spy(text),
        istat=True,
        istat_scelta=True,
    )
    assert "conta 46" not in out.narrativa
    assert out.istat_frasi_scartate == 1
    assert "andamento in calo" in out.narrativa
