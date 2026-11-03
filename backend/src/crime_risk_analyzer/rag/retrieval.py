"""Retrieval pipeline -> raw context_dict (#22).

First of the three layers of the /analyze pipeline (retrieval -> grounding #24 ->
orchestration #18). :func:`retrieve` wires the already-ready upstream building blocks
(geocoding #15, Overpass #16/#79, SPARQL executor #76) and assembles the *raw*
``context_dict``: POIs + risk profile per TERMINUS class, WITHOUT
tag/confidence (those are the job of the grounding #24).

Normalised shape: the POIs remain the existing
:class:`~crime_risk_analyzer.overpass_client.Poi` (verbatim reuse); the profiles sit
in a map indexed BY CLASS (:data:`RetrievalContext` ``profiles``), because hazards
and vulnerabilities depend only on the TERMINUS class. ``profile()`` is therefore
invoked once per distinct class (semantically correct memoisation, no
redundant call).

The domain errors (:class:`ZoneNotFoundError`, :class:`GeocodingError`,
:class:`OverpassError`) are NOT handled here: they rise to the caller (endpoint #18).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, TypedDict

from fastapi.concurrency import run_in_threadpool

from crime_risk_analyzer.geocoding import GeoResult, geocode_zone
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.overpass_client import Poi, fetch_pois

__all__ = [
    "GeoSource",
    "PoiSource",
    "RetrievalContext",
    "RetrievalStats",
    "RiskProfiler",
    "retrieve",
]

#: Injectable POI source (capture-and-replay in eval). Default: live Overpass.
PoiSource = Callable[[Bbox, str], Awaitable[list[Poi]]]

#: Injectable geo source (replay in eval, #169). Default (None): live geocode.
#: The signature is ``(citta, zona) -> GeoResult`` (mirror of :data:`PoiSource`).
GeoSource = Callable[[str, str], Awaitable[GeoResult]]


class RiskProfiler(Protocol):
    """Minimal structural view of the SPARQL executor (#76) used by retrieve.

    ``RiskQueryExecutor`` satisfies it; the tests pass a fake that traces the calls.
    """

    def profile(self, ontology_class: str) -> PoiRiskProfile: ...


class RetrievalStats(TypedDict):
    """Summary counts of the retrieval."""

    n_pois: int
    n_classes: int


class RetrievalContext(TypedDict):
    """Raw ``context_dict`` (pre-grounding) produced by :func:`retrieve`.

    The risk of a POI is obtained with ``profiles[poi["ontology_class"]]``.
    """

    citta: str
    zona: str
    geo: GeoResult
    pois: list[Poi]
    profiles: dict[str, PoiRiskProfile]
    stats: RetrievalStats


async def retrieve(
    citta: str,
    zona: str,
    *,
    executor: RiskProfiler,
    poi_source: PoiSource | None = None,
    geo_source: GeoSource | None = None,
) -> RetrievalContext:
    """Assembles the raw context_dict for ``zona`` inside ``citta``.

    It wires geocoding -> Overpass -> SPARQL profile per distinct class. POIs without
    risks (``GenericUrbanPOI`` or empty profile) are included; a zone without POIs ->
    context with ``pois=[]`` without error. Domain errors are propagated.

    ``poi_source`` allows capture-and-replay in the eval harness: if None
    it uses the live source ``fetch_pois`` (Overpass).

    ``geo_source`` (#169) allows the geo replay in the harness: if None it uses the
    live geocoding ``geocode_zone`` (Nominatim). By injecting a source that returns
    a placeholder, the eval run never calls Nominatim (hermetic run): the geo
    stays irrelevant for grounding/generation/metrics (none of the three reads it;
    ``replay_source`` ignores the bbox). Since #260 it is however NO longer
    dead-downstream in the absolute sense: it comes out verbatim in
    ``AnalyzeResponse.zona_geo``, so a replay placeholder would appear, unchanged,
    in that field of the response — harmless for the metrics (which do not look at
    it) but no longer a value that "alters no output" in the literal sense.
    """
    if geo_source is not None:
        geo = await geo_source(citta, zona)
    else:
        geo = await run_in_threadpool(geocode_zone, zona, citta)
    source = poi_source or fetch_pois
    pois = await source(geo["bbox"], citta)
    profiles: dict[str, PoiRiskProfile] = {
        ontology_class: executor.profile(ontology_class)
        for ontology_class in {poi["ontology_class"] for poi in pois}
    }
    return RetrievalContext(
        citta=citta,
        zona=zona,
        geo=geo,
        pois=pois,
        profiles=profiles,
        stats=RetrievalStats(n_pois=len(pois), n_classes=len(profiles)),
    )
