"""Risolve l'AREA di analisi in un GeoSource iniettabile, nelle due modalita'.

Le due modalita' di ricerca COESISTONO e l'utente usa l'una o l'altra:

* :func:`resolve_circle` — il cerchio disegnato sulla mappa (centro+raggio, #318),
  bbox calcolato puramente, nessuna chiamata di rete in quel calcolo;
* :func:`resolve_query` — una ricerca testuale libera, bbox da Nominatim col
  pavimento minimo gia' tarato (:func:`~crime_risk_analyzer.geocoding.geocode_query`).

Entrambe ritornano lo STESSO contratto ``(citta, zona, geo_source)``, quindi il
resto della pipeline non sa quale modalita' sia stata usata. E' il punto di
estensione ``geo_source`` che :mod:`crime_risk_analyzer.rag.retrieval` espone gia'
per il replay in ``eval/`` (#169) a rendere possibile questa simmetria: aggiungere
una modalita' di ricerca non tocca ne' ``retrieve`` ne' l'harness di valutazione.

Asimmetria voluta sugli errori: nel cerchio il reverse geocode e' COSMETICO (serve
solo l'etichetta mostrata in UI) e non blocca mai; nella ricerca testuale il geocode
DETERMINA l'area analizzata, quindi un luogo non trovato e' un errore vero e non
degrada a un'area di ripiego.
"""

from __future__ import annotations

from fastapi.concurrency import run_in_threadpool

from crime_risk_analyzer.geocoding import (
    GeoResult,
    geocode_query,
    reverse_geocode_label,
)
from crime_risk_analyzer.models.geo import bbox_from_circle
from crime_risk_analyzer.rag.retrieval import GeoSource

__all__ = ["resolve_circle", "resolve_query"]


async def resolve_circle(
    lat: float, lon: float, radius_m: float
) -> tuple[str, str, GeoSource]:
    """(citta, zona) best-effort da reverse geocode + un GeoSource per il cerchio.

    Args:
        lat: Latitudine del centro del cerchio.
        lon: Longitudine del centro del cerchio.
        radius_m: Raggio del cerchio in metri.

    Returns:
        Tupla (citta, zona, geo_source) dove geo_source e' un callable che ignora
        gli argomenti (citta, zona) e ritorna sempre lo stesso GeoResult.
    """
    citta, zona = await run_in_threadpool(reverse_geocode_label, lat, lon)
    bbox = bbox_from_circle(lat, lon, radius_m)

    async def _geo_source(_citta: str, _zona: str) -> GeoResult:
        return GeoResult(lat=lat, lon=lon, bbox=bbox)

    return citta, zona, _geo_source


async def resolve_query(query: str) -> tuple[str, str, GeoSource]:
    """(citta, zona) + un GeoSource per una ricerca TESTUALE libera.

    L'area e' il bounding box che Nominatim restituisce per ``query``, col
    pavimento minimo di :func:`~crime_risk_analyzer.geocoding.geocode_query` — non
    il raggio corrente attorno al punto geocodificato: e' il comportamento storico
    della ricerca per testo, gia' tarato, e non un comportamento nuovo.

    Le etichette passano comunque dal reverse geocode del punto risolto, non dal
    testo digitato: cosi' "colosseo" produce le stesse etichette pulite del cerchio
    disegnato sullo stesso punto, e la narrativa non eredita il fraseggio
    dell'utente. Costa una seconda chiamata a Nominatim (serializzata dal rate
    limiter), accettata per avere etichette uniformi fra le due modalita'.

    Args:
        query: Testo libero digitato dall'utente (es. ``"Colosseo, Roma"``).

    Returns:
        Tupla (citta, zona, geo_source), stesso contratto di :func:`resolve_circle`.

    Raises:
        ZoneNotFoundError: luogo inesistente o privo di bounding box utilizzabile.
        GeocodingError: Nominatim non raggiungibile.
    """
    geo = await run_in_threadpool(geocode_query, query)
    citta, zona = await run_in_threadpool(reverse_geocode_label, geo["lat"], geo["lon"])

    async def _geo_source(_citta: str, _zona: str) -> GeoResult:
        return geo

    return citta, zona, _geo_source
