"""Tests for the retrieval layer (#22): assembly of the raw context_dict.

retrieve() is pure wiring: the correctness of profile() is covered by
test_query_executor.py. Here we test the assembly, the memoization, the product
decisions (generic POIs included, graceful zero POIs) and the propagation of
domain errors. geocode_zone (sync) and fetch_pois (async) are mocked via
monkeypatch on the retrieval module namespace.
"""

from __future__ import annotations

import pytest

from crime_risk_analyzer.geocoding import GeoResult, ZoneNotFoundError
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.overpass_client import OverpassError, Poi
from crime_risk_analyzer.rag import retrieval
from crime_risk_analyzer.rag.retrieval import retrieve
from tests.eval._doubles import FakeProfiler, make_poi

_GEO: GeoResult = GeoResult(
    lat=41.9,
    lon=12.5,
    bbox=Bbox(min_lat=41.88, min_lon=12.48, max_lat=41.9, max_lon=12.5),
)


def _poi(
    poi_id: str, name: str, ontology_class: str, *, osm_tags: str = "amenity=bank"
) -> Poi:
    return Poi(
        id=poi_id,
        name=name,
        lat=41.9,
        lon=12.5,
        osm_tags=osm_tags,
        ontology_class=ontology_class,
        citta="Roma",
    )


def _patch_io(
    monkeypatch: pytest.MonkeyPatch, *, pois: list[Poi], geo: GeoResult = _GEO
) -> None:
    """Replaces geocode_zone (sync) and fetch_pois (async) in the retrieval module."""

    def _fake_geocode(zona: str, citta: str) -> GeoResult:
        return geo

    async def _fake_fetch(
        bbox: Bbox, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return list(pois)

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode)
    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)


async def test_retrieve_happy_path_multi_class(monkeypatch: pytest.MonkeyPatch) -> None:
    pois = [
        _poi("1", "Banca A", "Bank"),
        _poi("2", "Banca B", "Bank"),
        _poi("3", "Museo", "Museum", osm_tags="tourism=museum"),
    ]
    profiles = {
        "Bank": PoiRiskProfile(ontology_class="Bank", hazards=["Robbery"]),
        "Museum": PoiRiskProfile(ontology_class="Museum", hazards=["Theft"]),
    }
    _patch_io(monkeypatch, pois=pois)

    ctx = await retrieve("Roma", "Centro", executor=FakeProfiler(profiles))

    assert ctx["citta"] == "Roma"
    assert ctx["zona"] == "Centro"
    assert ctx["geo"] == _GEO
    assert ctx["pois"] == pois  # reused verbatim
    assert ctx["profiles"]["Bank"].hazards == ["Robbery"]
    assert ctx["profiles"]["Museum"].hazards == ["Theft"]
    assert ctx["stats"] == {"n_pois": 3, "n_classes": 2}


async def test_retrieve_profiles_once_per_distinct_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pois = [_poi("1", "A", "Bank"), _poi("2", "B", "Bank"), _poi("3", "C", "Bank")]
    _patch_io(monkeypatch, pois=pois)
    executor = FakeProfiler()

    await retrieve("Roma", "Centro", executor=executor)

    assert executor.calls == ["Bank"]  # only once despite 3 POIs


async def test_retrieve_includes_generic_poi_with_empty_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pois = [_poi("1", "Qualcosa", "GenericUrbanPOI", osm_tags="")]
    _patch_io(monkeypatch, pois=pois)

    ctx = await retrieve("Roma", "Centro", executor=FakeProfiler())

    assert len(ctx["pois"]) == 1
    prof = ctx["profiles"]["GenericUrbanPOI"]
    assert prof.hazards == []
    assert prof.vulnerabilities == []


async def test_retrieve_zero_pois_returns_empty_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_io(monkeypatch, pois=[])
    executor = FakeProfiler()

    ctx = await retrieve("Roma", "Zona Vuota", executor=executor)

    assert ctx["pois"] == []
    assert ctx["profiles"] == {}
    assert ctx["stats"] == {"n_pois": 0, "n_classes": 0}
    assert executor.calls == []


async def test_retrieve_propagates_zone_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(zona: str, citta: str) -> GeoResult:
        raise ZoneNotFoundError("unknown zone")

    async def _fetch(bbox: Bbox, citta: str, *a: object, **k: object) -> list[Poi]:
        return []

    monkeypatch.setattr(retrieval, "geocode_zone", _raise)
    monkeypatch.setattr(retrieval, "fetch_pois", _fetch)

    with pytest.raises(ZoneNotFoundError):
        await retrieve("Roma", "Ignota", executor=FakeProfiler())


async def test_retrieve_propagates_overpass_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _geocode(zona: str, citta: str) -> GeoResult:
        return _GEO

    async def _raise(bbox: Bbox, citta: str, *a: object, **k: object) -> list[Poi]:
        raise OverpassError("overpass down")

    monkeypatch.setattr(retrieval, "geocode_zone", _geocode)
    monkeypatch.setattr(retrieval, "fetch_pois", _raise)

    with pytest.raises(OverpassError):
        await retrieve("Roma", "Centro", executor=FakeProfiler())


async def test_retrieve_context_has_exact_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_io(monkeypatch, pois=[_poi("1", "A", "Bank")])

    ctx = await retrieve("Roma", "Centro", executor=FakeProfiler())

    assert set(ctx.keys()) == {"citta", "zona", "geo", "pois", "profiles", "stats"}
    assert set(ctx["stats"].keys()) == {"n_pois", "n_classes"}


async def test_retrieve_uses_injected_geo_source_without_geocoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With geo_source injected: geocode_zone NOT called, geo comes from the source."""

    def _boom_geocode(zona: str, citta: str) -> GeoResult:
        raise AssertionError("geocode_zone must not be called with geo_source")

    monkeypatch.setattr(retrieval, "geocode_zone", _boom_geocode)

    geo: GeoResult = GeoResult(lat=1.0, lon=2.0, bbox=Bbox(0.0, 0.0, 0.0, 0.0))
    geo_source_calls: list[tuple[str, str]] = []

    async def _geo_src(citta: str, zona: str) -> GeoResult:
        geo_source_calls.append((citta, zona))
        return geo

    async def _pois(bbox: Bbox, citta: str) -> list[Poi]:
        return []

    ctx = await retrieve(
        "Roma",
        "Colosseo",
        executor=FakeProfiler(),
        poi_source=_pois,
        geo_source=_geo_src,
    )
    assert geo_source_calls == [("Roma", "Colosseo")]  # order (citta, zona)
    assert ctx["geo"] == geo


async def test_retrieve_uses_injected_poi_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from crime_risk_analyzer.models.geo import Bbox
    from crime_risk_analyzer.rag import retrieval

    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        return {"lat": 41.89, "lon": 12.49, "bbox": Bbox(41.88, 12.48, 41.90, 12.50)}

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode)
    captured: list[str] = []

    async def fake_source(bbox: object, citta: str) -> list[Poi]:
        captured.append(citta)
        return [make_poi(id="1")]

    ctx = await retrieval.retrieve(
        "Roma",
        "Centro",
        executor=FakeProfiler(),
        poi_source=fake_source,  # type: ignore[arg-type]
    )
    assert captured == ["Roma"]
    assert ctx["pois"][0]["name"] == "Banca A"
