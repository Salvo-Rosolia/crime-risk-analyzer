"""Test di circle_search.resolve_circle (#318)."""

from __future__ import annotations

import pytest

from crime_risk_analyzer import circle_search
from crime_risk_analyzer.models.geo import bbox_from_circle


@pytest.mark.asyncio
async def test_resolve_circle_ritorna_etichetta_e_geo_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_circle ritorna (citta, zona, geo_source).

    Il geo_source ignora gli argomenti e ritorna sempre lo stesso GeoResult.
    """
    def _fake_reverse_geocode(lat: float, lon: float) -> tuple[str, str]:
        return ("Roma", "Trastevere")

    monkeypatch.setattr(circle_search, "reverse_geocode_label", _fake_reverse_geocode)
    citta, zona, geo_source = await circle_search.resolve_circle(41.89, 12.47, 500.0)
    assert citta == "Roma"
    assert zona == "Trastevere"

    # geo_source ignora gli argomenti e ritorna sempre lo stesso GeoResult
    geo = await geo_source("qualsiasi", "cosa")
    assert geo["lat"] == 41.89
    assert geo["lon"] == 12.47
    assert geo["bbox"] == bbox_from_circle(41.89, 12.47, 500.0)
