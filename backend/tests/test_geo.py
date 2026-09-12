"""Test del tipo Bbox condiviso (#59).

Un solo ``Bbox`` (NamedTuple con campi nominati) vive in
``crime_risk_analyzer.models.geo`` ed e' riusato sia da ``geocoding`` sia da
``overpass_client`` (prima duplicato in entrambi). L'ordine semantico resta
``(min_lat, min_lon, max_lat, max_lon)`` e la compatibilita' con la tupla
piatta e' preservata.
"""

from __future__ import annotations

import math

from crime_risk_analyzer.models.geo import Bbox, bbox_from_circle


def test_bbox_center_is_the_midpoint() -> None:
    """Il centro dell'area interrogata, usato per ordinare i POI per prossimita'.

    E' il punto medio del bbox e non quello di Nominatim: la selezione vive in
    ``fetch_pois``, che ha il bbox ma non il ``GeoResult``, e far dipendere
    l'ordinamento dal geo lo renderebbe portante nella catena di valutazione,
    dove le run usano un placeholder (#169).
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

    # Confronto con tupla piatta e unpacking nell'ordine semantico canonico.
    assert bbox == (41.88, 12.48, 41.90, 12.50)
    min_lat, min_lon, max_lat, max_lon = bbox
    assert (min_lat, min_lon, max_lat, max_lon) == (41.88, 12.48, 41.90, 12.50)


def test_geocoding_and_overpass_share_same_bbox() -> None:
    from crime_risk_analyzer.geocoding import Bbox as GeoBbox
    from crime_risk_analyzer.overpass_client import Bbox as OverpassBbox

    assert GeoBbox is Bbox
    assert OverpassBbox is Bbox


def test_bbox_from_circle_simmetrico_su_centro() -> None:
    bbox = bbox_from_circle(41.9028, 12.4964, 500.0)
    lat_mid = (bbox.min_lat + bbox.max_lat) / 2
    lon_mid = (bbox.min_lon + bbox.max_lon) / 2
    assert math.isclose(lat_mid, 41.9028, abs_tol=1e-9)
    assert math.isclose(lon_mid, 12.4964, abs_tol=1e-9)


def test_bbox_from_circle_raggio_maggiore_bbox_piu_grande() -> None:
    piccolo = bbox_from_circle(41.9, 12.5, 200.0)
    grande = bbox_from_circle(41.9, 12.5, 2000.0)
    assert (grande.max_lat - grande.min_lat) > (piccolo.max_lat - piccolo.min_lat)
    assert (grande.max_lon - grande.min_lon) > (piccolo.max_lon - piccolo.min_lon)


def test_bbox_from_circle_semi_ampiezza_lat_coerente_con_metri() -> None:
    # Pinna la FORMULA di bbox_from_circle (metri per grado di latitudine derivati dal
    # raggio terrestre IUGG, lo stesso di haversine_m: _EARTH_RADIUS_M in models/geo.py,
    # non importato qui per non toccare un simbolo privato del modulo), non un magic
    # number indipendente: prima dell'unificazione qui viveva il letterale 111_320,
    # corrispondente a un raggio leggermente diverso (~6378.1 km equatoriale).
    earth_radius_m = 6_371_008.8  # == crime_risk_analyzer.models.geo._EARTH_RADIUS_M
    meters_per_degree_lat = earth_radius_m * math.pi / 180
    bbox = bbox_from_circle(0.0, 0.0, 500.0)
    assert math.isclose(bbox.max_lat - 0.0, 500.0 / meters_per_degree_lat, rel_tol=1e-9)
