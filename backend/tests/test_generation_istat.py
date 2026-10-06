"""Generation layer con i dati ISTAT (#345): parsing [ISTAT], contesto, filtro."""

from __future__ import annotations

from crime_risk_analyzer.istat.cifre import SpanBlocco
from crime_risk_analyzer.rag.generation import (
    ISTAT_BLOCK_HEADER,
    SourceProse,
    parse_source_prose,
    source_block_spans,
)

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
