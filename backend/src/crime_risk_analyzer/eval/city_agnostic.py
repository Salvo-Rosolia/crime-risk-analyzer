"""City-agnostic C1 validation (#31): POI coverage, boundary, switch.

Two separate phases (like #34): live capture (geocode+Overpass once per city)
and deterministic compute (coverage recomputed from the snapshots against the
ontology graph). Metrics reported with a-priori pass/fail thresholds (they do not
fail the gate). The product uses the Nominatim bbox for the zone *by design* (no
change to retrieval); the boundary validation instead verifies the containment
of the POIs in the real administrative polygon of the city (decision 3B), with
`bbox_valid` remaining as a simple sanity check on a non-degenerate bbox.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal, Protocol, cast

from geopy.exc import GeocoderServiceError  # pyright: ignore[reportMissingTypeStubs]
from geopy.extra.rate_limiter import (  # pyright: ignore[reportMissingTypeStubs]
    RateLimiter,
)
from geopy.geocoders import Nominatim  # pyright: ignore[reportMissingTypeStubs]
from pydantic import BaseModel, Field
from rdflib import OWL, RDF, Graph

from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.eval.geometry import (
    CityBoundary,
    boundary_from_geojson,
    point_in_multipolygon,
)
from crime_risk_analyzer.eval.snapshots import current_canonical_config
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
    """Minimal typed view of ``geopy.location.Location`` (library without stubs)."""

    @property
    def raw(self) -> dict[str, object]: ...


class _BoundaryGeocoder(Protocol):
    """Minimal typed view of the geocoder (geopy without stubs) for the boundary.

    Declares the signature needed here (with ``geometry`` for the polygon) instead of
    inheriting the untyped one of ``Nominatim``: the call stays verifiable
    by strict pyright without ``# pyright: ignore`` on the arguments.
    """

    def geocode(
        self,
        query: str,
        *,
        geometry: str = ...,
        country_codes: str = ...,
        timeout: float = ...,
    ) -> _BoundaryLocation | None: ...


@lru_cache(maxsize=1)
def _boundary_geolocator() -> Nominatim:
    return Nominatim(user_agent=_BOUNDARY_USER_AGENT)


def _boundary_geocode_raw(citta: str) -> _BoundaryLocation | None:
    """Actual call to geopy for the boundary, with timeout and country_codes (#170).

    Re-resolves ``_boundary_geolocator()`` on every call so that the test
    monkeypatch is honoured even behind the singleton RateLimiter (mirror of #115).
    ``geometry='geojson'`` is wired in: the polygon is needed, not a point.
    """
    settings = get_settings()
    geolocator = cast("_BoundaryGeocoder", _boundary_geolocator())
    return geolocator.geocode(
        f"{citta}, Italia",
        geometry="geojson",
        country_codes=settings.geocoding_country_codes,
        timeout=settings.geocoding_timeout_seconds,
    )


@lru_cache(maxsize=1)
def _boundary_rate_limiter() -> Callable[[str], _BoundaryLocation | None]:
    """LOCAL RateLimiter around :func:`_boundary_geocode_raw` (#170).

    Second Nominatim call site of the project: the boundary respects the usage
    policy (~1 req/s) with the same pattern as #115 but a DEDICATED limiter (not
    shared with ``geocode_zone``), so as not to touch the core logic of that
    rate-limiter. ``min_delay_seconds`` from the settings; ``max_retries=0`` preserves
    the single-call semantics; ``swallow_exceptions=False`` makes
    ``GeocoderServiceError`` propagate (mapped by :func:`fetch_city_boundary` ->
    ``GeocodingError``, otherwise geopy would swallow it returning ``None``,
    confused with "boundary not found"). ``error_wait_seconds`` >= ``min_delay``
    for the internal assert of geopy with envs that configure ``min_delay`` > 5s
    (inert with ``max_retries=0``). Cached: the throttling state persists; the
    tests reset it with ``cache_clear()``.
    """
    min_delay = get_settings().geocoding_min_delay_seconds
    return cast(
        "Callable[[str], _BoundaryLocation | None]",
        RateLimiter(
            _boundary_geocode_raw,
            min_delay_seconds=min_delay,
            max_retries=0,
            error_wait_seconds=max(5.0, min_delay),
            swallow_exceptions=False,
        ),
    )


def fetch_city_boundary(citta: str) -> CityBoundary:
    """Download the real administrative polygon of the city via Nominatim.

    Validation-only: uses a dedicated geolocator and a LOCAL rate-limiter (#170)
    so as not to modify the product nor interfere with the #115 limiter.
    """
    try:
        location = _boundary_rate_limiter()(citta)
    except GeocoderServiceError as exc:
        raise GeocodingError(
            f"Nominatim non raggiungibile per confine {citta!r}"
        ) from exc
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
    """City of the validation roster (data, not code)."""

    citta: str
    zona: str


#: Roster of >=5 cities (evaluation-spec section 0). Rome/Milan/Naples guaranteed;
#: Turin/Florence best-effort on the OSM data.
ROSTER: tuple[RosterCity, ...] = (
    RosterCity("Roma", "Colosseo"),
    RosterCity("Milano", "Duomo"),
    RosterCity("Napoli", "Piazza Garibaldi"),
    RosterCity("Torino", "Porta Nuova"),
    RosterCity("Firenze", "Santa Maria Novella"),
)


class CityCapture(BaseModel):
    """Snapshot of a live capture for a city (versioned for replay)."""

    citta: str
    zona: str
    lat: float
    lon: float
    bbox: tuple[float, float, float, float]
    switch_ms: int = Field(ge=0)
    pois: list[Poi]
    boundary: CityBoundary


class CityAgnosticRecord(BaseModel):
    """Record computed for a city: metrics + threshold outcomes."""

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
    """True if ``class_name`` is declared as ``owl:Class`` in the TERMINUS graph."""
    if class_name == GENERIC_FALLBACK:
        return False
    return (TERMINUS[class_name], RDF.type, OWL.Class) in graph


def compute_coverage(pois: list[Poi], graph: Graph) -> tuple[float, float]:
    """Coverage (verbatim, derived) on the POIs. Empty list -> (0.0, 0.0)."""
    if not pois:
        return (0.0, 0.0)
    n = len(pois)
    derived = sum(1 for p in pois if p["terminus_class"] != GENERIC_FALLBACK) / n
    verbatim = sum(1 for p in pois if class_exists(graph, p["terminus_class"])) / n
    return (verbatim, derived)


def bbox_valid(bbox: tuple[float, float, float, float]) -> bool:
    """True if the bbox is non-degenerate (positive area)."""
    min_lat, min_lon, max_lat, max_lon = bbox
    return max_lat > min_lat and max_lon > min_lon


def compute_boundary_coverage(pois: list[Poi], boundary: CityBoundary) -> float:
    """Fraction of POIs inside the administrative polygon. Empty list -> 0.0."""
    if not pois:
        return 0.0
    inside = sum(
        1 for p in pois if point_in_multipolygon((p["lon"], p["lat"]), boundary)
    )
    return inside / len(pois)


def build_record(
    capture: CityCapture, graph: Graph, ontology_hash: str
) -> CityAgnosticRecord:
    """Compute the record from the metrics of a capture."""
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
    """Slug for the snapshot file name."""
    return citta.strip().lower().replace(" ", "-")


def capture_path(results_dir: Path, citta: str) -> Path:
    """Path of the versioned snapshot for a city."""
    return results_dir / "city_agnostic" / "snapshots" / f"{city_slug(citta)}.json"


class OutcomeProvenance(BaseModel):
    """With which CODE configuration a C1 outcome was written (#374).

    It says two things: WHEN the process wrote the outcome (``catturato_il``,
    ISO-8601 UTC, process clock: "when the process finished
    writing the outcome", AFTER the request to Overpass and not before, and not "which
    state of OSM I obtained") and the canonical constants of the code that wrote it
    (selectors, caps, element types: same source as the POI fixtures, #241).

    It does not say what was really queried: ``capture_city`` accepts an
    arbitrary ``poi_source``. For the same reason it does NOT carry the ``taglio_osm``
    (#251): ``PoiSource`` returns only the POIs, the cut is not available here and a
    field that claims more than is known is worse than one that stays silent. The aim is
    to make visible a partial re-capture that mixes outcomes produced with
    different configurations (e.g. with and without relations, #314).

    ``configurazione_canonica`` is a generic dict (not the TypedDict of
    ``snapshots``) because it is re-read from external JSON: the check against the
    current configuration is in ``describe_config_divergence``.
    """

    catturato_il: str
    configurazione_canonica: dict[str, object]


class CaptureOutcome(BaseModel):
    """Outcome of a per-city capture: success (with capture) or failure (error).

    ``provenienza`` is present on ok and failed (even a failure says with which
    configuration it was attempted); ``None`` for outcomes written before #374,
    which stay readable.
    """

    status: Literal["ok", "failed"]
    citta: str
    zona: str
    capture: CityCapture | None = None
    error_type: str | None = None
    error: str | None = None
    provenienza: OutcomeProvenance | None = None


def _current_provenance(clock: Callable[[], datetime]) -> OutcomeProvenance:
    return OutcomeProvenance(
        catturato_il=clock().isoformat(),
        configurazione_canonica=dict(current_canonical_config()),
    )


def save_outcome(path: Path, outcome: CaptureOutcome) -> None:
    """Serialize an outcome to file (creates the folders).

    ``newline=""``: no translation. On Windows the default wrote CRLF against
    the LF blob in git, and with ``core.autocrlf=false`` every re-capture showed up
    modified over the whole file (with ``.gitattributes`` ``* text=auto eol=lf`` the
    diff is instead empty; same class as
    :func:`~crime_risk_analyzer.eval.snapshots.save_snapshot`).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        outcome.model_dump_json(indent=2) + "\n", encoding="utf-8", newline=""
    )


def load_outcome(path: Path) -> CaptureOutcome:
    """Load an outcome from a versioned snapshot."""
    return CaptureOutcome.model_validate_json(path.read_text(encoding="utf-8"))


async def capture_city(
    citta: str,
    zona: str,
    *,
    poi_source: PoiSource | None = None,
    boundary_source: BoundarySource = fetch_city_boundary,
) -> CityCapture:
    """Live capture: geocode + fetch POI (timed) + city polygon (not timed)."""
    # INTERACTIVE retry policy on purpose, not the offline one of #232:
    # here wall-clock time IS the metric (``switch_ms``, time to add a new
    # city). A courtesy backoff of minutes would falsify it, measuring
    # Overpass congestion instead of the switch cost. If the roster capture
    # fails, it is rerun: there is nothing to preserve as in a run.
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
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Capture every city of the roster isolating per-city failures (M3).

    Every outcome (ok and failed) carries the provenance (#374). ``clock`` is an
    injectable callable, not a string: the instant is not fabricated by hand (as in
    ``save_snapshot``).
    """
    for city in roster:
        try:
            capture = await capture_city(
                city.citta,
                city.zona,
                poi_source=poi_source,
                boundary_source=boundary_source,
            )
            outcome = CaptureOutcome(
                status="ok",
                citta=city.citta,
                zona=city.zona,
                capture=capture,
                provenienza=_current_provenance(clock),
            )
        except (GeocodingError, OverpassError) as exc:
            outcome = CaptureOutcome(
                status="failed",
                citta=city.citta,
                zona=city.zona,
                error_type=type(exc).__name__,
                error=str(exc),
                provenienza=_current_provenance(clock),
            )
        save_outcome(capture_path(results_dir, city.citta), outcome)
