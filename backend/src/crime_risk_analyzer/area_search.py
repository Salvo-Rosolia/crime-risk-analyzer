"""Risolve l'AREA di analisi in un GeoSource iniettabile, nelle due modalita'.

Le due modalita' di ricerca COESISTONO e l'utente usa l'una o l'altra:

* :func:`resolve_circle` — il cerchio disegnato sulla mappa (centro+raggio, #318),
  bbox calcolato puramente, nessuna chiamata di rete in quel calcolo;
* :func:`resolve_zone` — i due campi citta + zona, bbox da Nominatim col pavimento
  minimo gia' tarato (:func:`~crime_risk_analyzer.geocoding.geocode_zone`).

Entrambe ritornano lo STESSO contratto ``(citta, zona, geo_source)``, quindi il
resto della pipeline non sa quale modalita' sia stata usata. E' il punto di
estensione ``geo_source`` che :mod:`crime_risk_analyzer.rag.retrieval` espone gia'
per il replay in ``eval/`` (#169) a rendere possibile questa simmetria: aggiungere
una modalita' di ricerca non tocca ne' ``retrieve`` ne' l'harness di valutazione.

Due asimmetrie volute fra le modalita':

* etichette — il cerchio non ha testo, quindi le prende dal reverse geocode del
  centro; con citta + zona il testo digitato E' l'area, e resta l'etichetta;
* errori — nel cerchio il reverse geocode e' COSMETICO e non blocca mai; con
  citta + zona il geocode DETERMINA l'area analizzata, quindi una zona non trovata
  e' un errore vero e non degrada a un'area di ripiego.
"""

from __future__ import annotations

from fastapi.concurrency import run_in_threadpool

from crime_risk_analyzer.geocoding import (
    GeoResult,
    geocode_zone,
    reverse_geocode_label,
)
from crime_risk_analyzer.models.geo import bbox_from_circle
from crime_risk_analyzer.rag.retrieval import GeoSource

__all__ = ["resolve_circle", "resolve_zone"]


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


async def resolve_zone(citta: str, zona: str) -> tuple[str, str, GeoSource]:
    """(citta, zona) + un GeoSource per la coppia di campi testuali.

    L'area e' il bounding box che Nominatim restituisce per "zona, citta", col
    pavimento minimo di :func:`~crime_risk_analyzer.geocoding.geocode_zone` — non
    il raggio corrente attorno al punto geocodificato: e' il comportamento storico
    della ricerca per testo, gia' tarato, e non un comportamento nuovo.

    Etichette: sono (citta, zona) COME DIGITATI (gia' ripuliti dal contratto), non
    il reverse geocode del punto come nel cerchio. Il motivo e' la ricostruzione
    del contesto: quando ``zone_context_cache`` l'ha scaduto o sfrattato,
    ``/analyze/narrativa`` e ``/analyze/poi`` lo ricostruiscono rifacendo
    ``geocode_zone`` sulle etichette ricevute dal client. Col testo digitato si
    torna alla STESSA area, deterministicamente; con un'etichetta del reverse
    geocode si finirebbe su un'area diversa (o su nessuna), quindi un 409. Nel
    cerchio quella via non esiste comunque — non c'e' testo da ricercare — e
    l'etichetta resta cosmetica.

    Non riapre la superficie del non-fidato: le lunghezze sono limitate dal
    contratto, ``zona`` e' normalizzata come dato esterno prima del prompt di zona
    (:func:`~crime_risk_analyzer.rag.generation.build_context_str`) e ``citta``
    lo e' nel prompt per-POI. E nessuna seconda chiamata a Nominatim.

    Args:
        citta: Citta' digitata dall'utente (es. ``"Roma"``).
        zona: Zona/quartiere digitato dall'utente (es. ``"Colosseo"``).

    Returns:
        Tupla (citta, zona, geo_source), stesso contratto di :func:`resolve_circle`.

    Raises:
        ZoneNotFoundError: zona inesistente nella citta' o priva di bounding box.
        GeocodingError: Nominatim non raggiungibile.
    """
    geo = await run_in_threadpool(geocode_zone, zona, citta)

    async def _geo_source(_citta: str, _zona: str) -> GeoResult:
        return geo

    return citta, zona, _geo_source
