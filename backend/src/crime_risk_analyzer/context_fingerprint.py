"""Impronta del contesto di zona (#242).

``/analyze/poi`` deve poter dimostrare che la narrativa di un POI nasce sul
contesto che l'utente ha davanti, non su uno ricostruito diverso: OSM e' una
sorgente viva e il cap ``MAX_POIS`` puo' far entrare o uscire punti fra due
catture. L'impronta da' un'identita' confrontabile a una lista di POI, cosi'
l'endpoint puo' rifiutare (409) invece di generare prosa su un intorno che a
schermo non c'e'.

Non e' una misura di nulla: e' un digest opaco di identita' (nessuno scoring,
_project.md §Vincoli). Funzione PURA: nessuna I/O, nessuno stato.

Qui vive anche :data:`ContestoHash`, il tipo con cui le richieste ACCETTANO
un'impronta: la sua forma e' una proprieta' del digest prodotto da
:func:`fingerprint`, non delle rotte che lo ricevono.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated

from pydantic import Field

from crime_risk_analyzer.overpass_client import Poi

__all__ = ["ContestoHash", "fingerprint"]

#: Lunghezza esatta di un'impronta: l'hexdigest sha256 che :func:`fingerprint`
#: restituisce (32 byte, due caratteri per byte). Ancorata al digest reale da
#: ``test_la_richiesta_accetta_esattamente_la_lunghezza_del_digest``, cosi' un
#: cambio di algoritmo non puo' lasciare indietro il bound delle richieste.
_LUNGHEZZA_IMPRONTA = 64

#: Tipo del campo ``contesto_hash`` nei body che riportano un'impronta al server
#: (``POST /analyze/narrativa`` e ``POST /analyze/poi``). Alias condiviso e non
#: due ``Field`` gemelli: il vincolo e la sua motivazione sono gli stessi per
#: entrambe le rotte, e in duplice copia potevano divergere — una corretta e
#: l'altra a respingere impronte valide (o, peggio, ad accettarne di malformate).
ContestoHash = Annotated[
    str,
    Field(
        min_length=_LUNGHEZZA_IMPRONTA,
        max_length=_LUNGHEZZA_IMPRONTA,
        description=(
            "Impronta del contesto ricevuta dalla fase 1 di /analyze (#242), "
            "rimandata verbatim. E' CONFRONTATA e mai usata per costruire il "
            "prompt: un valore opaco che il server non consuma non puo' iniettare "
            "nulla. Obbligatoria: senza, la garanzia sarebbe opt-in. Lunghezza "
            "esatta di un digest sha256, cosi' un valore che non ha la forma di "
            "un'impronta esce come 422 prima di ogni I/O invece di costare, a "
            "cache fredda, una ricostruzione del contesto (geocoding + Overpass) "
            "per un rifiuto annunciato; il 409 resta per l'impronta ben formata "
            "che identifica un ALTRO contesto."
        ),
    ),
]


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
