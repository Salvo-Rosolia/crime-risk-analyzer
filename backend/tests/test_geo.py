"""Test del tipo Bbox condiviso (#59).

Un solo ``Bbox`` (NamedTuple con campi nominati) vive in
``crime_risk_analyzer.models.geo`` ed e' riusato sia da ``geocoding`` sia da
``overpass_client`` (prima duplicato in entrambi). L'ordine semantico resta
``(min_lat, min_lon, max_lat, max_lon)`` e la compatibilita' con la tupla
piatta e' preservata.
"""

from __future__ import annotations

from crime_risk_analyzer.models.geo import Bbox


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
