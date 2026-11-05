"""Tests for the shared test helpers in ``_doubles`` (#465)."""

from __future__ import annotations

from tests.eval._doubles import FakeProfiler, make_poi


def test_make_poi_defaults() -> None:
    assert make_poi() == {
        "id": "node/1",
        "name": "Banca A",
        "lat": 41.89,
        "lon": 12.49,
        "osm_tags": "amenity=bank",
        "ontology_class": "Bank",
        "citta": "Roma",
    }


def test_make_poi_overrides_only_the_given_fields() -> None:
    poi = make_poi(id="node/2", ontology_class="School", citta="Milano")

    assert poi["id"] == "node/2"
    assert poi["ontology_class"] == "School"
    assert poi["citta"] == "Milano"
    assert poi["name"] == "Banca A"
    assert poi["lat"] == 41.89


def test_make_poi_returns_a_new_dict_each_call() -> None:
    first = make_poi()
    first["name"] = "mutated"

    second = make_poi()

    assert second is not first
    assert second["name"] == "Banca A"


def test_fake_profiler_records_requested_classes() -> None:
    profiler = FakeProfiler()

    profiler.profile("Bank")
    profiler.profile("School")

    assert profiler.calls == ["Bank", "School"]
