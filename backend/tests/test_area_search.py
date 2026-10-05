"""Test dei resolver di area: cerchio disegnato e coppia citta + zona."""

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


def _fake_geocode_zone(zona: str, citta: str) -> GeoResult:
    return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))


@pytest.mark.asyncio
async def test_resolve_zone_ritorna_etichetta_e_geo_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La modalita' citta + zona produce lo stesso contratto del cerchio.

    Le due modalita' di ricerca coesistono e l'utente usa l'una o l'altra: a
    valle il resto della pipeline non deve sapere quale sia stata usata, quindi
    entrambe ritornano (citta, zona, geo_source). Qui il bbox arriva da
    Nominatim (`geocode_zone`), non dal calcolo centro+raggio.
    """
    chiamate: list[tuple[str, str]] = []

    def _recording_geocode_zone(zona: str, citta: str) -> GeoResult:
        chiamate.append((zona, citta))
        return _fake_geocode_zone(zona, citta)

    monkeypatch.setattr(area_search, "geocode_zone", _recording_geocode_zone)

    _, _, geo_source = await area_search.resolve_zone("Roma", "Colosseo")

    assert chiamate == [("Colosseo", "Roma")]
    geo = await geo_source("qualsiasi", "cosa")
    assert geo["bbox"] == (41.88, 12.48, 41.90, 12.50)
    assert geo["lat"] == 41.89
    assert geo["lon"] == 12.49


@pytest.mark.asyncio
async def test_resolve_zone_etichette_sono_quelle_digitate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le etichette sono (citta, zona) digitati, e nessun reverse geocode parte.

    Le rotte di fase 2 (``/analyze/narrativa``, ``/analyze/poi``) ricostruiscono
    il contesto scaduto rifacendo ``geocode_zone`` sulle etichette: solo il testo
    digitato riporta alla STESSA area. Un'etichetta dal reverse geocode darebbe
    un'area diversa, quindi un 409.
    """

    def _reverse_vietato(lat: float, lon: float) -> tuple[str, str]:
        raise AssertionError("la modalita' zona non deve chiamare il reverse")

    monkeypatch.setattr(area_search, "geocode_zone", _fake_geocode_zone)
    monkeypatch.setattr(area_search, "reverse_geocode_label", _reverse_vietato)

    citta, zona, _ = await area_search.resolve_zone("Roma", "Colosseo")

    assert (citta, zona) == ("Roma", "Colosseo")


@pytest.mark.asyncio
async def test_resolve_zone_propaga_la_zona_non_trovata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una zona inesistente resta un errore, non un'area di ripiego.

    Asimmetria voluta col cerchio: li' il reverse geocode e' cosmetico e non
    blocca mai, qui il geocode DETERMINA l'area analizzata — fallire in
    silenzio significherebbe analizzare un posto a caso.
    """

    def _raise(zona: str, citta: str) -> GeoResult:
        raise ZoneNotFoundError(f"Zona non trovata: {zona!r} in {citta!r}")

    monkeypatch.setattr(area_search, "geocode_zone", _raise)

    with pytest.raises(ZoneNotFoundError):
        await area_search.resolve_zone("Roma", "Atlantide")
