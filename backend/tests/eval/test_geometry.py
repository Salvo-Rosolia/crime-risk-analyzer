from __future__ import annotations

import pytest

from crime_risk_analyzer.eval.geometry import (
    CityBoundary,
    boundary_from_geojson,
    point_in_multipolygon,
    point_in_polygon,
    point_in_ring,
)


def test_point_in_ring_inside_and_outside() -> None:
    square = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
    assert point_in_ring((1.0, 1.0), square) is True
    assert point_in_ring((3.0, 1.0), square) is False


def test_point_in_polygon_with_hole() -> None:
    outer = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
    hole = [(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)]
    poly = [outer, hole]
    assert point_in_polygon((0.5, 0.5), poly) is True  # dentro, fuori dal buco
    assert point_in_polygon((2.0, 2.0), poly) is False  # nel buco → fuori
    assert point_in_polygon((5.0, 5.0), poly) is False  # fuori dall'esterno


def test_point_in_multipolygon() -> None:
    a = [[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]]
    b = [[(5.0, 5.0), (6.0, 5.0), (6.0, 6.0), (5.0, 6.0)]]
    boundary = CityBoundary(polygons=[a, b])
    assert point_in_multipolygon((0.5, 0.5), boundary) is True
    assert point_in_multipolygon((5.5, 5.5), boundary) is True
    assert point_in_multipolygon((3.0, 3.0), boundary) is False


def test_boundary_from_geojson_polygon() -> None:
    geom = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0]]],
    }
    boundary = boundary_from_geojson(geom)
    assert len(boundary.polygons) == 1
    assert point_in_multipolygon((1.0, 1.0), boundary) is True


def test_boundary_from_geojson_multipolygon() -> None:
    geom = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]],
            [[[5.0, 5.0], [6.0, 5.0], [6.0, 6.0], [5.0, 6.0]]],
        ],
    }
    boundary = boundary_from_geojson(geom)
    assert len(boundary.polygons) == 2


def test_boundary_from_geojson_rejects_unknown_type() -> None:
    with pytest.raises(ValueError):
        boundary_from_geojson({"type": "Point", "coordinates": [0.0, 0.0]})
