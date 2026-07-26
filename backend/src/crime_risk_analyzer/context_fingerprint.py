"""Impronta del contesto di zona (#242).

``/analyze/poi`` deve poter dimostrare che la narrativa di un POI nasce sul
contesto che l'utente ha davanti, non su uno ricostruito diverso: OSM e' una
sorgente viva e il cap ``MAX_POIS`` puo' far entrare o uscire punti fra due
catture. L'impronta da' un'identita' confrontabile a una lista di POI, cosi'
l'endpoint puo' rifiutare (409) invece di generare prosa su un intorno che a
schermo non c'e'.

Non e' una misura di nulla: e' un digest opaco di identita' (nessuno scoring,
_project.md §Vincoli). Funzione PURA: nessuna I/O, nessuno stato.
"""

from __future__ import annotations

import hashlib
import json

from crime_risk_analyzer.overpass_client import Poi

__all__ = ["fingerprint"]


def fingerprint(pois: list[Poi]) -> str:
    """Hexdigest sha256 della lista di POI del contesto di zona.

    Entrano nel digest i soli campi che alimentano il prompt del POI: ``id``,
    ``name``, ``terminus_class`` (composizione della zona ed etichette IT) e
    ``lat``/``lon`` (distanze dei vicini). Restano fuori ``osm_tags`` e
    ``citta``, che non lo alimentano: un ritag su OSM non deve invalidare una
    narrativa ancora valida.

    SENSIBILE ALL'ORDINE per scelta: l'impronta identifica la lista *mostrata*
    all'utente — numerata in mappa e nella lista POI — non il solo insieme. Un
    riordino a contenuto invariato produce quindi un 409: falso positivo raro e
    nella direzione prudente (rifiutare invece di divergere).

    Serializzazione via ``json.dumps`` e non via join con separatore: un nome
    OSM puo' contenere qualunque carattere, e l'escaping JSON rende la
    serializzazione non ambigua per costruzione invece che per assunzione sui
    nomi. Il digest e' calcolato solo lato server (``/analyze`` e
    ``/analyze/poi``): il client lo rimanda opaco e non lo ricalcola, quindi la
    formattazione dei float non deve accordarsi fra Python e TypeScript.
    """
    canonico = json.dumps(
        [
            [poi["id"], poi["name"], poi["terminus_class"], poi["lat"], poi["lon"]]
            for poi in pois
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()
