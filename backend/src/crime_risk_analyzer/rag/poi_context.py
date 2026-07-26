"""Contesto spaziale del POI selezionato (#197).

Funzioni PURE: nessuna I/O, nessun LLM, nessuno stato. Servono a rendere la
narrativa per-POI diversa fra POI della stessa classe: i rischi derivano solo
dalla classe TERMINUS, quindi senza contesto ogni banca riceverebbe lo stesso
testo. Il contesto e' il vicinato spaziale piu' la composizione della zona.

Ogni output ha ordinamento TOTALE dichiarato: due esecuzioni sullo stesso
contesto devono produrre lo stesso prompt, altrimenti ``repro.prompt_hash``
diverge e la run non e' ricostruibile.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import TypedDict

from crime_risk_analyzer.i18n.terminus_labels import label_it
from crime_risk_analyzer.overpass_client import Poi

__all__ = [
    "NeighbourPoi",
    "haversine_m",
    "nearest_neighbours",
    "zone_composition",
]

#: Raggio medio terrestre in metri (IUGG).
_EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in metri fra due coordinate (haversine).

    Haversine e non una proiezione piana: il costo e' irrilevante su una
    ventina di punti e non introduce un errore di proiezione da giustificare.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


class NeighbourPoi(TypedDict):
    """Un POI vicino, come entra nel prompt (nome, classe in IT, distanza)."""

    name: str
    label_it: str
    distance_m: int


def nearest_neighbours(
    pois: list[Poi], poi_id: str, *, k: int = 5
) -> list[NeighbourPoi]:
    """I ``k`` POI piu' vicini a ``poi_id``, escluso se stesso.

    Ordinamento totale: distanza crescente, a parita' di distanza ``id``
    crescente. Solleva :class:`KeyError` se ``poi_id`` non e' nella lista: il
    chiamante (endpoint) lo traduce in 404, non in una lista vuota che
    produrrebbe una narrativa senza contesto senza dirlo.
    """
    selected = next((p for p in pois if p["id"] == poi_id), None)
    if selected is None:
        raise KeyError(f"poi_id sconosciuto nel contesto di zona: {poi_id!r}")
    scored = [
        (haversine_m(selected["lat"], selected["lon"], p["lat"], p["lon"]), p["id"], p)
        for p in pois
        if p["id"] != poi_id
    ]
    scored.sort(key=lambda t: (t[0], t[1]))
    return [
        NeighbourPoi(
            name=p["name"],
            label_it=label_it(p["terminus_class"]),
            distance_m=round(distance),
        )
        for distance, _, p in scored[:k]
    ]


def zone_composition(pois: list[Poi], *, top: int = 3) -> str:
    """Riga di sintesi della zona: totale POI e classi piu' frequenti in IT.

    Ordinamento totale: conteggio decrescente, a parita' di conteggio etichetta
    in ordine alfabetico.
    """
    counts = Counter(label_it(p["terminus_class"]) for p in pois)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    if not ranked:
        return "0 punti di interesse nel contesto della zona."
    parti = ", ".join(f"{label} ({n})" for label, n in ranked)
    return f"{len(pois)} punti di interesse nella zona; classi prevalenti: {parti}."
