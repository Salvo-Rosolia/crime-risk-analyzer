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

import math
from typing import NamedTuple

#: Raggio medio terrestre in metri (IUGG).
_EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in metri fra due coordinate (haversine).

    Haversine e non una proiezione piana: il costo e' irrilevante sulle poche
    centinaia di punti in gioco e non introduce un errore di proiezione da
    giustificare. Vive qui, accanto a :class:`Bbox`, perche' la usano due layer
    che non possono importarsi a vicenda — la selezione dei POI in
    ``overpass_client`` e il vicinato per-POI in ``rag.poi_context``.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


class Bbox(NamedTuple):
    """Bounding box geografico nell'ordine ``(min_lat, min_lon, max_lat, max_lon)``.

    Corrisponde all'ordine Overpass ``(south, west, north, east)``.
    """

    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    def center(self) -> tuple[float, float]:
        """Punto medio ``(lat, lon)`` dell'area interrogata.

        E' il riferimento per ordinare i POI per prossimita' (#254). Non e' il
        punto restituito da Nominatim: la selezione vive in ``fetch_pois``, che
        ha il bbox e non il ``GeoResult``, e dipendere dal geo lo renderebbe
        portante nella catena di valutazione, dove le run iniettano un
        placeholder (#169). ``geocoding._enforce_min_bbox`` preserva il punto medio
        del BBOX, che non e' il punto restituito da Nominatim (per una geometria
        way/relation quello e' un centroide calcolato): su una zona-landmark i due
        praticamente coincidono, su una zona ampia o allungata possono distare
        centinaia di metri, e la mappa si centra sul secondo.

        La scelta e' un COMPROMESSO, non una necessita': la provenienza degli
        snapshot registra il bbox reale, quindi un replay potrebbe riselezionare
        restando ermetico. Il prezzo pagato qui e' che lo snapshot conserva un
        campione derivato, e ogni evoluzione della politica di selezione richiede
        una ri-cattura live.
        """
        return (
            (self.min_lat + self.max_lat) / 2,
            (self.min_lon + self.max_lon) / 2,
        )
