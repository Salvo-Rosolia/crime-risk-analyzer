"""Tipi geografici condivisi (#59).

:class:`Bbox` e' il bounding box usato sia dal geocoding (Nominatim -> bbox) sia
dal client Overpass (bbox -> query OSM). Prima era duplicato come
``tuple[float, float, float, float]`` in entrambi i moduli; qui vive una volta
sola, con campi nominati che rendono esplicito l'ordine semantico.

Essendo una :class:`~typing.NamedTuple`, resta pienamente compatibile con la
tupla piatta: unpacking ``min_lat, min_lon, max_lat, max_lon = bbox`` e confronto
``bbox == (..., ...)`` continuano a funzionare.
"""

from __future__ import annotations

from typing import NamedTuple


class Bbox(NamedTuple):
    """Bounding box geografico nell'ordine ``(min_lat, min_lon, max_lat, max_lon)``.

    Corrisponde all'ordine Overpass ``(south, west, north, east)``.
    """

    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float
