"""Test dei resolver di area: cerchio disegnato e ricerca testuale."""

from __future__ import annotations

import pytest

from crime_risk_analyzer import area_search
from crime_risk_analyzer.geocoding import GeoResult, ZoneNotFoundError
from crime_risk_analyzer.models.geo import Bbox, bbox_from_circle


@pytest.mark.asyncio
async def test_resolve_circle_ritorna_etichetta_e_geo_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_circle ritorna (citta, zona, geo_source).

    Il geo_source ignora gli argomenti e ritorna sempre lo stesso GeoResult.
    """

    def _fake_reverse_geocode(lat: float, lon: float) -> tuple[str, str]:
        return ("Roma", "Trastevere")

    monkeypatch.setattr(area_search, "reverse_geocode_label", _fake_reverse_geocode)
    citta, zona, geo_source = await area_search.resolve_circle(41.89, 12.47, 500.0)
    assert citta == "Roma"
    assert zona == "Trastevere"

    # geo_source ignora gli argomenti e ritorna sempre lo stesso GeoResult
    geo = await geo_source("qualsiasi", "cosa")
    assert geo["lat"] == 41.89
    assert geo["lon"] == 12.47
    assert geo["bbox"] == bbox_from_circle(41.89, 12.47, 500.0)


@pytest.mark.asyncio
async def test_resolve_query_ritorna_etichetta_e_geo_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La modalita' TESTUALE produce lo stesso contratto del cerchio.

    Le due modalita' di ricerca coesistono e l'utente usa l'una o l'altra: a
    valle il resto della pipeline non deve sapere quale sia stata usata, quindi
    entrambe ritornano (citta, zona, geo_source). Qui il bbox arriva da
    Nominatim (`geocode_query`), non dal calcolo centro+raggio.
    """

    def _fake_geocode_query(query: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    def _fake_reverse_geocode(lat: float, lon: float) -> tuple[str, str]:
        return ("Roma", "Colosseo")

    monkeypatch.setattr(area_search, "geocode_query", _fake_geocode_query)
    monkeypatch.setattr(area_search, "reverse_geocode_label", _fake_reverse_geocode)

    citta, zona, geo_source = await area_search.resolve_query("Colosseo, Roma")

    assert citta == "Roma"
    assert zona == "Colosseo"

    geo = await geo_source("qualsiasi", "cosa")
    assert geo["bbox"] == (41.88, 12.48, 41.90, 12.50)
    assert geo["lat"] == 41.89
    assert geo["lon"] == 12.49


@pytest.mark.asyncio
async def test_resolve_query_propaga_il_luogo_non_trovato(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un luogo inesistente resta un errore, non un'area di ripiego.

    Asimmetria voluta col cerchio: li' il reverse geocode e' cosmetico e non
    blocca mai, qui il geocode DETERMINA l'area analizzata — fallire in
    silenzio significherebbe analizzare un posto a caso.
    """

    def _raise(query: str) -> GeoResult:
        raise ZoneNotFoundError(f"Luogo non trovato: {query!r}")

    monkeypatch.setattr(area_search, "geocode_query", _raise)

    with pytest.raises(ZoneNotFoundError):
        await area_search.resolve_query("Atlantide")
