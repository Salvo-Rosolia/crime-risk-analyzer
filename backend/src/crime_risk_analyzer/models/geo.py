"""Shared geographic types (#59).

:class:`Bbox` is the bounding box used both by geocoding (Nominatim -> bbox) and
by the Overpass client (bbox -> OSM query). It used to be duplicated as
``tuple[float, float, float, float]`` in both modules; here it lives only
once, with named fields that make the semantic order explicit.

Being a :class:`~typing.NamedTuple`, it remains fully compatible with the
flat tuple: unpacking ``min_lat, min_lon, max_lat, max_lon = bbox`` and comparison
``bbox == (..., ...)`` keep working.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import NamedTuple, cast

from pydantic import BaseModel

#: Mean Earth radius in metres (IUGG).
_EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres between two coordinates (haversine).

    Haversine and not a flat projection: the cost is irrelevant on the few
    hundred points involved and it does not introduce a projection error to
    justify. It lives here, next to :class:`Bbox`, because it is used by two layers
    that cannot import each other — the POI selection in
    ``overpass_client`` and the per-POI neighbourhood in ``rag.poi_context``.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bbox_from_circle(lat: float, lon: float, radius_m: float) -> Bbox:
    """Rectangular bbox circumscribing the circle.

    (centre ``lat``/``lon``, radius in metres, #318)
    Approximate degree/metre conversion: the metres per degree of latitude are
    derived from ``_EARTH_RADIUS_M`` (meridian circumference ``2*pi*R`` over 360
    degrees) instead of an independent literal (before ``111_320``, which
    corresponds to a slightly different radius, ~6378.1 km equatorial) — so
    this function and :func:`haversine_m`, in the same module, do not use two
    different Earth radii (~0.11% discrepancy between the two). The half-width
    in longitude narrows with ``cos(lat)`` because the meridians converge
    towards the poles. Pure: no network call, unlike the bbox from
    geocoding (:mod:`crime_risk_analyzer.geocoding`).
    """
    meters_per_degree_lat = _EARTH_RADIUS_M * math.pi / 180
    half_lat_deg = radius_m / meters_per_degree_lat
    coslat = math.cos(math.radians(lat))
    half_lon_deg = (
        radius_m / (meters_per_degree_lat * coslat) if coslat > 1e-9 else half_lat_deg
    )
    return Bbox(
        min_lat=lat - half_lat_deg,
        min_lon=lon - half_lon_deg,
        max_lat=lat + half_lat_deg,
        max_lon=lon + half_lon_deg,
    )


def bbox_side_m(bbox: Bbox) -> tuple[float, float]:
    """Approximate ``(height_m, width_m)`` of ``bbox``, from the same Earth radius.

    The width is measured at the mid latitude (meridians converge with
    ``cos(lat)``) and the longitude span is taken modulo 360, so a bbox crossing
    the antimeridian (``min_lon > max_lon``) gets a positive width. Consistent
    with :func:`bbox_from_circle`: a circle of radius
    ``r`` gives a bbox of ``(2r, 2r)``.
    """
    meters_per_degree_lat = _EARTH_RADIUS_M * math.pi / 180
    mid_lat = (bbox.min_lat + bbox.max_lat) / 2
    height = (bbox.max_lat - bbox.min_lat) * meters_per_degree_lat
    width = (
        ((bbox.max_lon - bbox.min_lon) % 360)
        * meters_per_degree_lat
        * math.cos(math.radians(mid_lat))
    )
    return height, width


class Bbox(NamedTuple):
    """Geographic bounding box in the order ``(min_lat, min_lon, max_lat, max_lon)``.

    It matches the Overpass order ``(south, west, north, east)``.
    """

    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    def center(self) -> tuple[float, float]:
        """Midpoint ``(lat, lon)`` of the queried area.

        It is the reference for ordering the POIs by proximity (#254). It is not the
        point returned by Nominatim: the selection lives in ``fetch_pois``, which
        has the bbox and not the ``GeoResult``, and depending on the geo would make it
        load-bearing in the evaluation chain, where the runs inject a
        placeholder (#169). ``geocoding._enforce_min_bbox`` preserves the midpoint
        of the BBOX, which is not the point returned by Nominatim (for a
        way/relation geometry that is a computed centroid): on a landmark zone the two
        practically coincide, on a wide or elongated zone they can be hundreds of
        metres apart, and the map centres on the latter.

        The choice is a COMPROMISE, not a necessity: the provenance of the
        snapshots records the real bbox, so a replay could reselect while
        staying hermetic. The price paid here is that the snapshot keeps a
        derived sample, and every evolution of the selection policy requires
        a live re-capture.
        """
        return (
            (self.min_lat + self.max_lat) / 2,
            (self.min_lon + self.max_lon) / 2,
        )


# --- Ray casting of the boundaries (#31, moved here from eval/geometry.py with #345)
# --- The grounding must know in which municipality or province a POI falls (ISTAT data,
# #345): the geometry is no longer only an evaluation tool. Points in
# GeoJSON order ``(lon, lat)``; no external dependency (even-odd ray casting
# with multipolygons and holes, e.g. Vatican City inside Rome).

Point = tuple[float, float]  # (lon, lat)
Ring = list[Point]
Polygon = list[Ring]  # ring[0] = outer ring; ring[1:] = holes


class CityBoundary(BaseModel):
    """Normalised administrative polygon (multipolygon with possible holes)."""

    polygons: list[Polygon]


def point_in_ring(point: Point, ring: Ring) -> bool:
    """True if ``point`` is inside ``ring`` (even-odd ray casting)."""
    x, y = point
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def point_in_polygon(point: Point, polygon: Polygon) -> bool:
    """Inside the outer ring and outside every hole."""
    if not polygon or not point_in_ring(point, polygon[0]):
        return False
    return not any(point_in_ring(point, hole) for hole in polygon[1:])


def point_in_multipolygon(point: Point, boundary: CityBoundary) -> bool:
    """Inside at least one of the polygons of the boundary."""
    return any(point_in_polygon(point, poly) for poly in boundary.polygons)


def boundary_from_geojson(geometry: Mapping[str, object]) -> CityBoundary:
    """Normalises a GeoJSON geometry (Polygon|MultiPolygon) into CityBoundary."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Polygon":
        raw: object = [coords]
    elif gtype == "MultiPolygon":
        raw = coords
    else:
        raise ValueError(f"Tipo GeoJSON non supportato: {gtype!r}")
    try:
        polygons: list[Polygon] = [
            [[(float(pt[0]), float(pt[1])) for pt in ring] for ring in poly]
            for poly in cast("list[list[list[list[float]]]]", raw)
        ]
    except (TypeError, IndexError, ValueError) as exc:
        raise ValueError("Coordinate GeoJSON malformate") from exc
    return CityBoundary(polygons=polygons)
