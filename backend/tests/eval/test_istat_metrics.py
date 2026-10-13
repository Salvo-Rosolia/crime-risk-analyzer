"""Metriche ISTAT (#345, versione 4 da #369): deterministiche, sul testo grezzo."""

from __future__ import annotations

import pytest

from crime_risk_analyzer.eval.istat_metrics import (
    ISTAT_METRICS_VERSION,
    compute_istat_metrics,
    somma_istat_metrics,
)
from crime_risk_analyzer.eval.schema import IstatMetrics
from crime_risk_analyzer.istat.blocco import blocco_istat_poi
from crime_risk_analyzer.istat.cifre import controlla_cifre
from crime_risk_analyzer.rag.generation import source_block_spans
from tests.istat._fattorie import RAPINE_IN_BANCA, istat_poi, riga

_BLOCCO = blocco_istat_poi(istat_poi(riga(), RAPINE_IN_BANCA))


def _metriche(testo: str, frasi_escluse_m1: int = 0) -> IstatMetrics:
    esito = controlla_cifre(
        testo,
        blocchi=source_block_spans(testo),
        blocco_istat=_BLOCCO.testo,
        contesto_senza_istat="ZONA: Colosseo",
        righe=_BLOCCO.righe,
    )
    return compute_istat_metrics(esito, frasi_escluse_m1=frasi_escluse_m1)


def test_versione_4_dal_369() -> None:
    """Frasi ISTAT, voci citate e corrispondenze cambiano significato con #365;
    con #368 e poi #369 M1 grada un altro testo, quindi la versione sale ancora."""
    assert ISTAT_METRICS_VERSION == 4
    m = _metriche("Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n", 2)
    assert (m.versione, m.frasi_escluse_m1) == (4, 2)


def test_i_record_prima_della_versione_4_non_hanno_le_frasi_escluse() -> None:
    m = _metriche("Rischi da ontologia [ONTOLOGIA]\nRapina.\n")
    vecchio = IstatMetrics.model_validate(
        {k: v for k, v in m.model_dump().items() if k != "frasi_escluse_m1"}
    )
    assert vecchio.frasi_escluse_m1 == 0


def test_i_record_scritti_prima_sono_versione_1() -> None:
    vecchio = {
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
    m = IstatMetrics.model_validate(vecchio)
    assert (m.versione, m.cifre_istat, m.confronti_totali) == (1, 0, 0)


def test_metriche_su_una_narrativa_tipica() -> None:
    testo = (
        "Sintesi con 134.169 furti.\n\n"
        "Rischi da ontologia [ONTOLOGIA]\n"
        "Secondo i dati ISTAT del Comune di Roma i furti hanno un tasso piu' alto "
        "di quello italiano e sono in calo, ma la voce ISTAT non coincide con il "
        "rischio. "
        "Secondo l'ISTAT le rapine in banca sono sotto la media italiana. "
        "Per l'ISTAT a Roma i furti sono il doppio di quanto si pensi. "
        "Rapina in banca per la Banca A.\n"
    )
    m = _metriche(testo)
    assert m.cifre_totali == 1
    assert m.cifre_istat == 1  # "134.169" nella sintesi: scritta, quindi tolta
    # tolte: la sintesi (cifra) e le rapine in banca (luogo mancante)
    assert m.frasi_scartabili == 2
    # frasi che parlano del dato ISTAT, in qualunque blocco
    assert (m.frasi_istat, m.frasi_istat_con_luogo) == (4, 2)
    # voci nominate in frasi ISTAT TENUTE dal filtro: solo i furti
    assert (m.voci_fornite, m.voci_citate) == (2, 1)
    assert (m.direzioni_totali, m.direzioni_coerenti) == (1, 1)
    # "piu' alto" sui furti (coerente), "sotto la media" sulle rapine (contrario:
    # 1,7 contro 0,5 e' piu' alto)
    assert (m.confronti_totali, m.confronti_coerenti) == (2, 1)
    # furti: voce piu' ampia del rischio; dichiarato solo in [ONTOLOGIA] alla
    # prima frase, non nella sintesi ne' nella frase del "doppio" (testo grezzo:
    # contano anche le frasi tolte)
    assert m.corrispondenze_non_dichiarate == 2
    assert m.numeri_in_lettere == 1


def test_frasi_istat_anche_in_un_blocco_istat_residuo() -> None:
    m = _metriche(
        "Sintesi.\n\nDati statistici ISTAT [ISTAT]\n"
        "Nel Comune di Roma, secondo l'ISTAT, i furti sono in calo.\n"
    )
    assert (m.frasi_istat, m.frasi_istat_con_luogo, m.frasi_scartabili) == (1, 1, 0)


def test_luogo_della_frase_a_parola_intera() -> None:
    """R7 (review 2): "romano" non nomina "Roma"."""
    m = _metriche(
        "Rischi da ontologia [ONTOLOGIA]\nSecondo l'ISTAT nel territorio romano i "
        "furti sono in calo.\n"
    )
    assert (m.frasi_istat, m.frasi_istat_con_luogo) == (1, 0)


def test_somma_fra_ripetizioni() -> None:
    a = _metriche("Rischi da ontologia [ONTOLOGIA]\nI furti sono 134.169.\n")
    b = _metriche(
        "Rischi da ontologia [ONTOLOGIA]\nSecondo l'ISTAT a Roma i furti sono "
        "sopra la media italiana.\n",
        frasi_escluse_m1=1,
    )
    s = somma_istat_metrics([a, None, b])
    assert s is not None
    assert (s.versione, s.cifre_totali, s.cifre_istat) == (4, 1, 1)
    assert (s.frasi_istat, s.confronti_totali, s.confronti_coerenti) == (2, 1, 1)
    assert s.frasi_escluse_m1 == 1
    assert somma_istat_metrics([None, None]) is None


def test_somma_rifiuta_versioni_diverse() -> None:
    a = _metriche("Rischi da ontologia [ONTOLOGIA]\nRapina.\n")
    with pytest.raises(ValueError, match="versioni"):
        somma_istat_metrics([a, a.model_copy(update={"versione": 1})])


def test_luogo_esplicito_e_ereditato_contati_a_parte() -> None:
    """Fix 3: la frase dell'elenco che eredita il luogo non conta come con luogo."""
    m = _metriche(
        "Rischi da ontologia [ONTOLOGIA]\nSecondo l'ISTAT nel Comune di Roma i "
        "furti sono in calo. I furti hanno un tasso piu' alto dal 2014.\n"
    )
    assert (m.frasi_istat, m.frasi_istat_con_luogo) == (2, 1)
    assert m.frasi_istat_con_luogo_ereditato == 1
    assert m.frasi_scartabili == 0


def test_codici_voce_scritti_dal_modello() -> None:
    """Domanda 2 della review: i codici delle righe si contano (attesi 0)."""
    m = _metriche(
        "Rischi da ontologia [ONTOLOGIA]\nSecondo l'ISTAT nel Comune di Roma la "
        "voce THEFT e' in calo; BANKROB pure.\n"
    )
    assert m.codici_voce == 2
    assert _metriche("Rischi da ontologia [ONTOLOGIA]\nRapina.\n").codici_voce == 0
    vecchio = IstatMetrics.model_validate(
        {k: v for k, v in m.model_dump().items() if k != "codici_voce"}
    )
    assert vecchio.codici_voce == 0
