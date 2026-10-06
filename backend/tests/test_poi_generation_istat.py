"""Narrativa del POI con i dati ISTAT (#345, spec 4.5)."""

from __future__ import annotations

import pytest

from crime_risk_analyzer.istat.blocco import INTESTAZIONE_DATI_ISTAT
from crime_risk_analyzer.istat.righe import IstatPoi
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
from tests.istat._fattorie import BANKROB, istat_poi


class _Spia:
    def __init__(self, testo: str) -> None:
        self.testo = testo
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        self.calls.append((system_prompt, user_content))
        return LLMResponse(
            text=self.testo,
            llm_used="openai/gpt-oss-120b",
            tokens_input=1,
            tokens_output=1,
            cache_hit=False,
            temperature=0.0,
            seed=0,
            prompt_hash="h",
        )


_RISCHI = [
    GroundedRisk(
        hazard="Bank_robbery",
        tag="ONTOLOGIA",
        confidence="verificato",
        source="Bank → havingHazard → Bank_robbery",
    )
]


def _contesto(istat: IstatPoi | None = None) -> str:
    return build_poi_context_str(
        citta="Roma",
        zona="Colosseo",
        poi_name="Banca A",
        poi_label_it="Banca",
        risks=_RISCHI,
        vulnerabilities=[],
        sparql_path="Bank → havingHazard → Bank_robbery",
        neighbours=[NeighbourPoi(name="Liceo", label_it="Scuola", distance_m=40)],
        zone_summary="2 punti di interesse nella zona.",
        istat=istat,
    )


async def _genera(
    testo: str, istat: IstatPoi | None
) -> tuple[_Spia, poi_mod.PoiGenerationResult]:
    spia = _Spia(testo)
    out = await generate_poi_narrative(
        citta="Roma",
        zona="Colosseo",
        poi_name="Banca A",
        poi_label_it="Banca",
        risks=_RISCHI,
        vulnerabilities=[],
        sparql_path="Bank → havingHazard → Bank_robbery",
        neighbours=[NeighbourPoi(name="Liceo", label_it="Scuola", distance_m=40)],
        zone_summary="2 punti di interesse nella zona.",
        llm_client=spia,
        istat=istat,
    )
    return spia, out


def test_contesto_senza_istat_invariato() -> None:
    senza = _contesto()
    assert "DATI ISTAT" not in senza
    assert senza == build_poi_context_str(
        citta="Roma",
        zona="Colosseo",
        poi_name="Banca A",
        poi_label_it="Banca",
        risks=_RISCHI,
        vulnerabilities=[],
        sparql_path="Bank → havingHazard → Bank_robbery",
        neighbours=[NeighbourPoi(name="Liceo", label_it="Scuola", distance_m=40)],
        zone_summary="2 punti di interesse nella zona.",
    )


def test_contesto_con_istat_prima_del_vicinato_senza_poi_coinvolti() -> None:
    testo = _contesto(istat_poi(BANKROB))
    assert testo.index(INTESTAZIONE_DATI_ISTAT) < testo.index("VICINATO")
    assert "rapine in banca (voce ISTAT BANKROB)" in testo
    assert "POI coinvolti" not in testo


async def test_generazione_con_istat_usa_la_variante_e_filtra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(poi_mod, "versione_dati", lambda: "2026-10-06")
    testo = (
        "[ONTOLOGIA]\nLa Banca A conta 46 rapine in banca. Rischio di rapina.\n\n"
        "[CONTESTO]\nZona di transito.\n\n[ISTAT]\n"
        "Le rapine in banca sono 3 nel 2024 (fonte ISTAT, Comune di Roma, 2024).\n"
    )
    spia, out = await _genera(testo, istat_poi(BANKROB))
    assert spia.calls[0][0] == POI_SYSTEM_PROMPT_ISTAT
    assert out.narrativa_grezza == testo
    assert "46" not in out.narrativa
    assert out.narrativa_fonti.istat.startswith("Le rapine in banca sono 3")
    assert (out.istat_attivo, out.istat_versione_dati, out.istat_frasi_scartate) == (
        True,
        "2026-10-06",
        1,
    )


async def test_generazione_senza_istat_come_prima() -> None:
    spia, out = await _genera("[ONTOLOGIA]\nRischio di rapina.\n", None)
    assert spia.calls[0][0] == POI_SYSTEM_PROMPT
    assert out.narrativa == "[ONTOLOGIA]\nRischio di rapina.\n"
    assert (out.istat_attivo, out.istat_frasi_scartate) == (False, 0)
