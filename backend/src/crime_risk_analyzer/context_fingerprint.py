"""Fingerprint of the zone context (#242).

``/analyze/poi`` must be able to prove that a POI narrative arises on the
context the user has in front of them, not on a different rebuilt one: OSM is a
live source and the ``MAX_POIS`` cap can let points in or out between two
captures. The fingerprint gives a comparable identity to a list of POIs, so the
endpoint can refuse (409) instead of generating prose on a neighbourhood that is
not on screen.

With the ISTAT switch on (#354) the fingerprint also covers the version of the
ISTAT data feeding the prompt: a data update between phase 1 and the click is a
context as different as a change of POIs, and gives the same 409. The version is
passed by the caller (:func:`istat_version_for`), so computation and comparison
read it from the same source.

It is not a measure of anything: it is an opaque identity digest (no scoring,
_project.md §Vincoli). :func:`fingerprint` is PURE: no I/O, no state.

:data:`ContextHash` also lives here, the type with which requests ACCEPT a
fingerprint: its shape is a property of the digest produced by
:func:`fingerprint`, not of the routes that receive it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated

from pydantic import Field

from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.sources.context import (
    DEFAULT_ID,
    current_id,
    istat_data_version,
)

__all__ = ["ContextHash", "fingerprint", "active_sources_id", "istat_version_for"]

#: Exact length of a fingerprint: the sha256 hexdigest that :func:`fingerprint`
#: returns (32 bytes, two characters per byte). Anchored to the real digest by
#: ``test_la_richiesta_accetta_esattamente_la_lunghezza_del_digest``, so an
#: algorithm change cannot leave the requests' bound behind.
_FINGERPRINT_LENGTH = 64

#: Type of the ``contesto_hash`` field in the bodies that send a fingerprint back
#: to the server (``POST /analyze/narrativa`` and ``POST /analyze/poi``). A shared
#: alias and not two twin ``Field``s: the constraint and its rationale are the
#: same for both routes, and as two copies they could diverge — one correct and
#: the other rejecting valid fingerprints (or, worse, accepting malformed ones).
ContextHash = Annotated[
    str,
    Field(
        min_length=_FINGERPRINT_LENGTH,
        max_length=_FINGERPRINT_LENGTH,
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


def fingerprint(
    pois: list[Poi],
    *,
    istat_version: str | None = None,
    sources_id: str | None = None,
) -> str:
    """sha256 hexdigest of the POI list of the zone context.

    Only the fields that feed the POI prompt enter the digest: ``id``,
    ``name``, ``terminus_class`` (zone composition and IT labels) and
    ``lat``/``lon`` (neighbour distances). ``osm_tags`` and ``citta`` stay out,
    as they do not feed it: a re-tag on OSM must not invalidate a still valid
    narrative.

    ORDER-SENSITIVE by choice: the fingerprint identifies the list *shown* to
    the user — numbered on the map and in the POI list — not just the set. A
    reordering with unchanged content therefore produces a 409: a rare false
    positive, in the cautious direction (refuse rather than diverge).

    Serialisation via ``json.dumps`` and not via a join with a separator: an OSM
    name can contain any character, and JSON escaping makes the serialisation
    unambiguous by construction rather than by assumption about the names. The
    digest is computed server-side only (``/analyze`` and ``/analyze/poi``): the
    client sends it back opaque and does not recompute it, so the float
    formatting need not agree between Python and TypeScript.

    ``istat_version`` (#354): version of the ISTAT data in the prompt, ``None``
    with the switch off (or without data). With ``None`` the serialisation is the
    same POI list as before, so the digest is byte-identical to the pre-#354 one.
    With a version (even an empty one) the canonical text is a JSON object
    ``{"istat_versione": ..., "pois": [...]}``: an object never coincides with a
    list, so the two forms cannot collide by construction.

    ``sources_id`` (#416): id of the user-uploaded source set, ``None`` with the
    default set (digest unchanged). With an id the canonical object also carries
    ``"fonti"``: two sessions with different sources never share a fingerprint,
    so phase 2 of one cannot accept that of the other.
    """
    rows = [
        [poi["id"], poi["name"], poi["terminus_class"], poi["lat"], poi["lon"]]
        for poi in pois
    ]
    payload: object
    if istat_version is None and sources_id is None:
        payload = rows
    else:
        obj: dict[str, object] = {}
        if istat_version is not None:
            obj["istat_versione"] = istat_version
        obj["pois"] = rows
        if sources_id is not None:
            obj["fonti"] = sources_id
        payload = obj
    canonical = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def istat_version_for(istat_context_enabled: bool) -> str | None:
    """ISTAT data version to put in the fingerprint (#354).

    Single source for all the places that COMPUTE or COMPARE a fingerprint:
    switch off -> ``None`` (fingerprint unchanged); on -> the version of the data
    in use (``None`` if the data is not available, like the prompt, which in that
    case carries no ISTAT block). It reads the data cache: not pure like
    :func:`fingerprint`, which is why it is a separate function.
    """
    return istat_data_version() if istat_context_enabled else None


def active_sources_id() -> str | None:
    """Source-set id to put in the fingerprint (#416).

    ``None`` with the default set, so the fingerprint stays as before. Like
    :func:`istat_version_for`, it is the single source for computation and
    comparison.
    """
    active = current_id()
    return None if active == DEFAULT_ID else active
