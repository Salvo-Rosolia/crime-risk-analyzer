"""Fase 1 (#259): risposta strutturata veloce, narrativa non ancora generata."""

from __future__ import annotations

from crime_risk_analyzer import zone_context_cache
from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.overpass_client import Poi

_BANK = PoiRiskProfile(
    terminus_class="Bank",
    hazards=["Bank_robbery"],
    vulnerabilities=["Accesso non controllato"],
    sparql_paths=["Bank → havingHazard → Bank_robbery"],
)


class _FakeProfiler:
    def profile(self, terminus_class: str) -> PoiRiskProfile:
        return {"Bank": _BANK}.get(
            terminus_class, PoiRiskProfile(terminus_class=terminus_class)
        )


def _pois(citta: str) -> list[Poi]:
    return [
        {
            "id": "node/1",
            "name": "Banca A",
            "lat": 41.8900,
            "lon": 12.4920,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": citta,
        },
    ]


async def _geo_source(citta: str, zona: str) -> GeoResult:
    return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))


async def _poi_source(bbox: Bbox, citta: str) -> list[Poi]:
    return _pois(citta)


async def test_fast_response_has_no_narrativa_yet() -> None:
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast

    out = await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    assert out.narrativa is None
    assert out.fallback is False
    assert len(out.poi) == 1
    assert out.poi[0].id == "node/1"


async def test_fast_response_warms_the_zone_context_cache() -> None:
    """Stesso side-effect di `run_analysis()`: /analyze/narrative non deve
    rifare Overpass (#232)."""
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast

    await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    assert zone_context_cache.get("Roma", "Colosseo") is not None


async def test_fast_response_contesto_hash_matches_the_cached_context() -> None:
    """L'impronta restituita è quella che /analyze/narrative dovrà ricevere
    indietro per passare la verifica (#242)."""
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast
    from crime_risk_analyzer.context_fingerprint import fingerprint

    out = await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    cached = zone_context_cache.get("Roma", "Colosseo")
    assert cached is not None
    assert out.contesto_hash == fingerprint(cached["retrieval"]["pois"])
