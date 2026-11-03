"""Fingerprint of the zone context (#242): determinism and sensitivity."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from crime_risk_analyzer.analyze_narrative import ZoneNarrativeRequest
from crime_risk_analyzer.context_fingerprint import fingerprint
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.poi_narrative import PoiNarrativeRequest


def _poi(
    poi_id: str = "node/1",
    name: str = "Banca A",
    ontology_class: str = "Bank",
    lat: float = 41.8900,
    lon: float = 12.4920,
) -> Poi:
    return {
        "id": poi_id,
        "name": name,
        "lat": lat,
        "lon": lon,
        "osm_tags": "amenity=bank",
        "ontology_class": ontology_class,
        "citta": "Roma",
    }


def test_same_list_same_digest() -> None:
    """Determinism: two runs on the same list must coincide, otherwise the comparison
    in /analyze/poi would reject identical contexts."""
    pois = [_poi(), _poi("node/2", "Liceo Cavour", "School")]
    assert fingerprint(pois) == fingerprint(list(pois))


def test_digest_is_a_sha256_hexdigest() -> None:
    assert len(fingerprint([_poi()])) == 64
    assert all(c in "0123456789abcdef" for c in fingerprint([_poi()]))


def test_added_poi_changes_the_digest() -> None:
    assert fingerprint([_poi()]) != fingerprint([_poi(), _poi("node/2", "Bar")])


def test_removed_poi_changes_the_digest() -> None:
    two = [_poi(), _poi("node/2", "Bar")]
    assert fingerprint(two) != fingerprint([_poi()])


def test_different_name_changes_the_digest() -> None:
    """The POI name enters the prompt (neighborhood and selected point)."""
    assert fingerprint([_poi()]) != fingerprint([_poi(name="Banca B")])


def test_different_class_changes_the_digest() -> None:
    """The TERMINUS class drives the zone composition and the IT labels."""
    assert fingerprint([_poi()]) != fingerprint([_poi(ontology_class="School")])


def test_different_coordinate_changes_the_digest() -> None:
    """The coordinates determine the distances of the neighbors in the prompt."""
    assert fingerprint([_poi()]) != fingerprint([_poi(lat=41.8901)])


def test_different_order_changes_the_digest() -> None:
    """Order-sensitive by choice (spec #242): the fingerprint identifies the SHOWN
    list, which in the UI is numbered, not just the set."""
    a, b = _poi(), _poi("node/2", "Bar")
    assert fingerprint([a, b]) != fingerprint([b, a])


def test_empty_list_has_a_stable_digest() -> None:
    """Zone without POIs: the fingerprint exists and is comparable (no special case)."""
    assert fingerprint([]) == fingerprint([])
    assert fingerprint([]) != fingerprint([_poi()])


def test_fields_outside_the_fingerprint_do_not_change_the_digest() -> None:
    """``osm_tags`` and ``citta`` do not enter the POI prompt: outside the
    fingerprint, so that an OSM retag does not invalidate a still valid narrativa."""
    base = _poi()
    variant: Poi = {**base, "osm_tags": "amenity=bank;atm=yes", "citta": "ROMA"}
    assert fingerprint([base]) == fingerprint([variant])


# --- The type of the fingerprint in the request bodies (``contesto_hash``) ---
# The bound of the field is a property of the digest produced HERE, not of the
# two routes that receive it: ``ZoneNarrativeRequest`` and ``PoiNarrativeRequest``
# each declared their own ``Field(min_length=64, max_length=64)`` with the same
# rationale copied by hand, and an algorithm change could have fixed one leaving
# the other to reject valid fingerprints.

#: The requests that carry a ``contesto_hash``, with the rest of the body minimal
#: valid: the (model, fields) pair serves to prove the SAME bound on both.
_REQUESTS_WITH_FINGERPRINT = [
    pytest.param(
        ZoneNarrativeRequest, {"citta": "Roma", "zona": "Colosseo"}, id="zona"
    ),
    pytest.param(
        PoiNarrativeRequest,
        {"citta": "Roma", "zona": "Colosseo", "poi_id": "node/1"},
        id="poi",
    ),
]


@pytest.mark.parametrize(("model_cls", "rest"), _REQUESTS_WITH_FINGERPRINT)
def test_la_richiesta_accetta_esattamente_la_lunghezza_del_digest(
    model_cls: type[BaseModel], rest: dict[str, str]
) -> None:
    """Both routes bind the fingerprint to the REAL length of the digest.

    One character less or more does not have the shape of a fingerprint: it falls
    in validation (422 before any I/O) and not at the comparison (409, which on a
    cold cache costs a rebuild of the context). The valid one is computed with
    :func:`fingerprint`, not written by hand: if the digest changed length, the
    bound of the two models must follow it.
    """
    valid = fingerprint([_poi()])

    model_cls.model_validate({**rest, "contesto_hash": valid})

    for malformed in (valid[:-1], valid + "0"):
        with pytest.raises(ValidationError):
            model_cls.model_validate({**rest, "contesto_hash": malformed})


def test_the_two_requests_describe_the_fingerprint_the_same_way() -> None:
    """One field, one prose: bound and description come from the shared alias of this
    module, not copied in two models. The description ends up in the OpenAPI, so
    two copies diverge toward the client as well."""
    zona = ZoneNarrativeRequest.model_fields["contesto_hash"]
    poi = PoiNarrativeRequest.model_fields["contesto_hash"]

    assert zona.description is not None
    assert zona.description == poi.description
    assert zona.metadata == poi.metadata


# --- ISTAT data version in the fingerprint (#354) ---
# With the ISTAT switch on the prompt depends on the ISTAT data too: a data
# update between phase 1 and the click must give 409 like a change of the POIs.
# Off, the fingerprint stays the previous one, byte for byte.

#: List with a named POI and an anonymous one, and its digest computed on main
#: (35acc46) BEFORE #354: the serialization without version must not change.
_PINNED_POIS: list[Poi] = [
    _poi(),
    _poi("way/2", "", "School", 41.8905, 12.4931),
]
_MAIN_DIGEST = "15d9ca577fa82f386a3e2192991e326e017f61eba9c0c734dda0e6aa4f4d08c2"


def test_senza_versione_istat_il_digest_e_quello_di_prima() -> None:
    assert fingerprint(_PINNED_POIS) == _MAIN_DIGEST
    assert fingerprint(_PINNED_POIS, istat_version=None) == _MAIN_DIGEST


def test_the_istat_version_changes_the_digest() -> None:
    with_istat = fingerprint(_PINNED_POIS, istat_version="2024@2026-10-06")
    assert with_istat != _MAIN_DIGEST
    assert len(with_istat) == 64


def test_different_istat_versions_give_different_digests() -> None:
    a = fingerprint(_PINNED_POIS, istat_version="2024@2026-10-06")
    b = fingerprint(_PINNED_POIS, istat_version="2024@2026-10-08")
    assert a != b
    assert a == fingerprint(list(_PINNED_POIS), istat_version="2024@2026-10-06")


def test_empty_version_is_not_confused_with_absence() -> None:
    """Unambiguous serialization: even the empty string is a version."""
    assert fingerprint(_PINNED_POIS, istat_version="") != _MAIN_DIGEST


def test_the_version_is_not_confused_with_a_poi() -> None:
    """The version is not an element at the end of the list: a list of POIs cannot
    produce the same canonical text as list + version."""
    assert fingerprint([], istat_version="x") != fingerprint([])
