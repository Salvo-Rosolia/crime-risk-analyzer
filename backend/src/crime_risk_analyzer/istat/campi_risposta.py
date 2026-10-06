"""Campi di risposta condivisi sui dati ISTAT nella narrativa (#345).

Le tre risposte HTTP che espongono una narrativa — ``AnalyzeResponse``
(:mod:`~crime_risk_analyzer.orchestrator`), ``ZoneNarrativeResponse``
(:mod:`~crime_risk_analyzer.analyze_narrative`) e ``PoiNarrativeResponse``
(:mod:`~crime_risk_analyzer.poi_narrative`) — riportano le STESSE tre
osservabili sull'interruttore ISTAT: se il prompt le ha usate
(``istat_attivo``), quale versione dei dati (``istat_versione_dati``) e
quante frasi il controllo delle cifre ha scartato (``istat_frasi_scartate``).

Prima di questo modulo i tre ``Field`` erano copiati identici in tre file
diversi: una divergenza futura (descrizione, default o vincolo cambiato in
uno solo dei tre punti) sarebbe passata inosservata. :class:`CampiIstatRisposta`
e' la base comune da cui le tre risposte ereditano, cosi' il contratto vive
in un solo posto.

Vive sotto ``istat/`` (non in ``rag/generation.py``, che ha gia' campi
OMONIMI su :class:`~crime_risk_analyzer.rag.generation.GenerationResult` con
descrizioni volutamente diverse — quelle descrivono un fatto del generation
layer, "il prompt conteneva il blocco", non il contratto della risposta HTTP)
ed e' importabile da tutti e tre senza cicli: il pacchetto ``istat`` dipende
solo da ``models.geo``/``i18n.terminus_labels``, mai da
``orchestrator``/``analyze_narrative``/``poi_narrative``/``rag.*``.

``narrativa_grezza``/``controllo_istat`` (solo per l'harness, ``exclude=True``)
NON fanno parte di questa base: restano solo su ``AnalyzeResponse``, l'unica
delle tre risposte che li espone.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["CampiIstatRisposta"]


class CampiIstatRisposta(BaseModel):
    """Base comune dei tre campi ISTAT esposti dalle risposte con narrativa."""

    istat_attivo: bool = Field(
        default=False,
        description=(
            "True se la narrativa e' stata scritta coi dati ISTAT nel prompt (#345)."
        ),
    )
    istat_versione_dati: str | None = Field(
        default=None, description="Data di estrazione dei dati ISTAT usati (#345)."
    )
    istat_frasi_scartate: int = Field(
        default=0,
        ge=0,
        description=(
            "Frasi tolte dal controllo delle cifre (#345): trasparenza sul filtro, "
            "non una misura di pericolosita'."
        ),
    )
