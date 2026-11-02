"""ISTAT place of a point (#345, spec 4.3 / D5).

Provincial capitals first, then provinces: the capital's data is the closest to
the POI that ISTAT publishes. Bounding-box filter before the ray casting (214
places). Outside every polygon (sea, abroad, holes left by the simplification)
-> ``None``. The order of the places is the loading one (type, code): between two
overlapping polygons of the same type the lower code wins, always the same one.
"""

from __future__ import annotations

from crime_risk_analyzer.istat.data import (
    IstatData,
    Place,
    PlaceType,
    istat_data_or_none,
)
from crime_risk_analyzer.models.geo import point_in_multipolygon

__all__ = ["place_of"]

_PRIORITY: tuple[PlaceType, ...] = ("comune", "provincia")


def _in_bbox(place: Place, lat: float, lon: float) -> bool:
    min_lon, min_lat, max_lon, max_lat = place.bbox
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def place_of(lat: float, lon: float, *, data: IstatData | None = None) -> Place | None:
    """Provincial capital or province containing ``(lat, lon)``, or ``None``."""
    source = data if data is not None else istat_data_or_none()
    if source is None:
        return None
    for place_type in _PRIORITY:
        for place in source.luoghi:
            if (
                place.tipo == place_type
                and _in_bbox(place, lat, lon)
                and point_in_multipolygon((lon, lat), place.confine)
            ):
                return place
    return None
