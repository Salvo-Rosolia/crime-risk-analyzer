"""ISTAT metrics (#345, version 4 from #369): deterministic, on the raw text."""

from __future__ import annotations

import pytest

from crime_risk_analyzer.eval.istat_metrics import (
    ISTAT_METRICS_VERSION,
    compute_istat_metrics,
    excluded_sentences_without_item,
    sum_istat_metrics,
)
from crime_risk_analyzer.eval.schema import IstatMetrics
from crime_risk_analyzer.istat.block import istat_block_for_poi
from crime_risk_analyzer.istat.figures import CheckOutcome, check_figures
from crime_risk_analyzer.rag.generation import source_block_spans
from tests.istat._factories import BANK_ROBBERIES, istat_poi, make_row

_BLOCK = istat_block_for_poi(istat_poi(make_row(), BANK_ROBBERIES))


def _metrics(text: str, frasi_escluse_m1: int = 0) -> IstatMetrics:
    outcome = check_figures(
        text,
        blocks=source_block_spans(text),
        istat_block=_BLOCK.testo,
        context_without_istat="ZONA: Colosseo",
        rows=_BLOCK.righe,
    )
    return compute_istat_metrics(outcome, frasi_escluse_m1=frasi_escluse_m1)


def test_version_4_from_369() -> None:
    """ISTAT sentences, cited items and matches change meaning with #365;
    with #368 and then #369 M1 grades another text, so the version goes up again."""
    assert ISTAT_METRICS_VERSION == 4
    m = _metrics("Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n", 2)
    assert (m.versione, m.frasi_escluse_m1) == (4, 2)


def test_records_before_version_4_have_no_excluded_sentences() -> None:
    m = _metrics("Rischi da ontologia [ONTOLOGIA]\nRapina.\n")
    old = IstatMetrics.model_validate(
        {k: v for k, v in m.model_dump().items() if k != "frasi_escluse_m1"}
    )
    assert old.frasi_escluse_m1 == 0


def test_earlier_records_are_version_1() -> None:
    old = {
        "cifre_totali": 4,
        "cifre_istat_corrette": 3,
        "precisione_cifre": 0.75,
        "frasi_scartabili": 1,
        "voci_fornite": 3,
        "voci_citate": 2,
        "frasi_istat": 2,
        "frasi_istat_con_luogo": 2,
        "direzioni_totali": 1,
        "direzioni_coerenti": 1,
        "corrispondenze_non_dichiarate": 0,
        "numeri_in_lettere": 0,
    }
    m = IstatMetrics.model_validate(old)
    assert (m.versione, m.cifre_istat, m.confronti_totali) == (1, 0, 0)


def test_metrics_on_a_typical_narrative() -> None:
    text = (
        "Sintesi con 134.169 furti.\n\n"
        "Rischi da ontologia [ONTOLOGIA]\n"
        "Secondo i dati ISTAT del Comune di Roma i furti hanno un tasso piu' alto "
        "di quello italiano e sono in calo, ma la voce ISTAT non coincide con il "
        "rischio. "
        "Secondo l'ISTAT le rapine in banca sono sotto la media italiana. "
        "Per l'ISTAT a Roma i furti sono il doppio di quanto si pensi. "
        "Rapina in banca per la Banca A.\n"
    )
    m = _metrics(text)
    assert m.cifre_totali == 1
    assert m.cifre_istat == 1  # "134.169" in the synthesis: written, hence removed
    # removed: the synthesis (figure) and the bank robberies (place missing)
    assert m.frasi_scartabili == 2
    # sentences that speak of the ISTAT datum, in any block
    assert (m.frasi_istat, m.frasi_istat_con_luogo) == (4, 2)
    # items named in ISTAT sentences KEPT by the filter: only thefts
    assert (m.voci_fornite, m.voci_citate) == (2, 1)
    assert (m.direzioni_totali, m.direzioni_coerenti) == (1, 1)
    # "piu' alto" on thefts (consistent), "sotto la media" on robberies (opposite:
    # 1.7 against 0.5 is higher)
    assert (m.confronti_totali, m.confronti_coerenti) == (2, 1)
    # thefts: item broader than the risk; declared only in [ONTOLOGIA] at the
    # first sentence, not in the synthesis nor in the "double" sentence (raw text:
    # the removed sentences count too)
    assert m.corrispondenze_non_dichiarate == 2
    assert m.numeri_in_lettere == 1


def test_istat_sentences_also_in_a_leftover_istat_block() -> None:
    m = _metrics(
        "Sintesi.\n\nDati statistici ISTAT [ISTAT]\n"
        "Nel Comune di Roma, secondo l'ISTAT, i furti sono in calo.\n"
    )
    assert (m.frasi_istat, m.frasi_istat_con_luogo, m.frasi_scartabili) == (1, 1, 0)


def test_sentence_place_matches_whole_word() -> None:
    """R7 (review 2): "romano" does not name "Roma"."""
    m = _metrics(
        "Rischi da ontologia [ONTOLOGIA]\nSecondo l'ISTAT nel territorio romano i "
        "furti sono in calo.\n"
    )
    assert (m.frasi_istat, m.frasi_istat_con_luogo) == (1, 0)


def test_sum_across_repetitions() -> None:
    a = _metrics("Rischi da ontologia [ONTOLOGIA]\nI furti sono 134.169.\n")
    b = _metrics(
        "Rischi da ontologia [ONTOLOGIA]\nSecondo l'ISTAT a Roma i furti sono "
        "sopra la media italiana.\n",
        frasi_escluse_m1=1,
    )
    s = sum_istat_metrics([a, None, b])
    assert s is not None
    assert (s.versione, s.cifre_totali, s.cifre_istat) == (4, 1, 1)
    assert (s.frasi_istat, s.confronti_totali, s.confronti_coerenti) == (2, 1, 1)
    assert s.frasi_escluse_m1 == 1
    assert sum_istat_metrics([None, None]) is None


def test_sum_rejects_different_versions() -> None:
    a = _metrics("Rischi da ontologia [ONTOLOGIA]\nRapina.\n")
    with pytest.raises(ValueError, match="versioni"):
        sum_istat_metrics([a, a.model_copy(update={"versione": 1})])


def test_explicit_and_inherited_place_counted_separately() -> None:
    """Fix 3: the list sentence that inherits the place does not count as with place."""
    m = _metrics(
        "Rischi da ontologia [ONTOLOGIA]\nSecondo l'ISTAT nel Comune di Roma i "
        "furti sono in calo. I furti hanno un tasso piu' alto dal 2014.\n"
    )
    assert (m.frasi_istat, m.frasi_istat_con_luogo) == (2, 1)
    assert m.frasi_istat_con_luogo_ereditato == 1
    assert m.frasi_scartabili == 0


def test_item_codes_written_by_the_model() -> None:
    """Question 2 of the review: the row codes are counted (expected 0)."""
    m = _metrics(
        "Rischi da ontologia [ONTOLOGIA]\nSecondo l'ISTAT nel Comune di Roma la "
        "voce THEFT e' in calo; BANKROB pure.\n"
    )
    assert m.codici_voce == 2
    assert _metrics("Rischi da ontologia [ONTOLOGIA]\nRapina.\n").codici_voce == 0
    old = IstatMetrics.model_validate(
        {k: v for k, v in m.model_dump().items() if k != "codici_voce"}
    )
    assert old.codici_voce == 0


_EXCLUDED = [
    "Secondo l'ISTAT a Roma i furti sono in calo",
    "Secondo i dati ISTAT a Roma sono in aumento i sequestri di persona",
    "Secondo i dati ISTAT a Roma sono in aumento i sequestri di persona",
]


def _outcome(text: str = "Rischi da ontologia [ONTOLOGIA]\nRapina.\n") -> CheckOutcome:
    return check_figures(
        text,
        blocks=source_block_spans(text),
        istat_block=_BLOCK.testo,
        context_without_istat="ZONA: Colosseo",
        rows=_BLOCK.righe,
    )


def test_excluded_sentences_without_item_of_prompt_rows() -> None:
    """#378: the excluded sentences that name no item of the rows passed to the
    model, in order and with the duplicates of the excluded ones."""
    assert excluded_sentences_without_item(_EXCLUDED, _outcome()) == _EXCLUDED[1:]
    assert excluded_sentences_without_item([], _outcome()) == []


def test_metrics_count_excluded_without_item() -> None:
    m = compute_istat_metrics(
        _outcome(), frasi_escluse_m1=3, frasi_escluse_senza_voce=2
    )
    assert (m.versione, m.frasi_escluse_m1, m.frasi_escluse_senza_voce) == (4, 3, 2)


def test_record_without_the_count_of_excluded_without_item() -> None:
    """Records written before #378 do not have the field: ``None``, not 0."""
    m = _metrics("Rischi da ontologia [ONTOLOGIA]\nRapina.\n")
    assert m.frasi_escluse_senza_voce is None
    old = IstatMetrics.model_validate(
        {k: v for k, v in m.model_dump().items() if k != "frasi_escluse_senza_voce"}
    )
    assert old.frasi_escluse_senza_voce is None


def test_sum_of_excluded_without_item() -> None:
    a = compute_istat_metrics(
        _outcome(), frasi_escluse_m1=2, frasi_escluse_senza_voce=1
    )
    b = compute_istat_metrics(
        _outcome(), frasi_escluse_m1=1, frasi_escluse_senza_voce=0
    )
    s = sum_istat_metrics([a, None, b])
    assert s is not None
    assert (s.frasi_escluse_m1, s.frasi_escluse_senza_voce) == (3, 1)
    # One repetition without the count is enough: the sum does not invent it.
    old_metrics = b.model_copy(update={"frasi_escluse_senza_voce": None})
    s = sum_istat_metrics([a, old_metrics])
    assert s is not None
    assert (s.frasi_escluse_m1, s.frasi_escluse_senza_voce) == (3, None)
