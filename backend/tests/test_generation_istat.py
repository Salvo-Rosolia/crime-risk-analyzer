"""Generation layer con i dati ISTAT (#345, #365): parsing, contesto, filtro.

Da #365 il prompt non chiede piu' il blocco [ISTAT]: il parser lo riconosce ancora
per le narrative scritte prima, e i test di parsing usano quella forma.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from crime_risk_analyzer.istat.cifre import SpanBlocco, applica_controllo
from crime_risk_analyzer.istat.righe import IstatPoi
from crime_risk_analyzer.llm.client import LLMResponse
from crime_risk_analyzer.rag import generation as generation_mod
from crime_risk_analyzer.rag.generation import (
    ISTAT_BLOCK_HEADER,
    ISTAT_RISERVA_MAX_TOKEN,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_ISTAT,
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
from tests.istat._fattorie import BANKROB, RAPINE_IN_BANCA, istat_poi, riga

#: Narrativa nella forma di #345, col terzo blocco [ISTAT] (record vecchi, D4).
_NARRATIVA = (
    "Sintesi della zona.\n\n"
    "Rischi da ontologia [ONTOLOGIA]\nRapina in banca per Banca A.\n\n"
    "Rischi dal contesto [CONTESTO]\nZona di transito.\n\n"
    f"{ISTAT_BLOCK_HEADER}\nLe rapine in banca sono 3 nel 2024.\n"
)


def test_parse_separa_il_terzo_blocco_istat() -> None:
    assert parse_source_prose(_NARRATIVA) == SourceProse(
        overview="Sintesi della zona.",
        ontologia="Rapina in banca per Banca A.",
        contesto="Zona di transito.",
        istat="Le rapine in banca sono 3 nel 2024.",
    )


def test_parse_riconosce_intestazione_istat_decorata_e_ignora_il_token_in_frase() -> (
    None
):
    """Review Focus 4."""
    testo = (
        "Sintesi: il tag [ISTAT] compare anche qui, dentro una frase.\n\n"
        "Rischi da ontologia [ONTOLOGIA]\nRapina.\n\n"
        "**Dati statistici ISTAT [ISTAT]**\nI furti sono 3.\n"
    )
    fonti = parse_source_prose(testo)
    assert fonti.overview.startswith("Sintesi: il tag [ISTAT]")
    assert fonti.ontologia == "Rapina."
    assert fonti.istat == "I furti sono 3."


def test_narrative_senza_istat_restano_identiche() -> None:
    testo = "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n"
    assert parse_source_prose(testo).istat == ""
    assert parse_source_prose(testo).ontologia == "Rapina."


def test_spans_dei_blocchi() -> None:
    spans = source_block_spans(_NARRATIVA)
    assert [s.campo for s in spans] == ["ontologia", "contesto", "istat"]
    assert all(isinstance(s, SpanBlocco) for s in spans)
    istat = spans[2]
    assert _NARRATIVA[istat.inizio_riga : istat.inizio] == f"{ISTAT_BLOCK_HEADER}\n"
    assert istat.fine == len(_NARRATIVA)
    assert spans[0].fine == spans[1].inizio_riga
    assert source_block_spans("solo testo") == []


class _Spia:
    def __init__(
        self, testo: str = "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n"
    ) -> None:
        self.testo = testo
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


async def test_istat_spento_prompt_identico_anche_con_righe_in_cache() -> None:
    """Review Focus 3: il contesto in cache porta le righe, l'interruttore e' spento."""
    con_righe, senza = _Spia(), _Spia()
    out = await generate_analysis(
        _ctx(_poi(istat=istat_poi(RAPINE_IN_BANCA))), con_righe, istat=False
    )
    await generate_analysis(_ctx(_poi()), senza)
    assert con_righe.calls == senza.calls
    assert con_righe.calls[0][0] == SYSTEM_PROMPT
    assert (out.istat_attivo, out.istat_frasi_scartate, out.controllo_istat) == (
        False,
        0,
        None,
    )
    assert out.narrativa == out.narrativa_grezza


async def test_istat_acceso_mette_il_blocco_fra_vocabolario_e_poi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generation_mod, "versione_dati", lambda: "2026-10-06")
    spia = _Spia()
    out = await generate_analysis(
        _ctx(_poi(istat=istat_poi(RAPINE_IN_BANCA))), spia, istat=True
    )
    system, user = spia.calls[0]
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


async def test_voce_sotto_i_20_delitti_non_accende_istat() -> None:
    """#365 D2: con le sole 3 rapine in banca non c'e' blocco DATI ISTAT, e il
    prompt e' quello di ISTAT spento."""
    acceso, spento = _Spia(), _Spia()
    out = await generate_analysis(
        _ctx(_poi(istat=istat_poi(BANKROB))), acceso, istat=True
    )
    await generate_analysis(_ctx(_poi()), spento, istat=False)
    assert acceso.calls == spento.calls
    assert out.istat_attivo is False


async def test_istat_acceso_senza_righe_e_identico_a_spento() -> None:
    """Review Focus 2: POI tutti fuori dai poligoni (o senza voci)."""
    acceso, spento = _Spia(), _Spia()
    out = await generate_analysis(_ctx(_poi(), _poi("node/2")), acceso, istat=True)
    await generate_analysis(_ctx(_poi(), _poi("node/2")), spento, istat=False)
    assert acceso.calls == spento.calls
    assert out.istat_attivo is False and out.controllo_istat is None


async def test_controllo_cifre_filtra_la_narrativa_e_conserva_il_grezzo() -> None:
    testo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        "Banca node/1 conta 46 rapine in banca. "
        "Rischio di rapina per Banca node/1. "
        "Secondo l'ISTAT, nel Comune di Roma le rapine in banca sono in calo.\n"
    )
    out = await generate_analysis(
        _ctx(_poi(istat=istat_poi(RAPINE_IN_BANCA))), _Spia(testo), istat=True
    )
    assert out.narrativa_grezza == testo
    assert "conta 46" not in out.narrativa
    assert "Rischio di rapina per Banca node/1." in out.narrativa
    assert out.istat_frasi_scartate == 1
    assert out.controllo_istat is not None
    assert "controllo_istat" not in out.model_dump()
    # #365: i dati ISTAT a parole restano nel blocco [ONTOLOGIA], nessun [ISTAT]
    fonti = parse_source_prose(out.narrativa)
    assert fonti.istat == ""
    assert fonti.ontologia.endswith("le rapine in banca sono in calo.")


def test_una_voce_condivisa_da_due_poi_compare_una_volta() -> None:
    contesto = build_context(
        _ctx(
            _poi("node/1", istat_poi(RAPINE_IN_BANCA)),
            _poi("node/2", istat_poi(RAPINE_IN_BANCA)),
        ),
        istat=True,
    )
    assert contesto.testo.count("rapine in banca:") == 1
    assert "POI coinvolti" not in contesto.testo
    assert contesto.testo_senza_istat == build_context_str(
        _ctx(
            _poi("node/1", istat_poi(RAPINE_IN_BANCA)),
            _poi("node/2", istat_poi(RAPINE_IN_BANCA)),
        )
    )


def test_riserva_lascia_spazio_al_blocco_su_un_contesto_troncato() -> None:
    """Decisione 10: senza riserva il blocco sparirebbe sulle zone gia' troncate."""
    pois = [_poi(f"node/{i}", istat_poi(RAPINE_IN_BANCA)) for i in range(30)]
    budget = 1500
    spento = build_context(_ctx(*pois), context_budget_tokens=budget)
    acceso = build_context(_ctx(*pois), context_budget_tokens=budget, istat=True)
    assert spento.poi_inclusi < 30  # gia' troncato a ISTAT spento
    assert acceso.blocco_istat.testo != ""
    assert acceso.poi_inclusi < spento.poi_inclusi
    assert _estimate_tokens(acceso.testo) <= budget
    assert 0 < ISTAT_RISERVA_MAX_TOKEN <= 1200


async def test_righe_perse_nel_troncamento_torna_al_ramo_spento() -> None:
    """Fix round 1 - IMPORTANT 1 (spec 4.10): le righe ISTAT ci sono solo sul POI
    meno rilevante, che il budget ridotto riservato al tentativo ISTAT scarta dal
    troncamento. Il blocco ricalcolato sui POI selezionati resta allora vuoto, ma
    tornare al ramo spento SOLO per il blocco (lasciando la selezione gia' fatta
    col budget piu' piccolo) darebbe meno POI e nessuna nota di quanti ne
    avrebbe un run con l'interruttore spento fin dall'inizio: la richiesta intera
    va rifatta con l'allowance di SYSTEM_PROMPT, non solo il blocco."""
    pois = [_poi(f"node/{i}") for i in range(5)] + [
        _poi("node/5", istat_poi(RAPINE_IN_BANCA))
    ]
    acceso, spento = _Spia(), _Spia()
    out = await generate_analysis(
        _ctx(*pois), acceso, istat=True, request_token_budget=2390, max_tokens=0
    )
    await generate_analysis(
        _ctx(*pois), spento, istat=False, request_token_budget=2390, max_tokens=0
    )
    assert acceso.calls == spento.calls
    assert out.istat_attivo is False and out.controllo_istat is None
    assert "POI piu' rilevanti" not in acceso.calls[0][1]  # nessun POI scartato


def test_nota_taglio_delle_voci_non_tocca_la_cifra_citata() -> None:
    """Fix round 1 - MINOR 2: quando ``blocco_istat_zona`` taglia delle voci per
    budget, la nota "NB: per limiti di lunghezza ..." finisce nello user_content
    di zona e il suo numero resta una cifra AMMESSA (compare nel blocco DATI ISTAT
    stesso): una frase che lo cita non viene scartata dal controllo cifre."""
    pois = [
        # #365: 22 voci, una in piu' di quelle che stanno nella riserva (righe a
        # parole, D7: piu' corte di quelle con le cifre).
        _poi(f"node/{i}", istat_poi(riga(f"V{i:02d}", label=f"voce numero {i}")))
        for i in range(22)
    ]
    budget = _estimate_tokens(build_context_str(_ctx(*pois))) + 1200
    contesto = build_context(_ctx(*pois), context_budget_tokens=budget, istat=True)
    assert contesto.poi_inclusi == 22  # nessun POI scartato, solo le voci
    assert contesto.blocco_istat.voci_tagliate == 1
    nota = "NB: per limiti di lunghezza 1 voce ISTAT non e' riportata."
    assert nota in contesto.testo

    narrativa = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        "Rischio di rapina per Banca node/0. "
        "Nel Comune di Roma 1 voce ISTAT non compare per limiti di spazio.\n"
    )
    filtrata, esito = applica_controllo(
        narrativa,
        blocco=contesto.blocco_istat,
        spans=source_block_spans(narrativa),
        contesto=contesto.testo_senza_istat,
    )
    assert esito is not None
    assert filtrata == narrativa
    assert esito.frasi_scartate == 0


async def test_versione_dati_dal_set_legato_senza_monkeypatch() -> None:
    attivo = default_set()
    custom = dataclasses.replace(
        attivo,
        id="x",
        kind="custom",
        istat=IstatSource(
            dati=attivo.istat.dati,
            mappatura=attivo.istat.mappatura,
            voci_rottura=attivo.istat.voci_rottura,
            versione="X",
        ),
    )
    with bind(custom):
        out = await generate_analysis(
            _ctx(_poi(istat=istat_poi(RAPINE_IN_BANCA))), _Spia(), istat=True
        )
    assert (out.istat_attivo, out.istat_versione_dati) == (True, "X")
