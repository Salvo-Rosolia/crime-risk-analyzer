"""Metriche ISTAT (#345, spec 4.9): deterministiche, sul testo grezzo."""

from __future__ import annotations

from crime_risk_analyzer.eval.istat_metrics import (
    compute_istat_metrics,
    somma_istat_metrics,
)
from crime_risk_analyzer.eval.schema import IstatMetrics
from crime_risk_analyzer.istat.blocco import blocco_istat_poi
from crime_risk_analyzer.istat.cifre import controlla_cifre
from crime_risk_analyzer.rag.generation import source_block_spans
from tests.istat._fattorie import BANKROB, istat_poi, riga

_BLOCCO = blocco_istat_poi(istat_poi(riga(), BANKROB))


def _metriche(testo: str) -> IstatMetrics:
    esito = controlla_cifre(
        testo,
        blocchi=source_block_spans(testo),
        blocco_istat=_BLOCCO.testo,
        contesto_senza_istat="ZONA: Colosseo",
        righe=_BLOCCO.righe,
    )
    return compute_istat_metrics(esito)


def test_metriche_su_una_narrativa_tipica() -> None:
    testo = (
        "Sintesi con 134.169 furti.\n\n"
        "Rischi da ontologia [ONTOLOGIA]\nRapina in banca.\n\n"
        "Dati statistici ISTAT [ISTAT]\n"
        "Nel Comune di Roma i furti sono 134.169, in calo del -10% (fonte ISTAT, "
        "Comune di Roma, 2024), e la voce ISTAT non coincide con il rischio.\n"
        "I furti sono il doppio di quanto si pensi.\n"
    )
    m = _metriche(testo)
    assert (m.cifre_totali, m.cifre_istat_corrette) == (3, 2)
    assert m.precisione_cifre == 2 / 3
    assert m.frasi_scartabili == 1
    assert (m.voci_fornite, m.voci_citate) == (2, 1)
    assert (m.frasi_istat, m.frasi_istat_con_luogo) == (1, 1)
    assert (m.direzioni_totali, m.direzioni_coerenti) == (1, 1)
    # "il doppio": furti piu' ampia, nessuna dichiarazione
    assert m.corrispondenze_non_dichiarate == 1
    assert m.numeri_in_lettere == 1


def test_senza_cifre_la_precisione_non_e_definita() -> None:
    m = _metriche("Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n")
    assert m.cifre_totali == 0 and m.precisione_cifre is None


def test_somma_fra_ripetizioni() -> None:
    a = _metriche("Dati statistici ISTAT [ISTAT]\nI furti sono 134.169.\n")
    b = _metriche("Dati statistici ISTAT [ISTAT]\nI furti sono 134.000.\n")
    s = somma_istat_metrics([a, None, b])
    assert s is not None
    assert (s.cifre_totali, s.cifre_istat_corrette) == (2, 1)
    assert s.precisione_cifre == 0.5
    assert somma_istat_metrics([None, None]) is None
