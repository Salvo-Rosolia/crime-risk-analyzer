"""Validazione C1 city-agnostic (#31): copertura POI, boundary, switch.

Due fasi separate (come #34): capture live (geocode+Overpass una volta per città)
e compute deterministico (ricalcolo copertura dagli snapshot contro il grafo
ontologia). Metriche riportate con soglie a-priori pass/fail (non fanno fallire
il gate). Il prodotto usa il bbox Nominatim per la zona *by design* (nessuna
modifica al retrieval); la validazione confini verifica invece il contenimento
dei POI nel poligono amministrativo reale della città (decisione 3B), con
`bbox_valid` che resta come semplice sanity check sul bbox non degenere.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Protocol, cast

from geopy.exc import GeocoderServiceError  # pyright: ignore[reportMissingTypeStubs]
from geopy.geocoders import Nominatim  # pyright: ignore[reportMissingTypeStubs]
from pydantic import BaseModel, Field
from rdflib import OWL, RDF, Graph

from crime_risk_analyzer.eval.geometry import (
    CityBoundary,
    boundary_from_geojson,
    point_in_multipolygon,
)
from crime_risk_analyzer.geocoding import (
    GeocodingError,
    ZoneNotFoundError,
    geocode_zone,
)
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.ontology_namespaces import TERMINUS
from crime_risk_analyzer.overpass_client import OverpassError, Poi, fetch_pois
from crime_risk_analyzer.sparql_module.osm_mapping import GENERIC_FALLBACK

PoiSource = Callable[[Bbox, str], Awaitable[list[Poi]]]
BoundarySource = Callable[[str], CityBoundary]

VERBATIM_MIN = 0.50
DERIVED_MIN = 0.70
SWITCH_MAX_MS = 5000
BOUNDARY_MIN = 0.90

_BOUNDARY_USER_AGENT = (
    "crime-risk-analyzer-eval (https://github.com/Salvo-Rosolia/crime-risk-analyzer)"
)


class _BoundaryLocation(Protocol):
    """Vista tipata minimale del ``geopy.location.Location`` (libreria senza stub)."""

    @property
    def raw(self) -> dict[str, object]: ...


@lru_cache(maxsize=1)
def _boundary_geolocator() -> Nominatim:
    return Nominatim(user_agent=_BOUNDARY_USER_AGENT)


def fetch_city_boundary(citta: str) -> CityBoundary:
    """Scarica il poligono amministrativo reale della città via Nominatim.

    Validation-only: usa un geolocator dedicato per non modificare il prodotto.
    """
    try:
        result: object = _boundary_geolocator().geocode(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            f"{citta}, Italia", geometry="geojson"
        )
    except GeocoderServiceError as exc:
        raise GeocodingError(
            f"Nominatim non raggiungibile per confine {citta!r}"
        ) from exc
    location = cast("_BoundaryLocation | None", result)
    if location is None:
        raise ZoneNotFoundError(f"Confine città non trovato: {citta!r}")
    raw = location.raw
    geometry = raw.get("geojson")
    if not isinstance(geometry, Mapping):
        raise ZoneNotFoundError(f"Confine città privo di geometria: {citta!r}")
    try:
        return boundary_from_geojson(cast("Mapping[str, object]", geometry))
    except ValueError as exc:
        raise ZoneNotFoundError(
            f"Confine città con geometria non poligonale: {citta!r}"
        ) from exc


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
    boundary: CityBoundary


class CityAgnosticRecord(BaseModel):
    """Record calcolato per una città: metriche + esiti soglia."""

    citta: str
    zona: str
    n_poi: int = Field(ge=0)
    coverage_verbatim: float
    coverage_derived: float
    bbox_valid: bool
    pois_in_boundary: float
    switch_ms: int = Field(ge=0)
    pass_verbatim: bool
    pass_derived: bool
    pass_boundary: bool
    pass_switch: bool
    ontology_hash: str
    verbatim_min: float = VERBATIM_MIN
    derived_min: float = DERIVED_MIN
    switch_max_ms: int = SWITCH_MAX_MS
    boundary_min: float = BOUNDARY_MIN


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


def bbox_valid(bbox: tuple[float, float, float, float]) -> bool:
    """True se il bbox è non degenere (area positiva)."""
    min_lat, min_lon, max_lat, max_lon = bbox
    return max_lat > min_lat and max_lon > min_lon


def compute_boundary_coverage(pois: list[Poi], boundary: CityBoundary) -> float:
    """Frazione di POI dentro il poligono amministrativo. Lista vuota → 0.0."""
    if not pois:
        return 0.0
    inside = sum(
        1 for p in pois if point_in_multipolygon((p["lon"], p["lat"]), boundary)
    )
    return inside / len(pois)


def build_record(
    capture: CityCapture, graph: Graph, ontology_hash: str
) -> CityAgnosticRecord:
    """Calcola il record dalle metriche di un capture."""
    verbatim, derived = compute_coverage(capture.pois, graph)
    boundary_cov = compute_boundary_coverage(capture.pois, capture.boundary)
    return CityAgnosticRecord(
        citta=capture.citta,
        zona=capture.zona,
        n_poi=len(capture.pois),
        coverage_verbatim=verbatim,
        coverage_derived=derived,
        bbox_valid=bbox_valid(capture.bbox),
        pois_in_boundary=boundary_cov,
        switch_ms=capture.switch_ms,
        pass_verbatim=verbatim >= VERBATIM_MIN,
        pass_derived=derived >= DERIVED_MIN,
        pass_boundary=boundary_cov >= BOUNDARY_MIN,
        pass_switch=capture.switch_ms < SWITCH_MAX_MS,
        ontology_hash=ontology_hash,
    )


def city_slug(citta: str) -> str:
    """Slug per il nome file dello snapshot."""
    return citta.strip().lower().replace(" ", "-")


def capture_path(results_dir: Path, citta: str) -> Path:
    """Percorso dello snapshot versionato per una città."""
    return results_dir / "city_agnostic" / "snapshots" / f"{city_slug(citta)}.json"


class CaptureOutcome(BaseModel):
    """Esito di una cattura per città: successo (con capture) o fallimento (errore)."""

    status: Literal["ok", "failed"]
    citta: str
    zona: str
    capture: CityCapture | None = None
    error_type: str | None = None
    error: str | None = None


def save_outcome(path: Path, outcome: CaptureOutcome) -> None:
    """Serializza un esito su file (crea le cartelle)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(outcome.model_dump_json(indent=2) + "\n", encoding="utf-8")


def load_outcome(path: Path) -> CaptureOutcome:
    """Carica un esito da uno snapshot versionato."""
    return CaptureOutcome.model_validate_json(path.read_text(encoding="utf-8"))


async def capture_city(
    citta: str,
    zona: str,
    *,
    poi_source: PoiSource | None = None,
    boundary_source: BoundarySource = fetch_city_boundary,
) -> CityCapture:
    """Capture live: geocode + fetch POI (cronometrati) + poligono città (non timed)."""
    source = poi_source or fetch_pois
    start = time.perf_counter()
    geo = geocode_zone(zona, citta)
    pois = await source(geo["bbox"], citta)
    switch_ms = int((time.perf_counter() - start) * 1000)
    boundary = boundary_source(citta)
    bbox = geo["bbox"]
    return CityCapture(
        citta=citta,
        zona=zona,
        lat=geo["lat"],
        lon=geo["lon"],
        bbox=(bbox.min_lat, bbox.min_lon, bbox.max_lat, bbox.max_lon),
        switch_ms=switch_ms,
        pois=pois,
        boundary=boundary,
    )


async def capture_roster(
    roster: tuple[RosterCity, ...] = ROSTER,
    results_dir: Path = Path("results"),
    *,
    poi_source: PoiSource | None = None,
    boundary_source: BoundarySource = fetch_city_boundary,
) -> None:
    """Cattura ogni città del roster isolando i fallimenti per-città (M3)."""
    for city in roster:
        try:
            capture = await capture_city(
                city.citta,
                city.zona,
                poi_source=poi_source,
                boundary_source=boundary_source,
            )
            outcome = CaptureOutcome(
                status="ok", citta=city.citta, zona=city.zona, capture=capture
            )
        except (GeocodingError, OverpassError) as exc:
            outcome = CaptureOutcome(
                status="failed",
                citta=city.citta,
                zona=city.zona,
                error_type=type(exc).__name__,
                error=str(exc),
            )
        save_outcome(capture_path(results_dir, city.citta), outcome)
