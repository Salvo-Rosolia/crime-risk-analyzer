"""Base condivisa dei campi ISTAT di risposta (#345, fix round 1 review Task 13).

Le tre risposte HTTP con narrativa (``AnalyzeResponse``, ``ZoneNarrativeResponse``,
``PoiNarrativeResponse``) ereditano gli stessi tre campi ``istat_*`` da
:class:`CampiIstatRisposta` invece di ridefinirli ciascuna: una divergenza futura
(descrizione/default/vincolo cambiato in un solo punto) romperebbe qui, non in
silenzio in uno solo dei tre file.
"""

from __future__ import annotations

from crime_risk_analyzer.analyze_narrative import ZoneNarrativeResponse
from crime_risk_analyzer.istat.campi_risposta import CampiIstatRisposta
from crime_risk_analyzer.orchestrator import AnalyzeResponse
from crime_risk_analyzer.poi_narrative import PoiNarrativeResponse

_CAMPI_ISTAT = {"istat_attivo", "istat_versione_dati", "istat_frasi_scartate"}


def test_campi_istat_risposta_espone_esattamente_i_tre_campi() -> None:
    assert set(CampiIstatRisposta.model_fields) == _CAMPI_ISTAT
    assert CampiIstatRisposta.model_fields["istat_attivo"].default is False
    assert CampiIstatRisposta.model_fields["istat_versione_dati"].default is None
    assert CampiIstatRisposta.model_fields["istat_frasi_scartate"].default == 0


def test_le_tre_risposte_ereditano_la_stessa_base_istat() -> None:
    """Le tre risposte non ridefiniscono i campi: li ricevono da una sola base.

    ``issubclass`` prova l'eredita'. Pydantic ricostruisce un ``FieldInfo`` per
    ogni sottoclasse (mai la stessa istanza, anche senza ridichiarazione: l'
    identita' non è quindi un test utile), percio' il confronto è sul ``repr``
    — stesso tipo, default, vincoli e descrizione: se una delle tre avesse
    ridichiarato il campo con una descrizione o un default divergente, il
    ``repr`` sarebbe diverso e il test diventerebbe rosso.
    """
    for risposta in (AnalyzeResponse, ZoneNarrativeResponse, PoiNarrativeResponse):
        assert issubclass(risposta, CampiIstatRisposta)
        assert _CAMPI_ISTAT <= set(risposta.model_fields)
        for campo in _CAMPI_ISTAT:
            assert repr(risposta.model_fields[campo]) == repr(
                CampiIstatRisposta.model_fields[campo]
            )


def test_narrativa_grezza_e_controllo_istat_restano_solo_su_analyze_response() -> None:
    """``narrativa_grezza``/``controllo_istat`` non sono nella base condivisa:
    solo ``AnalyzeResponse`` (harness) li espone."""
    assert "narrativa_grezza" not in CampiIstatRisposta.model_fields
    assert "controllo_istat" not in CampiIstatRisposta.model_fields
    assert {"narrativa_grezza", "controllo_istat"} <= set(AnalyzeResponse.model_fields)
    assert "narrativa_grezza" not in ZoneNarrativeResponse.model_fields
    assert "narrativa_grezza" not in PoiNarrativeResponse.model_fields
