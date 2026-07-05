"""Validazione C1 city-agnostic (#31): copertura POI, boundary, switch.

Due fasi separate (come #34): capture live (geocode+Overpass una volta per città)
e compute deterministico (ricalcolo copertura dagli snapshot contro il grafo
ontologia). Metriche riportate con soglie a-priori pass/fail (non fanno fallire
il gate). La robustezza confini è reinterpretata come bbox valido end-to-end: il
retrieval usa il bbox Nominatim, non relation amministrative (finding di #31).
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field
from rdflib import OWL, RDF, Graph

from crime_risk_analyzer.ontology_namespaces import TERMINUS
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.sparql_module.osm_mapping import GENERIC_FALLBACK

VERBATIM_MIN = 0.50
DERIVED_MIN = 0.70
SWITCH_MAX_MS = 5000


@dataclass(frozen=True)
class RosterCity:
    """Città del roster di validazione (dato, non codice)."""

    citta: str
    zona: str


#: Roster ≥5 città (spec-valutazione §0). Roma/Milano/Napoli garantite;
#: Torino/Firenze best-effort sui dati OSM.
ROSTER: tuple[RosterCity, ...] = (
    RosterCity("Roma", "Colosseo"),
    RosterCity("Milano", "Duomo"),
    RosterCity("Napoli", "Piazza Garibaldi"),
    RosterCity("Torino", "Porta Nuova"),
    RosterCity("Firenze", "Santa Maria Novella"),
)


class CityCapture(BaseModel):
    """Snapshot di un capture live per una città (versionato per il replay)."""

    citta: str
    zona: str
    lat: float
    lon: float
    bbox: tuple[float, float, float, float]
    switch_ms: int = Field(ge=0)
    pois: list[Poi]


class CityAgnosticRecord(BaseModel):
    """Record calcolato per una città: metriche + esiti soglia."""

    citta: str
    zona: str
    n_poi: int = Field(ge=0)
    coverage_verbatim: float
    coverage_derived: float
    boundary_ok: bool
    switch_ms: int = Field(ge=0)
    pass_verbatim: bool
    pass_derived: bool
    pass_switch: bool
    ontology_hash: str
    verbatim_min: float = VERBATIM_MIN
    derived_min: float = DERIVED_MIN
    switch_max_ms: int = SWITCH_MAX_MS


def class_exists(graph: Graph, class_name: str) -> bool:
    """True se ``class_name`` è dichiarata come ``owl:Class`` nel grafo TERMINUS."""
    if class_name == GENERIC_FALLBACK:
        return False
    return (TERMINUS[class_name], RDF.type, OWL.Class) in graph


def compute_coverage(pois: list[Poi], graph: Graph) -> tuple[float, float]:
    """Copertura (verbatim, derivata) sui POI. Lista vuota → (0.0, 0.0)."""
    if not pois:
        return (0.0, 0.0)
    n = len(pois)
    derived = sum(1 for p in pois if p["terminus_class"] != GENERIC_FALLBACK) / n
    verbatim = sum(1 for p in pois if class_exists(graph, p["terminus_class"])) / n
    return (verbatim, derived)


def boundary_ok(bbox: tuple[float, float, float, float]) -> bool:
    """True se il bbox è non degenere (area positiva)."""
    min_lat, min_lon, max_lat, max_lon = bbox
    return max_lat > min_lat and max_lon > min_lon


def build_record(
    capture: CityCapture, graph: Graph, ontology_hash: str
) -> CityAgnosticRecord:
    """Calcola il record dalle metriche di un capture."""
    verbatim, derived = compute_coverage(capture.pois, graph)
    return CityAgnosticRecord(
        citta=capture.citta,
        zona=capture.zona,
        n_poi=len(capture.pois),
        coverage_verbatim=verbatim,
        coverage_derived=derived,
        boundary_ok=boundary_ok(capture.bbox),
        switch_ms=capture.switch_ms,
        pass_verbatim=verbatim >= VERBATIM_MIN,
        pass_derived=derived >= DERIVED_MIN,
        pass_switch=capture.switch_ms < SWITCH_MAX_MS,
        ontology_hash=ontology_hash,
    )
