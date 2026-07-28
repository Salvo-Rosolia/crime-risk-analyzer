"""Contesto spaziale del POI selezionato (#197): funzioni pure, offline."""

from __future__ import annotations

import pytest

from crime_risk_analyzer.i18n.terminus_labels import label_it
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.rag.poi_context import (
    haversine_m,
    nearest_neighbours,
    zone_composition,
)


def test_haversine_zero_for_same_point() -> None:
    assert haversine_m(41.8902, 12.4922, 41.8902, 12.4922) == pytest.approx(0.0)


def test_haversine_matches_known_distance() -> None:
    """Colosseo -> Circo Massimo, ~700 m in linea d'aria (tolleranza 15%)."""
    d = haversine_m(41.8902, 12.4922, 41.8859, 12.4854)
    assert d == pytest.approx(700.0, rel=0.15)


def _poi(poi_id: str, name: str, terminus_class: str, lat: float, lon: float) -> Poi:
    return Poi(
        id=poi_id,
        name=name,
        lat=lat,
        lon=lon,
        osm_tags="",
        terminus_class=terminus_class,
        citta="Roma",
    )


def _zone() -> list[Poi]:
    return [
        _poi("n1", "Banca Centrale", "Bank", 41.8900, 12.4920),
        _poi("n2", "Liceo Cavour", "School", 41.8901, 12.4921),
        _poi("n3", "Policlinico Celio", "Hospital", 41.8950, 12.4980),
        _poi("n4", "Commissariato Celio", "Police_station", 41.8902, 12.4922),
        _poi("n5", "Farmacia Colosseo", "Pharmacy", 41.9100, 12.5200),
    ]


def test_nearest_neighbours_excludes_the_selected_poi() -> None:
    out = nearest_neighbours(_zone(), "n1", k=5)
    assert all(n["name"] != "Banca Centrale" for n in out)


def test_nearest_neighbours_sorted_by_distance_and_capped_at_k() -> None:
    out = nearest_neighbours(_zone(), "n1", k=2)
    assert [n["name"] for n in out] == ["Liceo Cavour", "Commissariato Celio"]
    assert out[0]["distance_m"] <= out[1]["distance_m"]


def test_nearest_neighbours_breaks_distance_ties_by_id() -> None:
    """Due vicini equidistanti: ordine per id, non per ordine di lista."""
    pois = [
        _poi("sel", "Selezionato", "Bank", 41.8900, 12.4900),
        _poi("zz", "Zeta", "School", 41.8900, 12.4910),
        _poi("aa", "Alfa", "School", 41.8900, 12.4890),
    ]
    out = nearest_neighbours(pois, "sel", k=2)
    assert [n["name"] for n in out] == ["Alfa", "Zeta"]


def test_nearest_neighbours_uses_italian_label() -> None:
    out = nearest_neighbours(_zone(), "n1", k=1)
    assert out[0]["label_it"] != ""
    assert out[0]["label_it"] == label_it("School")


def test_nearest_neighbours_raises_when_poi_id_absent() -> None:
    with pytest.raises(KeyError, match="sconosciuto"):
        nearest_neighbours(_zone(), "non-esiste")


def test_nearest_neighbours_on_single_poi_zone_is_empty() -> None:
    assert nearest_neighbours([_poi("solo", "Unico", "Bank", 41.0, 12.0)], "solo") == []


def test_zone_composition_reports_total_and_top_classes() -> None:
    out = zone_composition(_zone(), top=2)
    assert "5" in out
    assert label_it("Bank") in out or label_it("School") in out


def test_zone_composition_dichiara_di_parlare_del_campione() -> None:
    """La riga entra nel prompt: non deve affermare fatti sulla ZONA (#254).

    I POI sono una selezione — i piu' vicini al centro, con un tetto per classe —
    quindi «20 punti di interesse nella zona» sarebbe falso sul totale e «classi
    prevalenti» un artefatto del tetto, che appiattisce i conteggi a un plateau.
    Il modello deve leggere che sta guardando un campione.
    """
    out = zone_composition(_zone(), top=2)

    assert "selezionati" in out
    assert "prevalenti" not in out


def test_zone_composition_breaks_count_ties_alphabetically() -> None:
    pois = [
        _poi("a", "A", "Bank", 41.0, 12.0),
        _poi("b", "B", "School", 41.0, 12.0),
    ]
    out = zone_composition(pois, top=2)
    labels = [label_it("Bank"), label_it("School")]
    first, second = sorted(labels)
    assert out.index(first) < out.index(second)


def test_zone_composition_of_empty_zone_is_explicit() -> None:
    assert "0" in zone_composition([])
