"""Tests for the shared Bbox type (#59).

A single ``Bbox`` (NamedTuple with named fields) lives in
``crime_risk_analyzer.models.geo`` and is reused by both ``geocoding`` and
``overpass_client`` (previously duplicated in both). The semantic order stays
``(min_lat, min_lon, max_lat, max_lon)`` and compatibility with the flat tuple
is preserved.
"""

from __future__ import annotations

import math

from crime_risk_analyzer.eval import geometry as eval_geometry
from crime_risk_analyzer.models.geo import (
    Bbox,
    CityBoundary,
    bbox_from_circle,
    boundary_from_geojson,
    point_in_multipolygon,
)


def test_bbox_center_is_the_midpoint() -> None:
    """The center of the queried area, used to sort the POIs by proximity.

    It is the midpoint of the bbox and not the Nominatim one: the selection lives
    in ``fetch_pois``, which has the bbox but not the ``GeoResult``, and making the
    sorting depend on the geo would make it load-bearing in the evaluation chain,
    where the runs use a placeholder (#169).
    """
    bbox = Bbox(min_lat=41.88, min_lon=12.48, max_lat=41.90, max_lon=12.52)

    assert bbox.center() == (41.89, 12.50)


def test_bbox_named_fields() -> None:
    bbox = Bbox(min_lat=41.88, min_lon=12.48, max_lat=41.90, max_lon=12.50)

    assert bbox.min_lat == 41.88
    assert bbox.min_lon == 12.48
    assert bbox.max_lat == 41.90
    assert bbox.max_lon == 12.50


def test_bbox_is_tuple_compatible() -> None:
    bbox = Bbox(41.88, 12.48, 41.90, 12.50)

    # Comparison with the flat tuple and unpacking in the canonical semantic order.
    assert bbox == (41.88, 12.48, 41.90, 12.50)
    min_lat, min_lon, max_lat, max_lon = bbox
    assert (min_lat, min_lon, max_lat, max_lon) == (41.88, 12.48, 41.90, 12.50)


def test_geocoding_and_overpass_share_same_bbox() -> None:
    from crime_risk_analyzer.geocoding import Bbox as GeoBbox
    from crime_risk_analyzer.overpass_client import Bbox as OverpassBbox

    assert GeoBbox is Bbox
    assert OverpassBbox is Bbox


def test_bbox_from_circle_symmetric_around_center() -> None:
    bbox = bbox_from_circle(41.9028, 12.4964, 500.0)
    lat_mid = (bbox.min_lat + bbox.max_lat) / 2
    lon_mid = (bbox.min_lon + bbox.max_lon) / 2
    assert math.isclose(lat_mid, 41.9028, abs_tol=1e-9)
    assert math.isclose(lon_mid, 12.4964, abs_tol=1e-9)


def test_bbox_from_circle_larger_radius_larger_bbox() -> None:
    small = bbox_from_circle(41.9, 12.5, 200.0)
    large = bbox_from_circle(41.9, 12.5, 2000.0)
    assert (large.max_lat - large.min_lat) > (small.max_lat - small.min_lat)
    assert (large.max_lon - large.min_lon) > (small.max_lon - small.min_lon)


def test_bbox_from_circle_lat_half_span_consistent_with_meters() -> None:
    # Pins the FORMULA of bbox_from_circle (meters per degree of latitude derived
    # from the IUGG earth radius, the same as haversine_m: _EARTH_RADIUS_M in
    # models/geo.py, not imported here so as not to touch a private symbol of the
    # module), not an independent magic number: before the unification the literal
    # 111_320 lived here, corresponding to a slightly different radius (~6378.1 km
    # equatorial).
    earth_radius_m = 6_371_008.8  # == crime_risk_analyzer.models.geo._EARTH_RADIUS_M
    meters_per_degree_lat = earth_radius_m * math.pi / 180
    bbox = bbox_from_circle(0.0, 0.0, 500.0)
    assert math.isclose(bbox.max_lat - 0.0, 500.0 / meters_per_degree_lat, rel_tol=1e-9)


def test_ray_casting_lives_in_models_geo() -> None:
    """#345: the grounding (not just eval/) must know in which place a POI falls."""
    square = boundary_from_geojson(
        {
            "type": "Polygon",
            "coordinates": [
                [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]
            ],
        }
    )
    assert point_in_multipolygon((1.0, 1.0), square)
    assert not point_in_multipolygon((3.0, 1.0), square)


def test_eval_geometry_reexports_the_same_objects() -> None:
    """One implementation: eval/ imports from models.geo, it keeps no copy."""
    assert eval_geometry.CityBoundary is CityBoundary
    assert eval_geometry.point_in_multipolygon is point_in_multipolygon
    assert eval_geometry.boundary_from_geojson is boundary_from_geojson
