"""Retrieval pipeline -> context_dict grezzo (#22).

Primo dei tre layer della pipeline /analyze (retrieval -> grounding #24 ->
orchestrazione #18). :func:`retrieve` caba i mattoni a monte gia' pronti
(geocoding #15, Overpass #16/#79, SPARQL executor #76) e assembla il
``context_dict`` *grezzo*: POI + profilo di rischio per classe TERMINUS, SENZA
tag/confidence (quelli sono compito del grounding #24).

Forma normalizzata: i POI restano il :class:`~crime_risk_analyzer.overpass_client.Poi`
esistente (riuso verbatim); i profili stanno in una mappa indicizzata PER CLASSE
(:data:`RetrievalContext` ``profiles``), perche' hazard e vulnerabilita' dipendono
solo dalla classe TERMINUS. ``profile()`` e' percio' invocato una volta per classe
distinta (memoizzazione semanticamente corretta, nessuna chiamata ridondante).

Gli errori di dominio (:class:`ZoneNotFoundError`, :class:`GeocodingError`,
:class:`OverpassError`) NON sono gestiti qui: risalgono al chiamante (endpoint #18).
"""

from __future__ import annotations

from typing import Protocol, TypedDict

from fastapi.concurrency import run_in_threadpool

from crime_risk_analyzer.geocoding import GeoResult, geocode_zone
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.overpass_client import Poi, fetch_pois

__all__ = ["RetrievalContext", "RetrievalStats", "RiskProfiler", "retrieve"]


class RiskProfiler(Protocol):
    """Vista strutturale minimale dell'executor SPARQL (#76) usata da retrieve.

    ``RiskQueryExecutor`` la soddisfa; i test passano un fake che traccia le chiamate.
    """

    def profile(self, terminus_class: str) -> PoiRiskProfile: ...


class RetrievalStats(TypedDict):
    """Conteggi di sintesi del retrieval."""

    n_pois: int
    n_classes: int


class RetrievalContext(TypedDict):
    """``context_dict`` grezzo (pre-grounding) prodotto da :func:`retrieve`.

    Il rischio di un POI si ottiene con ``profiles[poi["terminus_class"]]``.
    """

    citta: str
    zona: str
    geo: GeoResult
    pois: list[Poi]
    profiles: dict[str, PoiRiskProfile]
    stats: RetrievalStats


async def retrieve(
    citta: str, zona: str, *, executor: RiskProfiler
) -> RetrievalContext:
    """Assembla il context_dict grezzo per ``zona`` dentro ``citta``.

    Caba geocoding -> Overpass -> profilo SPARQL per classe distinta. I POI senza
    rischi (``GenericUrbanPOI`` o profilo vuoto) sono inclusi; zona senza POI ->
    context con ``pois=[]`` senza errore. Gli errori di dominio sono propagati.
    """
    geo = await run_in_threadpool(geocode_zone, zona, citta)
    pois = await fetch_pois(geo["bbox"], citta)
    profiles: dict[str, PoiRiskProfile] = {
        terminus_class: executor.profile(terminus_class)
        for terminus_class in {poi["terminus_class"] for poi in pois}
    }
    return RetrievalContext(
        citta=citta,
        zona=zona,
        geo=geo,
        pois=pois,
        profiles=profiles,
        stats=RetrievalStats(n_pois=len(pois), n_classes=len(profiles)),
    )
