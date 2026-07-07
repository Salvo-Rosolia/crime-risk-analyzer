"""Geometria per la validazione confini (#31): ray casting dependency-free.

Punti in ordine GeoJSON ``(lon, lat)``. Nessuna dipendenza esterna: il test
"punto dentro il poligono" usa ray casting even-odd, con supporto a
multipoligoni e buchi (es. Città del Vaticano dentro Roma).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pydantic import BaseModel

Point = tuple[float, float]  # (lon, lat)
Ring = list[Point]
Polygon = list[Ring]  # ring[0] = anello esterno; ring[1:] = buchi


class CityBoundary(BaseModel):
    """Poligono amministrativo normalizzato (multipoligono con eventuali buchi)."""

    polygons: list[Polygon]


def point_in_ring(point: Point, ring: Ring) -> bool:
    """True se ``point`` è dentro ``ring`` (ray casting even-odd)."""
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
    """Dentro l'anello esterno e fuori da ogni buco."""
    if not polygon or not point_in_ring(point, polygon[0]):
        return False
    return not any(point_in_ring(point, hole) for hole in polygon[1:])


def point_in_multipolygon(point: Point, boundary: CityBoundary) -> bool:
    """Dentro almeno uno dei poligoni del confine."""
    return any(point_in_polygon(point, poly) for poly in boundary.polygons)


def boundary_from_geojson(geometry: Mapping[str, object]) -> CityBoundary:
    """Normalizza una geometria GeoJSON (Polygon|MultiPolygon) in CityBoundary."""
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
