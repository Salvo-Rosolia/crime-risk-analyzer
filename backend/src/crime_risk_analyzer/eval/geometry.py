"""Geometria per la validazione confini (#31): ora vive in ``models.geo`` (#345).

Il ray casting serve anche al grounding (luogo ISTAT di un POI), quindi e' passato
nel modulo dei tipi geografici condivisi. Questo modulo resta come re-export per
``eval/city_agnostic.py`` e i test di #31: stessi oggetti, nessuna copia.
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
