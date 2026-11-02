"""Geometry for boundary validation (#31): now lives in ``models.geo`` (#345).

Ray casting is also needed by grounding (ISTAT place of a POI), so it moved
into the shared geographic-types module. This module stays as a re-export for
``eval/city_agnostic.py`` and the #31 tests: same objects, no copy.
"""

from __future__ import annotations

from crime_risk_analyzer.models.geo import (
    CityBoundary,
    Point,
    Polygon,
    Ring,
    boundary_from_geojson,
    point_in_multipolygon,
    point_in_polygon,
    point_in_ring,
)

__all__ = [
    "CityBoundary",
    "Point",
    "Polygon",
    "Ring",
    "boundary_from_geojson",
    "point_in_multipolygon",
    "point_in_polygon",
    "point_in_ring",
]
