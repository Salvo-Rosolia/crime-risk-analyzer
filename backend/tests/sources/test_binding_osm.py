"""OSM binding, labels and POI catalog read from the active set (#413).

With the default set everything stays identical to the constants; with a custom
set the same functions read the set's binding and labels, and two different
sets do not mix (caches included).
"""

from __future__ import annotations

import dataclasses
import gc
import urllib.parse
import weakref
from typing import cast

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rdflib import Graph

from crime_risk_analyzer import main as main_module
from crime_risk_analyzer import poi_types as poi_types_module
from crime_risk_analyzer.errors import register_exception_handlers
from crime_risk_analyzer.i18n import terminus_labels
from crime_risk_analyzer.i18n.terminus_labels import (
    controlled_vocab_for,
    label_en,
    label_it,
)
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.overpass_client import (
    DEFAULT_OVERPASS_URL,
    _extract_osm_tag,  # pyright: ignore[reportPrivateUsage]
    _parse_elements,  # pyright: ignore[reportPrivateUsage]
    fetch_pois,
)
from crime_risk_analyzer.poi_types import (
    PoiType,
    UnknownPoiTypeError,
    poi_types,
    resolve_poi_type,
)
from crime_risk_analyzer.sources import routes
from crime_risk_analyzer.sources.build import build_source_set
from crime_risk_analyzer.sources.context import (
    DEFAULT_ID,
    bind,
    current_labels,
    current_osm,
    default_set,
)
from crime_risk_analyzer.sources.model import OsmBinding, SourceSet
from crime_risk_analyzer.sources.parsing import ParsedSources
from crime_risk_analyzer.sources.report import SourceValidationError
from crime_risk_analyzer.sources.session import SessionStore
from crime_risk_analyzer.sources.vocabulary import TERMINUS_VOCABULARY
from crime_risk_analyzer.sparql_module.osm_mapping import (
    FAMILY_ORDER,
    OSM_SELECTORS,
    OSM_TO_TERMINUS,
    YIELDING_SELECTORS,
)

SID = "test-session-AAAAAA-0123456789ab"
OTHER_SID = "other-session-BBBBBB-0123456789ab"
#: Classes of the set built by ``_custom()``.
CUSTOM_CLASSES = {"Banca", "Gas_station", "Monumento", "Rovina"}


def _custom(id_: str = "c1", **fields: object) -> SourceSet:
    osm = OsmBinding(
        osm_to_class={
            "amenity=bank": "Banca",
            "shop=kiosk": "Gas_station",
            "tourism=attraction": "Monumento",
            "historic=ruins": "Rovina",
        },
        family_order=("shop", "amenity", "tourism", "historic"),
        yielding_selectors={"tourism=attraction": "historic"},
    )
    labels = {
        "Banca": ("Istituto di credito", "Bank"),
        "Monumento": ("Monumento", "Monument"),
        "Rovina": ("", "Ruin"),
    }
    base = dataclasses.replace(
        default_set(), id=id_, kind="custom", osm=osm, labels=labels
    )
    return dataclasses.replace(base, **fields)  # pyright: ignore[reportArgumentType]


def _bank2_set() -> SourceSet:
    """Custom set with a single class, disjoint from ``_custom()``."""
    return _custom(
        "c2",
        osm=OsmBinding(
            osm_to_class={"amenity=bank": "Bank2"},
            family_order=("amenity",),
            yielding_selectors={},
        ),
        labels={"Bank2": ("Banca due", "Bank two")},
    )


def _parsed_with(labels: dict[str, tuple[str, str]]) -> ParsedSources:
    """Already-read sources with one class per label (minimal binding)."""
    return ParsedSources(
        graph=Graph(),
        vocabulary=TERMINUS_VOCABULARY,
        classes=frozenset(labels),
        labels=labels,
        osm_to_class={f"amenity=t{i}": c for i, c in enumerate(labels)},
        family_order=("amenity",),
        istat=None,  # pyright: ignore[reportArgumentType]
        mappatura={},
        voci_rottura=frozenset(),
        versione="v",
    )


# --- identical default ---


def test_default_binding_matches_the_constants() -> None:
    osm = current_osm()
    assert dict(osm.osm_to_class) == OSM_TO_TERMINUS
    assert osm.family_order == FAMILY_ORDER
    assert dict(osm.yielding_selectors) == YIELDING_SELECTORS
    assert osm.selectors == OSM_SELECTORS
    assert current_labels() is None


def test_default_labels_from_the_json() -> None:
    # Literal values of the TERMINUS JSON, not a comparison of the code with itself.
    assert label_it("Bank") == "Banca"
    assert label_en("Bank") == "Bank"
    # class absent from the JSON: fallback to the normalized name (IT and EN equal)
    assert label_it("Boh_sconosciuto") == "Boh sconosciuto"
    assert label_en("Boh_sconosciuto") == "Boh sconosciuto"
    # custom set without own labels: same answers as the default
    with bind(dataclasses.replace(default_set(), id="x", labels=None)):
        assert label_it("Bank") == "Banca"
        assert label_en("Bank") == "Bank"


def test_default_empty_it_label_falls_back_to_en(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = {
        "identifier": "Xyz",
        "label_en": "Xyz en",
        "label_it": "",
        "category": "",
    }
    monkeypatch.setattr(terminus_labels, "_records", lambda: {"Xyz": record})
    assert label_it("Xyz") == "Xyz en"


def test_default_tag_extraction_unchanged() -> None:
    tags = {"tourism": "attraction", "historic": "archaeological_site"}
    assert _extract_osm_tag(tags) == "historic=archaeological_site"


# --- OSM binding of the set ---


def test_tag_extraction_uses_order_and_yielding_selectors_of_the_set() -> None:
    tags = {"amenity": "bank", "shop": "kiosk"}
    assert _extract_osm_tag(tags) == "amenity=bank"  # default: amenity first
    with bind(_custom()):
        assert _extract_osm_tag(tags) == "shop=kiosk"  # set order: shop first
        yielding = {"tourism": "attraction", "historic": "ruins"}
        assert _extract_osm_tag(yielding) == "historic=ruins"


def test_tag_not_in_the_set_binding_is_not_extracted() -> None:
    with bind(_custom()):
        assert _extract_osm_tag({"amenity": "hospital"}) == ""


def test_poi_class_from_the_set_binding() -> None:
    payload = {
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 41.9,
                "lon": 12.5,
                "tags": {"amenity": "bank", "name": "B"},
            }
        ]
    }
    with bind(_custom()):
        pois = _parse_elements(payload, "Roma")
    assert [p["ontology_class"] for p in pois] == ["Banca"]
    assert [p["ontology_class"] for p in _parse_elements(payload, "Roma")] == ["Bank"]


# --- labels ---


def test_labels_from_the_set() -> None:
    with bind(_custom()):
        assert label_it("Banca") == "Istituto di credito"
        assert label_en("Banca") == "Bank"
        assert current_labels() is not None


def test_empty_it_label_falls_back_to_en() -> None:
    with bind(_custom()):
        assert label_it("Rovina") == "Ruin"


def test_class_without_label_shows_the_name_with_spaces() -> None:
    with bind(_custom()):
        assert label_it("Gas_station") == "Gas station"
        assert label_en("Gas_station") == "Gas station"
        assert label_it("Bank") == "Bank"  # not in the set: no TERMINUS JSON


def test_controlled_vocabulary_follows_the_set() -> None:
    with bind(_custom()):
        assert controlled_vocab_for(["Banca", "Gas_station"]) == [
            "Istituto di credito",
            "Gas station",
        ]


def test_custom_set_with_labels_none_uses_the_json() -> None:
    with bind(_custom(labels=None)):
        assert label_it("Bank") == "Banca"


# --- /poi-types catalog ---


def test_catalog_of_the_custom_set() -> None:
    with bind(_custom()):
        types = poi_types()
    assert {t.ontology_class for t in types} == CUSTOM_CLASSES
    assert PoiType(ontology_class="Banca", label_it="Istituto di credito") in types
    labels_cf = [t.label_it.casefold() for t in types]
    assert labels_cf == sorted(labels_cf)


def test_catalog_of_different_sets_does_not_mix() -> None:
    other = _bank2_set()
    default_before = poi_types()
    with bind(_custom("c1")):
        a = poi_types()
        assert resolve_poi_type("istituto di credito") == "Banca"
    with bind(other):
        b = poi_types()
        with pytest.raises(UnknownPoiTypeError):
            resolve_poi_type("istituto di credito")
        assert resolve_poi_type("banca due") == "Bank2"
    assert {t.ontology_class for t in b} == {"Bank2"}
    assert a != b
    assert poi_types() == default_before
    assert resolve_poi_type("stazione ferroviaria") == "Railway_station"
    with bind(_custom("c1")):
        with pytest.raises(UnknownPoiTypeError):
            resolve_poi_type("stazione ferroviaria")


def test_custom_catalog_is_not_served_from_the_default_cache() -> None:
    # A custom set is never served from the default cache, even if the cache
    # is already full.
    poi_types()
    with bind(_custom("default-lookalike")):
        assert {t.ontology_class for t in poi_types()} != set(OSM_TO_TERMINUS.values())


def test_catalog_of_a_set_is_computed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def counting_label_it(cls: str) -> str:
        calls.append(cls)
        return label_it(cls)

    monkeypatch.setattr(poi_types_module, "label_it", counting_label_it)
    first, second = _custom("once-1"), _custom("once-2")
    with bind(first):
        a = poi_types()
        assert poi_types() is a
        assert len(calls) == 4  # one label per class, not per call
    with bind(second):
        # another set: its own catalogue, computed once more
        assert poi_types() == a
        assert len(calls) == 8
    with bind(first):
        assert poi_types() is a
    assert len(calls) == 8


def test_catalog_cache_does_not_keep_the_set_alive() -> None:
    source_set = _custom("weak")
    ref = weakref.ref(source_set)
    with bind(source_set):
        poi_types()
    del source_set
    gc.collect()
    assert ref() is None


def _client(store: SessionStore) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(main_module.router)
    app.dependency_overrides[routes.get_sessions] = lambda: store
    return TestClient(app)


def _get_poi_types(client: TestClient, sid: str | None = None) -> httpx.Response:
    headers = {"X-Session-Id": sid} if sid is not None else {}
    return cast(httpx.Response, client.get("/poi-types", headers=headers))  # pyright: ignore[reportUnknownMemberType]


def _classes(response: httpx.Response) -> set[str]:
    return {t["ontology_class"] for t in response.json()}


def test_poi_types_endpoint_serves_the_catalog_of_the_session_set() -> None:
    """#463: with a custom set active the list is the set's, not the default."""
    store = SessionStore(ttl_seconds=100, max_sessions=4)
    store.activate(SID, _custom(), [])
    client = _client(store)

    with_session = _get_poi_types(client, SID)
    default = _get_poi_types(client)

    assert with_session.status_code == 200
    assert _classes(with_session) == CUSTOM_CLASSES
    assert _classes(default) == set(OSM_TO_TERMINUS.values())


def test_poi_types_endpoint_session_without_set_serves_the_default() -> None:
    store = SessionStore(ttl_seconds=100, max_sessions=4)
    store.activate(SID, _custom(), [])
    client = _client(store)

    r = _get_poi_types(client, OTHER_SID)

    assert r.status_code == 200
    assert r.json() == _get_poi_types(client).json()
    assert _classes(r) == set(OSM_TO_TERMINUS.values())


def test_poi_types_endpoint_sessions_with_different_sets_do_not_mix() -> None:
    other = _bank2_set()
    store = SessionStore(ttl_seconds=100, max_sessions=4)
    store.activate(SID, _custom("c1"), [])
    store.activate(OTHER_SID, other, [])
    client = _client(store)

    assert _classes(_get_poi_types(client, SID)) == CUSTOM_CLASSES
    assert _classes(_get_poi_types(client, OTHER_SID)) == {"Bank2"}
    assert _classes(_get_poi_types(client, SID)) == CUSTOM_CLASSES


def test_poi_types_endpoint_does_not_renew_the_session_ttl() -> None:
    """Listing is not a use of the set: it must not keep the session alive."""
    t = [0.0]
    store = SessionStore(ttl_seconds=100, max_sessions=4, clock=lambda: t[0])
    store.activate(SID, _custom(), [])
    client = _client(store)
    t[0] = 60.0

    assert _get_poi_types(client, SID).status_code == 200

    assert store.remaining_seconds(SID) == 40


def test_poi_types_endpoint_with_expired_or_malformed_session_200() -> None:
    """#438: no 410 (nor 422 for a malformed header): it serves the default.

    Still holds after #463: an expired set is not resurrected nor reported.
    """
    t = [0.0]
    store = SessionStore(ttl_seconds=100, max_sessions=4, clock=lambda: t[0])
    store.activate(SID, _custom(), [])
    client = _client(store)
    t[0] = 101.0

    expected = _get_poi_types(client).json()
    for header in (SID, "x"):
        r = _get_poi_types(client, header)
        assert r.status_code == 200
        assert r.json() == expected


def _set_ids(response: httpx.Response) -> set[str]:
    return {t["source_set_id"] for t in response.json()}


def test_poi_types_endpoint_exposes_the_id_of_the_session_set() -> None:
    """#473: every entry carries the id of the set the catalogue belongs to."""
    store = SessionStore(ttl_seconds=100, max_sessions=4)
    store.activate(SID, _custom("c1"), [])
    store.activate(OTHER_SID, _bank2_set(), [])
    client = _client(store)

    assert _set_ids(_get_poi_types(client, SID)) == {"c1"}
    assert _set_ids(_get_poi_types(client, OTHER_SID)) == {"c2"}
    assert _set_ids(_get_poi_types(client)) == {"default"}


def test_poi_types_endpoint_id_is_stable_and_default_after_expiry() -> None:
    t = [0.0]
    store = SessionStore(ttl_seconds=100, max_sessions=4, clock=lambda: t[0])
    store.activate(SID, _custom("c1"), [])
    client = _client(store)

    assert _set_ids(_get_poi_types(client, SID)) == {"c1"}
    assert _set_ids(_get_poi_types(client, SID)) == {"c1"}
    t[0] = 101.0
    assert _set_ids(_get_poi_types(client, SID)) == {"default"}


# --- Overpass: selectors of the set ---


@respx.mock
async def test_fetch_pois_without_selectors_uses_those_of_the_active_set() -> None:
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": []})
    )
    with bind(_custom()):
        await fetch_pois(Bbox(41.88, 12.48, 41.90, 12.50), "Roma")
    query = urllib.parse.unquote_plus(route.calls.last.request.content.decode())
    for selector in ("amenity=bank", "shop=kiosk", "historic=ruins"):
        key, _, value = selector.partition("=")
        assert f'["{key}"="{value}"]' in query
    assert '"hospital"' not in query  # default selector, not the set one


# --- alias ambiguity: rejected when building the set ---


def test_ambiguous_set_aliases_are_a_validation_error() -> None:
    parsed = _parsed_with(
        {
            "Alfa": ("Comune", "Alpha"),
            "Beta": ("comune", "Beta en"),
            "Gamma": ("Alfa", ""),
        }
    )
    with pytest.raises(SourceValidationError) as exc:
        build_source_set(parsed)
    errors = exc.value.report.errors
    assert {p.code for p in errors} == {"alias_tipo_poi_ambiguo"}
    messages = " ".join(p.message for p in errors)
    for cls in ("Alfa", "Beta", "Gamma"):
        assert cls in messages


def test_unambiguous_set_aliases_build() -> None:
    ss = build_source_set(
        _parsed_with({"Alfa": ("Alfa", "A"), "Beta": ("Beta due", "B")})
    )
    assert ss.id != DEFAULT_ID
    assert ss.kind == "custom"
