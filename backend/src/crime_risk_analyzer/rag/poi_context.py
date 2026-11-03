"""Spatial context of the selected POI (#197).

PURE functions: no I/O, no LLM, no state. They serve to make the per-POI
narrative different between POIs of the same class: the risks derive only
from the TERMINUS class, so without context every bank would receive the same
text. The context is the spatial neighbourhood plus the composition of the zone.

Every output has a declared TOTAL ordering: two runs on the same
context must produce the same prompt, otherwise ``repro.prompt_hash``
diverges and the run is not reconstructible.
"""

from __future__ import annotations

from collections import Counter
from typing import TypedDict

from crime_risk_analyzer.i18n.terminus_labels import label_it
from crime_risk_analyzer.models.geo import haversine_m
from crime_risk_analyzer.overpass_client import Poi

__all__ = [
    "NeighbourPoi",
    "haversine_m",
    "nearest_neighbours",
    "zone_composition",
]


class NeighbourPoi(TypedDict):
    """A neighbouring POI, as it enters the prompt (name, class in IT, distance)."""

    name: str
    label_it: str
    distance_m: int


def nearest_neighbours(
    pois: list[Poi], poi_id: str, *, k: int = 5
) -> list[NeighbourPoi]:
    """The ``k`` POIs closest to ``poi_id``, excluding itself.

    Total ordering: increasing distance, at equal distance increasing ``id``.
    Raises :class:`KeyError` if ``poi_id`` is not in the list: the
    caller (endpoint) translates it into 404, not into an empty list that
    would produce a narrative without context without saying so.
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
            label_it=label_it(p["ontology_class"]),
            distance_m=round(distance),
        )
        for distance, _, p in scored[:k]
    ]


def zone_composition(pois: list[Poi], *, top: int = 3) -> str:
    """Summary line of the SAMPLE of POIs: how many there are and the most frequent
    classes.

    The line enters the prompt, so the text declares that it speaks of a selection and
    not of the zone (#254): the POIs are the closest to the centre of the area with a
    cap per TERMINUS class, so the total is not the total of the zone and "prevailing
    classes" would be an artefact of the cap, which flattens the counts to a
    plateau. Asserting a fact about the zone starting from the sample is exactly the
    kind of unanchored assertion that the project does not want in the context.

    Total ordering: decreasing count, at equal count label in
    alphabetical order.
    """
    counts = Counter(label_it(p["ontology_class"]) for p in pois)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    if not ranked:
        return "0 punti di interesse selezionati nel contesto della zona."
    parts = ", ".join(f"{label} ({n})" for label, n in ranked)
    return (
        f"{len(pois)} punti di interesse selezionati fra i piu' vicini al centro "
        f"della zona; classi piu' frequenti fra questi: {parts}."
    )
