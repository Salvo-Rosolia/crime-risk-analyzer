"""Tests for the shared test helpers in ``_doubles`` (#465)."""

from __future__ import annotations

from crime_risk_analyzer.models.risk import PoiRiskProfile
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
    poi = make_poi(
        id="node/2",
        lon=12.5,
        osm_tags="amenity=school",
        ontology_class="School",
        citta="Milano",
    )

    assert poi["id"] == "node/2"
    assert poi["lon"] == 12.5
    assert poi["osm_tags"] == "amenity=school"
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


def test_fake_profiler_returns_the_canned_profile_for_the_requested_class() -> None:
    bank = PoiRiskProfile(ontology_class="Bank", hazards=["Bank_robbery"])

    profile = FakeProfiler({"Bank": bank}).profile("Bank")

    assert profile is bank


def test_fake_profiler_returns_an_empty_profile_for_an_unknown_class() -> None:
    profiler = FakeProfiler({"Bank": PoiRiskProfile(ontology_class="Bank")})

    profile = profiler.profile("School")

    assert profile == PoiRiskProfile(ontology_class="School")
    assert profile.hazards == []


def test_fake_profiler_keeps_the_given_dict_so_it_can_be_filled_later() -> None:
    profiles: dict[str, PoiRiskProfile] = {}
    profiler = FakeProfiler(profiles)
    bank = PoiRiskProfile(ontology_class="Bank", hazards=["Bank_robbery"])

    profiles["Bank"] = bank

    assert profiler.profile("Bank") is bank
