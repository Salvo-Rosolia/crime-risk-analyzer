"""Tests for the Overpass client -> on-demand POIs (#16). HTTP responses are mocked."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

import httpx
import pytest
import respx

from crime_risk_analyzer import overpass_client
from crime_risk_analyzer.eval.snapshots import capturing_source
from crime_risk_analyzer.models.geo import Bbox, haversine_m
from crime_risk_analyzer.overpass_client import (
    DEFAULT_OVERPASS_URL,
    INTERACTIVE_RETRY,
    MAX_POIS,
    OFFLINE_RETRY,
    PER_SELECTOR_CAP,
    OsmCut,
    OverpassError,
    Poi,
    fetch_pois,
    fetch_pois_with_cut,
    remark_signals_incomplete_response,
)
from crime_risk_analyzer.sparql_module.osm_mapping import map_to_terminus

_FIXTURE = Path(__file__).parent / "fixtures" / "overpass_sample.json"
_BBOX = Bbox(41.88, 12.48, 41.90, 12.50)


def _sample() -> dict[str, object]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _no_retry_pause(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    """Zeroes the pauses of the interactive policy: no real sleep (#232).

    ``fetch_pois`` resolves the default policy AT CALL TIME
    (``retry or INTERACTIVE_RETRY``), not as a signature default: that is why
    replacing the module attribute here is enough to make the suite instantaneous.
    """
    monkeypatch.setattr(
        overpass_client,
        "INTERACTIVE_RETRY",
        replace(overpass_client.INTERACTIVE_RETRY, pause_s=(0.0,)),
    )


def _poi_at(poi_id: str, lat: float, lon: float, terminus_class: str = "Bank") -> Poi:
    """Synthetic POI placed by hand (for the selection tests, #254)."""
    return Poi(
        id=poi_id,
        name=f"POI {poi_id}",
        lat=lat,
        lon=lon,
        osm_tags="amenity=bank",
        terminus_class=terminus_class,
        citta="Roma",
    )


# --- #254: which POIs enter the MAX_POIS slots ---


def test_select_pois_prefers_the_nearest_to_the_center() -> None:
    """The slots go to the POIs closest to the centre of the area, not first comers.

    Before #254 the cut took the first ``MAX_POIS`` in the order in which Overpass
    emitted them, i.e. in the order of the declared selectors: the POIs of the tag
    families at the tail never made it into a dense zone.
    """
    center_lat, center_lon = _BBOX.center()
    far = _poi_at("far", center_lat + 0.02, center_lon)
    near = _poi_at("near", center_lat + 0.0001, center_lon)

    selected = overpass_client.select_pois([far, near], _BBOX.center(), max_pois=1)

    assert [p["id"] for p in selected] == ["near"]


def test_select_pois_caps_a_dense_class_while_other_classes_are_present() -> None:
    """A dense class does not take all the slots if there are other classes.

    In a city centre the closest POIs are often of the same class (eight ATMs within
    150 m): without a cap the zone would be described on a homogeneous sample, i.e.
    the distortion that #254 closes, only with another cause.
    """
    lat, lon = _BBOX.center()
    banks = [_poi_at(f"bank-{i}", lat + 0.0001 * i, lon, "Bank") for i in range(5)]
    others = [
        _poi_at("school", lat + 0.001, lon, "School"),
        _poi_at("museum", lat + 0.0011, lon, "Museum"),
    ]

    selected = overpass_client.select_pois(
        banks + others, (lat, lon), max_pois=5, per_class_cap=3
    )

    per_class = Counter(p["terminus_class"] for p in selected)
    assert per_class == Counter({"Bank": 3, "School": 1, "Museum": 1})


def test_select_pois_fills_remaining_slots_when_only_capped_classes_are_left() -> None:
    """The cap must not make the function return FEWER POIs than the zone has.

    In a zone of only banks a rigid cap would return 3 points instead of
    ``max_pois``: worse than before. Once the candidates of other classes are
    exhausted, the remaining slots are filled with the closest among the discarded,
    keeping the distance order.
    """
    lat, lon = _BBOX.center()
    banks = [_poi_at(f"bank-{i}", lat + 0.0001 * i, lon, "Bank") for i in range(6)]

    selected = overpass_client.select_pois(
        banks, (lat, lon), max_pois=5, per_class_cap=3
    )

    assert [p["id"] for p in selected] == [
        "bank-0",
        "bank-1",
        "bank-2",
        "bank-3",
        "bank-4",
    ]


def test_select_pois_always_comes_out_in_distance_order() -> None:
    """Even the POIs readmitted by the second round sit in their place by distance.

    It is not cosmetic: the context fingerprint (#242) is SENSITIVE to the order — a
    reordering with unchanged content makes ``/analyze/poi`` answer 409 — and the
    numbering of the markers on the map follows this list. Without the final
    reordering the output would be ``bank-0, bank-1, bank-2, school, bank-3``.
    """
    lat, lon = _BBOX.center()
    banks = [_poi_at(f"bank-{i}", lat + 0.0001 * i, lon, "Bank") for i in range(4)]
    school = _poi_at("school", lat + 0.005, lon, "School")

    selected = overpass_client.select_pois(
        [*banks, school], (lat, lon), max_pois=5, per_class_cap=3
    )

    assert [p["id"] for p in selected] == [
        "bank-0",
        "bank-1",
        "bank-2",
        "bank-3",
        "school",
    ]


def test_select_pois_breaks_distance_ties_by_id() -> None:
    """At equal distance the lower ``id`` wins.

    Without a tie-breaking criterion two runs on the same input can produce
    different prompts and ``repro.prompt_hash`` diverges, making the run
    non-reconstructible.
    """
    lat, lon = _BBOX.center()
    selected = overpass_client.select_pois(
        [_poi_at("b", lat + 0.001, lon), _poi_at("a", lat + 0.001, lon)],
        (lat, lon),
        max_pois=1,
    )

    assert [p["id"] for p in selected] == ["a"]


@respx.mock
async def test_fetch_pois_deduplicates_elements_emitted_by_several_blocks() -> None:
    """The same OSM object emitted by several ``out`` blocks enters only once.

    The query has one block per selector and each ``out`` prints ITS OWN set:
    verified live on the Colosseo bbox, where the Arco di Costantino
    (``tourism=attraction`` + ``historic=monument``) and the Basilica di San Pietro in
    Vincoli (``amenity=place_of_worship`` + ``tourism=attraction``) arrive twice.
    As long as the cut was «the first 20 emitted» the blocks duplicating them never
    made it into the output; with the selection by proximity the duplicates are the
    closest, so they would eat the slots of exactly the classes that #254 wants to
    bring out, and ``zone_composition`` would count three places of worship where
    there is one.
    """
    lat, lon = _BBOX.center()
    arch: dict[str, object] = {
        "type": "way",
        "id": 23590989,
        "center": {"lat": lat, "lon": lon},
        "tags": {
            "tourism": "attraction",
            "historic": "monument",
            "name": "Arco di Costantino",
        },
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": [arch, dict(arch)]})
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert [p["id"] for p in pois] == ["way/23590989"]


@respx.mock
async def test_fetch_pois_node_and_way_with_same_number_do_not_collide() -> None:
    """A node and a way with the same OSM number do not share the same id (#265).

    node and way live in separate OSM namespaces: without the element type in the
    POI id, the risks would be attributed (since #255) to the wrong point every time
    the two numbers match.
    """
    lat, lon = _BBOX.center()
    node_elem: dict[str, object] = {
        "type": "node",
        "id": 123,
        "lat": lat,
        "lon": lon,
        "tags": {"amenity": "bank", "name": "Banca (node)"},
    }
    way_elem: dict[str, object] = {
        "type": "way",
        "id": 123,
        "center": {"lat": lat, "lon": lon},
        "tags": {"tourism": "museum", "name": "Museo (way)"},
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": [node_elem, way_elem]})
    )

    pois = await fetch_pois(_BBOX, "Roma")

    ids = {p["id"] for p in pois}
    assert ids == {"node/123", "way/123"}
    assert len(pois) == 2


@respx.mock
async def test_fetch_pois_keeps_the_nearest_even_if_emitted_last() -> None:
    """The POI closest to the centre enters even if Overpass emits it last.

    It is the defect of #254 taken from the real entry point: the emission order is
    that of the declared selectors, so before a POI beyond the twentieth slot never
    made it in, however close it was.
    """
    lat, lon = _BBOX.center()
    elements: list[dict[str, object]] = [
        {
            "type": "node",
            "id": 1000 + i,
            "lat": lat + 0.01,
            "lon": lon,
            "tags": {"amenity": "bank", "name": f"Lontana {i}"},
        }
        for i in range(MAX_POIS)
    ]
    elements.append(
        {
            "type": "node",
            "id": 9999,
            "lat": lat,
            "lon": lon,
            "tags": {"tourism": "museum", "name": "Museo sul centro"},
        }
    )
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": elements})
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert len(pois) == MAX_POIS
    assert pois[0]["id"] == "node/9999"
    assert "Museum" in {p["terminus_class"] for p in pois}


@respx.mock
async def test_fetch_pois_maps_contract_fields() -> None:
    """POI in the retrieval contract: id/name/lat/lon/osm_tags/terminus_class/citta."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_sample())
    )

    pois = await fetch_pois(_BBOX, "Roma")

    bank = next(p for p in pois if p["id"] == "node/1001")
    assert bank == {
        "id": "node/1001",
        "name": "Banca Intesa Sanpaolo",
        "lat": pytest.approx(41.8902),
        "lon": pytest.approx(12.4922),
        "osm_tags": "amenity=bank",
        "terminus_class": "Bank",
        "citta": "Roma",
    }


@respx.mock
async def test_fetch_pois_with_cut_extracts_the_osm_cut_from_the_payload() -> None:
    """#251: the cut declared by Overpass in ``osm3s`` becomes OsmCut."""
    payload = {**_sample(), "osm3s": {"timestamp_osm_base": "2026-07-26T17:42:03Z"}}
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    pois, cut = await fetch_pois_with_cut(_BBOX, "Roma")

    assert pois  # same pool as fetch_pois, it is not the point of the test
    assert cut == {
        "timestamp_osm_base": "2026-07-26T17:42:03Z",
        "overpass_url": DEFAULT_OVERPASS_URL,
    }


@respx.mock
async def test_fetch_pois_with_cut_absent_when_payload_does_not_declare_it() -> None:
    """Payload without ``osm3s``/``timestamp_osm_base``: cut absent, not an error."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_sample())
    )

    pois, cut = await fetch_pois_with_cut(_BBOX, "Roma")

    assert pois
    assert cut["timestamp_osm_base"] is None
    assert cut["overpass_url"] == DEFAULT_OVERPASS_URL


@respx.mock
async def test_fetch_pois_discards_the_cut_and_behaves_as_before() -> None:
    """fetch_pois stays a wrapper that returns only the list of POIs (#251)."""
    payload = {**_sample(), "osm3s": {"timestamp_osm_base": "2026-07-26T17:42:03Z"}}
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert isinstance(pois, list)
    assert pois and "terminus_class" in pois[0]


@respx.mock
async def test_fetch_pois_enriches_terminus_class() -> None:
    """terminus_class derives from map_to_terminus; unknown tag -> GenericUrbanPOI."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_sample())
    )

    pois = await fetch_pois(_BBOX, "Roma")
    by_id = {p["id"]: p for p in pois}

    assert by_id["node/1002"]["terminus_class"] == "Museum"
    assert by_id["node/1003"]["terminus_class"] == "GenericUrbanPOI"
    assert by_id["way/2001"]["terminus_class"] == "Railway_station"


@respx.mock
async def test_fetch_pois_uses_way_center_and_skips_untagged() -> None:
    """Ways use 'center' for lat/lon; nodes without tags are discarded."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_sample())
    )

    pois = await fetch_pois(_BBOX, "Roma")
    by_id = {p["id"]: p for p in pois}

    assert "node/1004" not in by_id  # untagged node discarded
    assert by_id["way/2001"]["lat"] == pytest.approx(41.8920)
    assert by_id["way/2001"]["lon"] == pytest.approx(12.4940)


@respx.mock
async def test_fetch_pois_caps_at_max() -> None:
    """No more than MAX_POIS elements are ever returned."""
    elements = [
        {
            "type": "node",
            "id": 3000 + i,
            "lat": 41.89,
            "lon": 12.49,
            "tags": {"amenity": "bank", "name": f"Bank {i}"},
        }
        for i in range(MAX_POIS + 20)
    ]
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": elements})
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert len(pois) == MAX_POIS


@respx.mock
async def test_fetch_pois_retries_once_then_succeeds() -> None:
    """Timeout on the first call -> one retry with extended timeout -> success."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.TimeoutException("slow"),
            httpx.Response(200, json=_sample()),
        ]
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert route.call_count == 2
    assert len(pois) > 0


@respx.mock
async def test_fetch_pois_retries_on_429_then_succeeds() -> None:
    """429 on the first call -> one retry -> success (429 is retryable)."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.Response(429, text="rate limited"),
            httpx.Response(200, json=_sample()),
        ]
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert route.call_count == 2
    assert len(pois) > 0


@respx.mock
async def test_fetch_pois_raises_after_retry_exhausted() -> None:
    """Timeout on both attempts -> OverpassError (mappable to 503)."""
    respx.post(DEFAULT_OVERPASS_URL).mock(side_effect=httpx.TimeoutException("slow"))

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma")


@respx.mock
async def test_fetch_pois_raises_on_http_error() -> None:
    """Status 504 (retryable) on both attempts -> retry exhausted -> error."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(504, text="gateway timeout")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma")

    assert route.call_count == 2


@respx.mock
async def test_fetch_pois_does_not_retry_on_non_retryable_status() -> None:
    """Non-retryable non-2xx status (400) -> immediate OverpassError, no retry."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(400, text="bad request")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma")

    assert route.call_count == 1


# --- #232: explicit retry policy, and offline capture that can wait ---
# The pauses are NEVER real: every test injects a ``sleep`` that records them.


def _recording_sleep(waits: list[float]):  # noqa: ANN202  (test closure)
    async def _sleep(seconds: float) -> None:
        waits.append(seconds)

    return _sleep


@respx.mock
async def test_offline_policy_survives_two_retryable_responses() -> None:
    """The real scenario of 26/07: 504 then 429 must not make the capture fail.

    With the interactive policy (a single retry) this sequence fails: it is exactly
    the defect of #232, which had forced a hand-written backoff outside the code.
    """
    waits: list[float] = []
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.Response(504, text="gateway timeout"),
            httpx.Response(429, text="rate limited"),
            httpx.Response(200, json=_sample()),
        ]
    )

    pois = await fetch_pois(
        _BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(waits)
    )

    assert route.call_count == 3
    assert len(pois) > 0
    # Increasing pauses declared by the policy, in order.
    assert waits == list(OFFLINE_RETRY.pause_s[:2])


@respx.mock
async def test_interactive_policy_stays_at_a_single_retry() -> None:
    """The /analyze path stays fail-fast: no latency regression (#232).

    A user is waiting: two attempts and then the error, as before #232.
    """
    waits: list[float] = []
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(504, text="gateway timeout")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma", sleep=_recording_sleep(waits))

    assert route.call_count == 2
    assert len(INTERACTIVE_RETRY.pause_s) == 1
    assert len(waits) == 1
    # The timeouts stay those from before #232: the worst-case latency on
    # /analyze does not change (30s + 1s + 60s).
    assert INTERACTIVE_RETRY.timeout_s == 30.0
    assert INTERACTIVE_RETRY.retry_timeout_s == 60.0


@respx.mock
async def test_interactive_policy_ignores_retry_after() -> None:
    """The interactive pause stays 1s even if the server asks for more (#232).

    It is the «no perceived-latency regression» criterion taken literally: on
    ``/analyze`` a user is waiting, and lengthening the wait because Overpass asks
    for it would worsen exactly what we want to keep low. It also holds for
    ``capture_city`` (#31), where the pause falls INSIDE the timed window of
    ``switch_ms`` (threshold 5000ms): a higher cap would have made the metric of a
    thesis contribution fail at the first transient 429.
    """
    waits: list[float] = []
    # Real policy, NOT the one zeroed by the fixture: here the value is the point.
    monkeypatch_free = replace(overpass_client.INTERACTIVE_RETRY, pause_s=(1.0,))
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "60"}, text="rate limited"),
            httpx.Response(200, json=_sample()),
        ]
    )

    await fetch_pois(
        _BBOX, "Roma", retry=monkeypatch_free, sleep=_recording_sleep(waits)
    )

    assert waits == [1.0]
    assert INTERACTIVE_RETRY.retry_after_cap_s is None


@respx.mock
async def test_retry_after_beyond_the_cap_gives_up_immediately() -> None:
    """If the server asks for more than the cap, we give up instead of retrying early.

    Retrying before what Overpass asked for would be hammering a free public service
    (#232 explicitly rules it out) and would burn the remaining retries in attempts
    with zero probability. The message says how much the server asked for, so the
    operator knows when to retry.
    """
    waits: list[float] = []
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(
            429, headers={"Retry-After": "3600"}, text="rate limited"
        )
    )

    with pytest.raises(OverpassError, match="3600"):
        await fetch_pois(
            _BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(waits)
        )

    assert route.call_count == 1  # no second attempt
    assert waits == []  # and no wait spent


@respx.mock
async def test_retries_leave_a_trace_in_the_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every retry is declared (#232): with the offline policy the overall wait
    reaches minutes, and without a trace «hung process» and «courtesy backoff in
    progress» are indistinguishable — the condition that on 26/07 led to writing the
    backoff by hand in a shell."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.Response(504, text="gateway timeout"),
            httpx.Response(200, json=_sample()),
        ]
    )

    with caplog.at_level("WARNING"):
        await fetch_pois(_BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep([]))

    messages = [r.getMessage() for r in caplog.records]
    assert any("504" in m and "retry 1/4" in m for m in messages), messages


@respx.mock
async def test_retry_after_is_honored_when_it_exceeds_the_planned_pause() -> None:
    """``Retry-After: 30`` with a planned pause of 5s -> we wait 30s (#232)."""
    waits: list[float] = []
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "30"}, text="rate limited"),
            httpx.Response(200, json=_sample()),
        ]
    )

    await fetch_pois(_BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(waits))

    assert waits == [30.0]


@respx.mock
async def test_retry_after_does_not_shorten_the_courtesy_pause() -> None:
    """``Retry-After: 1`` does not lower the pause below the planned one: towards a
    free public service courtesy is a minimum, not a maximum (#232)."""
    waits: list[float] = []
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "1"}, text="rate limited"),
            httpx.Response(200, json=_sample()),
        ]
    )

    await fetch_pois(_BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(waits))

    assert waits == [OFFLINE_RETRY.pause_s[0]]


@respx.mock
async def test_retry_after_unreadable_falls_back_to_the_planned_pause() -> None:
    """HTTP-date form of ``Retry-After``: not interpreted, the planned pause is used
    instead of failing or waiting at random (#232)."""
    waits: list[float] = []
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.Response(
                429,
                headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
                text="rate limited",
            ),
            httpx.Response(200, json=_sample()),
        ]
    )

    await fetch_pois(_BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(waits))

    assert waits == [OFFLINE_RETRY.pause_s[0]]


@respx.mock
async def test_non_retryable_status_never_waits() -> None:
    """A 400 is not transient: no pause, immediate error (#232)."""
    waits: list[float] = []
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(400, text="bad request")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(
            _BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(waits)
        )

    assert waits == []


@respx.mock
async def test_offline_policy_exhausted_raises_overpass_error() -> None:
    """Even the long policy has a limit: exhausted, a clear error (#232)."""
    waits: list[float] = []
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(429, text="rate limited")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(
            _BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(waits)
        )

    assert route.call_count == 1 + len(OFFLINE_RETRY.pause_s)
    assert waits == list(OFFLINE_RETRY.pause_s)


def test_offline_policy_waits_longer_than_the_interactive() -> None:
    """Offline capture can afford minutes, the interactive one cannot (#232): the
    contract between the two policies is explicit and verified, not implicit."""
    assert sum(OFFLINE_RETRY.pause_s) > sum(INTERACTIVE_RETRY.pause_s)
    assert len(OFFLINE_RETRY.pause_s) > len(INTERACTIVE_RETRY.pause_s)
    # Only the offline policy honours Retry-After; the interactive one ignores it.
    assert INTERACTIVE_RETRY.retry_after_cap_s is None
    assert OFFLINE_RETRY.retry_after_cap_s is not None


def test_the_cap_does_not_shorten_the_declared_pauses() -> None:
    """The cap applies to the server's request, not to the policy's pause.

    With ``min(wait, cap)`` a future policy with pauses longer than the cap would
    have seen its courtesy silently shortened: invariant made explicit here instead
    of staying implicit in the current values (review m1).
    """
    assert OFFLINE_RETRY.retry_after_cap_s is not None
    long_policy = replace(OFFLINE_RETRY, pause_s=(300.0,), retry_after_cap_s=60.0)
    assert (
        overpass_client._wait_before_retry(  # pyright: ignore[reportPrivateUsage]
            None, long_policy.pause_s[0], long_policy.retry_after_cap_s
        )
        == 300.0
    )


@respx.mock
async def test_fetch_pois_query_uses_key_value_selectors_and_caps() -> None:
    """The query uses k=v selectors with a per-selector 'out center' cap."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": []})
    )

    await fetch_pois(_BBOX, "Roma", ["amenity=bank", "tourism=museum"])

    body = route.calls.last.request.content.decode()
    assert "41.88,12.48,41.9,12.5" in body
    assert 'node["amenity"="bank"]' in body
    assert 'way["tourism"="museum"]' in body
    assert f"out center {PER_SELECTOR_CAP}" in body
    assert "[out:json][timeout:25]" in body
    # two 'out center' per selector (node+way union and relation, #314): with 2
    # selectors there must be exactly 4 blocks.
    assert body.count(f"out center {PER_SELECTOR_CAP}") == 4


# --- #314: relations (multipolygons) enter the candidate pool ---
# Many iconic monuments are mapped as relations: the Colosseo is relation/1834818
# 9 m from the centre of the Rome bbox, the Duomo di Milano relation/18017026. With
# a node+way-only query they never made it into the sample, however close they were.


@respx.mock
async def test_query_also_queries_relations_for_each_selector() -> None:
    """Every selector also queries relations, with ``out center``: without
    ``center`` a relation has no coordinates and would be discarded by the parsing."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": []})
    )

    await fetch_pois(_BBOX, "Roma", ["historic=archaeological_site", "tourism=museum"])

    body = route.calls.last.request.content.decode()
    bbox_str = "41.88,12.48,41.9,12.5"
    for key, value in (("historic", "archaeological_site"), ("tourism", "museum")):
        assert (
            f'relation["{key}"="{value}"]({bbox_str});\nout center {PER_SELECTOR_CAP};'
        ) in body
    # Every type declared as queried really appears in the query: the constant
    # recorded in the snapshot provenance cannot diverge.
    for element_type in overpass_client.ELEMENT_TYPES:
        assert f"{element_type}[" in body


@respx.mock
async def test_relation_with_own_cap_and_node_way_block_unchanged() -> None:
    """Relations have a separate ``out``, the node+way block stays identical.

    Two reasons. Overpass prints a set in type order (node, way, relation): inside
    the union with the ``out center N`` cap a dense selector such as
    ``tourism=attraction`` would exhaust the slots with node and way before getting
    to the Colosseo, i.e. the defect that #314 closes. And the node+way block
    unchanged byte for byte means the previous node+way pool stays the same: the
    change ADDS candidates, it does not replace them.
    """
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": []})
    )

    await fetch_pois(_BBOX, "Roma", ["amenity=bank", "tourism=museum"])

    body = route.calls.last.request.content.decode()
    bbox_str = "41.88,12.48,41.9,12.5"
    assert (
        f'(\n  node["amenity"="bank"]({bbox_str});\n'
        f'  way["amenity"="bank"]({bbox_str});\n);\n'
        f"out center {PER_SELECTOR_CAP};"
    ) in body
    # One out for the node+way union and one for the relations, for each selector.
    assert body.count(f"out center {PER_SELECTOR_CAP};") == 4
    # Relations are NOT inside the union with the shared cap.
    assert "  relation[" not in body


# Tags of the real Colosseo relation (relation/1834818): archaeological site and
# tourist attraction at once, the case of #314 (relation) and #373 (priority).
_COLOSSEO_ID = 1834818
_COLOSSEO_TAGS: dict[str, str] = {
    "type": "multipolygon",
    "historic": "archaeological_site",
    "tourism": "attraction",
    "name": "Colosseo",
}


def _relation(
    rel_id: int, lat: float, lon: float, tags: dict[str, str]
) -> dict[str, object]:
    """Relation element as Overpass returns it with ``out center``."""
    return {
        "type": "relation",
        "id": rel_id,
        "center": {"lat": lat, "lon": lon},
        "tags": tags,
    }


def _overpass_honoring_the_query(
    others: list[dict[str, object]], relations: list[dict[str, object]]
) -> Callable[[httpx.Request], httpx.Response]:
    """respx ``side_effect``: relations arrive ONLY if the query asks for them.

    A mock that returns the relations whatever the query is verifies the parsing,
    not #314: it would stay green even removing the relation block from
    ``_build_query``. This way the test turns red, as Overpass would.
    """

    def _respond(request: httpx.Request) -> httpx.Response:
        asks_for_relation = "relation[" in request.content.decode()
        elements_ = others + (relations if asks_for_relation else [])
        return httpx.Response(200, json={"elements": elements_})

    return _respond


@respx.mock
async def test_relation_becomes_poi_with_typed_id_and_coordinates_from_center() -> None:
    """A relation requested by the query goes through the parsing like a way:
    coordinates from ``center``, id ``relation/<n>``, TERMINUS class from the same
    selectors and priority."""
    duomo = _relation(
        18017026,
        45.4641844,
        9.1916105,
        {
            "type": "multipolygon",
            "amenity": "place_of_worship",
            "building": "cathedral",
            "tourism": "attraction",
            "name": "Duomo di Milano",
        },
    )
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=_overpass_honoring_the_query([], [duomo])
    )

    pois = await fetch_pois(Bbox(45.46, 9.18, 45.47, 9.20), "Milano")

    assert pois == [
        {
            "id": "relation/18017026",
            "name": "Duomo di Milano",
            "lat": pytest.approx(45.4641844),
            "lon": pytest.approx(9.1916105),
            "osm_tags": "amenity=place_of_worship",
            "terminus_class": "Place_of_worship",
            "citta": "Milano",
        }
    ]


@respx.mock
async def test_relation_near_the_center_enters_the_sample() -> None:
    """The case of the issue: the relation a few metres from the centre enters first,
    even with the pool full of farther nodes.

    Fake Overpass that returns the Colosseo only if the query asks for the
    relations: without the relation block in ``_build_query`` the sample would be
    made of nodes only, i.e. the defect of #314.
    """
    lat, lon = _BBOX.center()
    nodes: list[dict[str, object]] = [
        {
            "type": "node",
            "id": 5000 + i,
            "lat": lat + 0.005,
            "lon": lon,
            "tags": {"tourism": "attraction", "name": f"Attrazione {i}"},
        }
        for i in range(MAX_POIS)
    ]
    colosseo = _relation(_COLOSSEO_ID, lat + 0.00008, lon, dict(_COLOSSEO_TAGS))
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=_overpass_honoring_the_query(nodes, [colosseo])
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert pois[0]["id"] == "relation/1834818"
    assert pois[0]["name"] == "Colosseo"


@respx.mock
async def test_relation_emitted_by_several_blocks_enters_once() -> None:
    """The Colosseo carries both ``tourism=attraction`` and
    ``historic=archaeological_site``: it arrives from the block of each selector and
    must count only once, as already for node and way."""
    lat, lon = _BBOX.center()
    colosseo = _relation(_COLOSSEO_ID, lat, lon, dict(_COLOSSEO_TAGS))
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=_overpass_honoring_the_query([], [colosseo, dict(colosseo)])
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert [p["id"] for p in pois] == ["relation/1834818"]


@respx.mock
async def test_relation_and_way_with_the_same_number_do_not_collide() -> None:
    """Relations have their own OSM namespace, like node and way (#265)."""
    lat, lon = _BBOX.center()
    way_elem: dict[str, object] = {
        "type": "way",
        "id": 77,
        "center": {"lat": lat, "lon": lon},
        "tags": {"tourism": "museum", "name": "Museo (way)"},
    }
    rel = _relation(77, lat, lon, {"amenity": "place_of_worship", "name": "Chiesa"})
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=_overpass_honoring_the_query([way_elem], [rel])
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert {p["id"] for p in pois} == {"way/77", "relation/77"}


@respx.mock
async def test_parsing_discards_a_relation_without_center() -> None:
    """Parsing non-regression, not a verification of #314: a relation without
    ``center`` (e.g. ``out`` without center) has no usable coordinates and must be
    discarded, not placed at random. It passes regardless of the query, on purpose:
    the presence of the relation block is verified by the tests above."""
    payload = {
        "elements": [
            {
                "type": "relation",
                "id": 1834818,
                "tags": {"historic": "archaeological_site", "name": "Colosseo"},
            }
        ]
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    assert await fetch_pois(_BBOX, "Roma") == []


# --- #371: the same object mapped as a way and as a multipolygon relation ---

# Ambiente 4 at the Palatino as Overpass returns it (``out center``, cut
# 2026-07-15): way/597452722 and relation/1835450 have the same name and the same
# ``historic``, centres ~34 m apart, and different secondary tags (``inscription``,
# ``fixme``, ``website``). The way is not a member of the relation: it is a
# second mapping of the same site.
_AMBIENTE_4_WAY: dict[str, object] = {
    "type": "way",
    "id": 597452722,
    "center": {"lat": 41.8900546, "lon": 12.4899794},
    "tags": {
        "historic": "archaeological_site",
        "historic:civilization": "ancient_roman",
        "inscription": "Ambiente 4- Luogo di Ritrovamento dei temenoi arcaici.",
        "name": "Ambiente 4",
    },
}
_AMBIENTE_4_REL: dict[str, object] = {
    "type": "relation",
    "id": 1835450,
    "center": {"lat": 41.8901595, "lon": 12.4895943},
    "tags": {
        "fixme": "location and detailing",
        "historic": "archaeological_site",
        "historic:civilization": "ancient_roman",
        "inscription": "Ambiente 4 - Area di scavo arcaica.",
        "name": "Ambiente 4",
        "type": "multipolygon",
        "website": "http://archeopalatino.uniroma1.it/",
    },
}

# Degrees of latitude per metre (mean sphere), to shift an element by hand.
_DEGREES_PER_METER = 1 / 111_195.0


def _variant(
    element: dict[str, object],
    *,
    north_m: float = 0.0,
    as_node: bool = False,
    elem_id: int | None = None,
    tags: dict[str, str] | None = None,
) -> dict[str, object]:
    """Copy of ``element`` shifted northwards, possibly as a node, with id
    or tags replaced."""
    copy = dict(element)
    center = cast(dict[str, float], element["center"])
    lat = center["lat"] + north_m * _DEGREES_PER_METER
    if as_node:
        del copy["center"]
        copy.update(type="node", lat=lat, lon=center["lon"])
    else:
        copy["center"] = {"lat": lat, "lon": center["lon"]}
    if elem_id is not None:
        copy["id"] = elem_id
    if tags is not None:
        copy["tags"] = tags
    return copy


def _tags(element: dict[str, object]) -> dict[str, str]:
    return dict(cast(dict[str, str], element["tags"]))


def _parse(elements: list[dict[str, object]]) -> list[Poi]:
    return overpass_client._parse_elements(  # pyright: ignore[reportPrivateUsage]
        {"elements": elements}, "Roma"
    )


def _sorted_ids(elements: list[dict[str, object]]) -> list[str]:
    return sorted(p["id"] for p in _parse(elements))


def test_way_duplicate_of_the_multipolygon_relation_is_discarded() -> None:
    """The case of the issue: only the relation remains, once."""
    assert _sorted_ids([_AMBIENTE_4_WAY, _AMBIENTE_4_REL]) == ["relation/1835450"]


def test_survivor_does_not_depend_on_the_emission_order() -> None:
    """The relation survives even if it arrives before the way, with its
    coordinates: the POI's id and centre do not depend on Overpass's order."""
    for elements_ in (
        [_AMBIENTE_4_WAY, _AMBIENTE_4_REL],
        [_AMBIENTE_4_REL, _AMBIENTE_4_WAY],
    ):
        pois = _parse(elements_)
        assert [p["id"] for p in pois] == ["relation/1835450"]
        assert (pois[0]["lat"], pois[0]["lon"]) == (41.8901595, 12.4895943)


def test_same_name_but_different_family_tags_do_not_merge() -> None:
    """One extra ``tourism=attraction`` on the way is enough to keep them distinct."""
    tags_way = _tags(_AMBIENTE_4_WAY) | {"tourism": "attraction"}
    way = _variant(_AMBIENTE_4_WAY, tags=tags_way)
    assert _sorted_ids([way, _AMBIENTE_4_REL]) == [
        "relation/1835450",
        "way/597452722",
    ]


def test_same_name_but_different_family_value_do_not_merge() -> None:
    """Same key, different value: ``historic=ruins`` is not the same site."""
    tags_way = _tags(_AMBIENTE_4_WAY) | {"historic": "ruins"}
    way = _variant(_AMBIENTE_4_WAY, tags=tags_way)
    assert _sorted_ids([way, _AMBIENTE_4_REL]) == [
        "relation/1835450",
        "way/597452722",
    ]


def test_same_name_and_tag_but_far_apart_do_not_merge() -> None:
    """Beyond the proximity threshold they are two homonymous sites, not a duplicate."""
    threshold = overpass_client.MAX_DUPLICATE_DISTANCE_M
    rel = cast(dict[str, float], _AMBIENTE_4_REL["center"])
    way = _variant(_AMBIENTE_4_REL, north_m=threshold + 5, elem_id=597452722)
    way["type"] = "way"
    way["tags"] = _tags(_AMBIENTE_4_WAY)
    way_center = cast(dict[str, float], way["center"])
    distance = haversine_m(rel["lat"], rel["lon"], way_center["lat"], rel["lon"])
    assert threshold < distance < threshold + 10
    assert _sorted_ids([way, _AMBIENTE_4_REL]) == [
        "relation/1835450",
        "way/597452722",
    ]


def test_two_homonymous_nearby_ways_do_not_merge() -> None:
    """Never two elements of the same type: they are distinct OSM objects."""
    twin = _variant(_AMBIENTE_4_WAY, north_m=5, elem_id=597452723)
    assert _sorted_ids([_AMBIENTE_4_WAY, twin]) == [
        "way/597452722",
        "way/597452723",
    ]


def test_homonymous_node_near_the_relation_does_not_merge() -> None:
    """Never nodes: a point inside a homonymous area stays a POI on its own."""
    node_elem = _variant(_AMBIENTE_4_REL, as_node=True, elem_id=42)
    node_elem["tags"] = _tags(_AMBIENTE_4_WAY)
    assert _sorted_ids([node_elem, _AMBIENTE_4_REL]) == ["node/42", "relation/1835450"]


def test_homonymous_node_and_way_do_not_merge() -> None:
    """Two "Termini" stops or a homonymous node and area stay distinct."""
    node_elem = _variant(_AMBIENTE_4_WAY, north_m=3, as_node=True, elem_id=42)
    assert _sorted_ids([node_elem, _AMBIENTE_4_WAY]) == ["node/42", "way/597452722"]


@pytest.mark.parametrize("name", [None, "", "   "])
def test_nameless_way_and_relation_do_not_merge(name: str | None) -> None:
    """Without a name there is no way to say they are the same object."""

    def _with_name(element: dict[str, object]) -> dict[str, object]:
        tags = {k: v for k, v in _tags(element).items() if k != "name"}
        if name is not None:
            tags["name"] = name
        return _variant(element, tags=tags)

    assert _sorted_ids([_with_name(_AMBIENTE_4_WAY), _with_name(_AMBIENTE_4_REL)]) == [
        "relation/1835450",
        "way/597452722",
    ]


def test_relation_that_is_not_a_multipolygon_does_not_absorb_the_way() -> None:
    """A ``type=site`` relation groups distinct objects: it is not the way's area,
    so it is not a duplicate of it."""
    rel = _variant(_AMBIENTE_4_REL, tags=_tags(_AMBIENTE_4_REL) | {"type": "site"})
    assert _sorted_ids([_AMBIENTE_4_WAY, rel]) == [
        "relation/1835450",
        "way/597452722",
    ]


def test_discarded_duplicate_frees_the_class_slot() -> None:
    """The deduplication happens before ``select_pois``: the slot the way
    occupied among the ``PER_CLASS_CAP`` Archaeological_site goes to the next site.

    Six filler classes at 500 m fill the other 17 slots in the first round, so the
    second round cannot recover the site discarded by the cap.
    """
    rel_center = cast(dict[str, float], _AMBIENTE_4_REL["center"])
    lat, lon = rel_center["lat"], rel_center["lon"]
    sites: list[dict[str, object]] = [
        {
            "type": "node",
            "id": 9000 + i,
            "lat": lat + (60 + 20 * i) * _DEGREES_PER_METER,
            "lon": lon,
            "tags": {"historic": "archaeological_site", "name": f"Sito {i}"},
        }
        for i in range(2)
    ]
    values = ["bank", "pharmacy", "school", "hospital", "fuel", "police"]
    fillers: list[dict[str, object]] = [
        {
            "type": "node",
            "id": 8000 + i,
            "lat": lat - 500 * _DEGREES_PER_METER,
            "lon": lon + i * 0.00001,
            "tags": {"amenity": value, "name": f"Riempitivo {i}"},
        }
        for i, value in enumerate(values * 3)
    ]

    chosen = overpass_client.select_pois(
        _parse([_AMBIENTE_4_WAY, _AMBIENTE_4_REL, *sites, *fillers]), (lat, lon)
    )

    assert len(chosen) == MAX_POIS
    archaeological = [
        p["id"] for p in chosen if p["terminus_class"] == "Archaeological_site"
    ]
    assert archaeological == ["relation/1835450", "node/9000", "node/9001"]


@respx.mock
async def test_fetch_pois_sets_explicit_user_agent() -> None:
    """Explicit UA on the Overpass request (not the httpx default): avoids the 406."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": []})
    )

    await fetch_pois(_BBOX, "Roma", ["amenity=bank"])

    assert (
        route.calls.last.request.headers.get("user-agent")
        == "crime-risk-analyzer (https://github.com/Salvo-Rosolia/crime-risk-analyzer)"
    )


@respx.mock
async def test_fetch_pois_user_agent_includes_contact_url() -> None:
    """The Overpass usage policy requires a contact in the UA (fail-if-removed)."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": []})
    )

    await fetch_pois(_BBOX, "Roma", ["amenity=bank"])

    user_agent = route.calls.last.request.headers.get("user-agent")
    assert user_agent is not None
    assert "https://github.com/Salvo-Rosolia/crime-risk-analyzer" in user_agent


@respx.mock
async def test_fetch_pois_raises_on_network_error() -> None:
    """Non-timeout network error (e.g. connection) -> immediate OverpassError.

    Default (interactive) policy: the /analyze path must not gain latency for a
    transport blip, so no additional retry (#247).
    """
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=httpx.ConnectError("refused")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma")

    assert route.call_count == 1


# --- #247: transport blips (non-timeout) retryable ONLY in offline capture ---


@respx.mock
async def test_offline_policy_retries_on_connection_error_then_succeeds() -> None:
    """A transient ConnectError is no longer final in offline capture: #232
    had closed transient timeouts and statuses, not transport blips (#247)."""
    waits: list[float] = []
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.ConnectError("connection refused"),
            httpx.Response(200, json=_sample()),
        ]
    )

    pois = await fetch_pois(
        _BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(waits)
    )

    assert route.call_count == 2
    assert len(pois) > 0
    assert waits == [OFFLINE_RETRY.pause_s[0]]


@respx.mock
async def test_offline_policy_retries_on_remote_protocol_error() -> None:
    """The server closing the connection without a response is as transient as
    a 504: Overpass under load does it at least as often as it returns 504 (#247)."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.RemoteProtocolError(
                "Server disconnected without sending a response."
            ),
            httpx.Response(200, json=_sample()),
        ]
    )

    pois = await fetch_pois(
        _BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep([])
    )

    assert route.call_count == 2
    assert len(pois) > 0


@respx.mock
async def test_offline_policy_retries_on_read_error() -> None:
    """Connection interrupted mid-read: same treatment (#247)."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.ReadError("connection reset"),
            httpx.Response(200, json=_sample()),
        ]
    )

    pois = await fetch_pois(
        _BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep([])
    )

    assert route.call_count == 2
    assert len(pois) > 0


@respx.mock
async def test_offline_policy_exhausted_on_transport_raises_overpass_error() -> None:
    """A persistent transport blip gives up like any other exhausted
    retryable: it does not stay hanging (#247)."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=httpx.ConnectError("refused")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep([]))

    assert route.call_count == 1 + len(OFFLINE_RETRY.pause_s)


@respx.mock
async def test_offline_policy_does_not_retry_unlisted_transport_errors() -> None:
    """A transport error OUTSIDE the explicit list stays final even in offline
    capture: only connection/remote protocol/read are transient blips, not any
    ``httpx.HTTPError`` (#247)."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=httpx.LocalProtocolError("malformed request")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep([]))

    assert route.call_count == 1


@respx.mock
async def test_retry_on_transport_error_leaves_a_trace_in_the_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The log distinguishes a transport blip from a real timeout: otherwise
    the operator reads «timeout» where there was a refused connection (#247)."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.ConnectError("connection refused"),
            httpx.Response(200, json=_sample()),
        ]
    )

    with caplog.at_level("WARNING"):
        await fetch_pois(_BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep([]))

    messages = [r.getMessage() for r in caplog.records]
    found = any("errore di trasporto" in m and "retry 1/4" in m for m in messages)
    assert found, messages


@respx.mock
async def test_fetch_pois_raises_on_invalid_json() -> None:
    """200 response but non-JSON body -> OverpassError."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, text="not json")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma")


# --- parsing edge cases (exercised way_elem the public API) ---


@respx.mock
async def test_fetch_pois_tag_priority_amenity_over_shop() -> None:
    """With several known keys the priority wins (amenity before shop)."""
    payload = {
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 41.0,
                "lon": 12.0,
                "tags": {"shop": "mall", "amenity": "bank", "name": "X"},
            }
        ]
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert pois[0]["osm_tags"] == "amenity=bank"
    assert pois[0]["terminus_class"] == "Bank"


@respx.mock
async def test_fetch_pois_picks_first_mapped_selector_not_first_present() -> None:
    """A high-priority but UNMAPPED tag does not win: the first mapped one is chosen."""
    payload = {
        "elements": [
            {
                "type": "node",
                "id": 11,
                "lat": 41.0,
                "lon": 12.0,
                "tags": {"amenity": "bar", "building": "warehouse", "name": "Deposito"},
            }
        ]
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    pois = await fetch_pois(_BBOX, "Roma")

    # amenity=bar is present and of higher priority but is NOT in the dict -> skipped;
    # building=warehouse is mapped -> wins.
    assert pois[0]["osm_tags"] == "building=warehouse"
    assert pois[0]["terminus_class"] == "Warehouse"


@respx.mock
async def test_colosseo_relation_resolves_archaeological_site() -> None:
    """#373 end-to-end on the real case: the Colosseo arrives as a relation with
    ``historic=archaeological_site`` + ``tourism=attraction`` and must come out as
    ``Archaeological_site``, not ``Historical_monument``."""
    lat, lon = _BBOX.center()
    colosseo = _relation(_COLOSSEO_ID, lat, lon, dict(_COLOSSEO_TAGS))
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=_overpass_honoring_the_query([], [colosseo])
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert pois[0]["id"] == f"relation/{_COLOSSEO_ID}"
    assert pois[0]["osm_tags"] == "historic=archaeological_site"
    assert pois[0]["terminus_class"] == "Archaeological_site"


@pytest.mark.parametrize(
    ("tags", "osm_tag", "terminus_class"),
    [
        pytest.param(
            _COLOSSEO_TAGS,
            "historic=archaeological_site",
            "Archaeological_site",
            id="colosseo-archaeological-site-wins-over-attraction",
        ),
        pytest.param(
            {"tourism": "attraction", "historic": "monument", "name": "Arco"},
            "historic=monument",
            "Historical_monument",
            id="arco-monument-wins-over-attraction",
        ),
        pytest.param(
            {"tourism": "attraction", "historic": "wayside_cross", "name": "Croce"},
            "tourism=attraction",
            "Historical_monument",
            id="unmapped-historic-does-not-steal-from-attraction",
        ),
        pytest.param(
            {"tourism": "museum", "historic": "castle", "name": "Castello"},
            "tourism=museum",
            "Museum",
            id="museum-stays-ahead-of-historic",
        ),
        pytest.param(
            {
                "amenity": "place_of_worship",
                "tourism": "attraction",
                "historic": "monument",
                "name": "Basilica",
            },
            "amenity=place_of_worship",
            "Place_of_worship",
            id="amenity-stays-ahead-of-everything",
        ),
    ],
)
def test_historic_wins_only_over_tourism_attraction(
    tags: dict[str, str], osm_tag: str, terminus_class: str
) -> None:
    """``tourism=attraction`` is a generic tag: on an element that also carries a
    mapped ``historic=*`` the historic tag wins (#373). The other precedences do not
    change: ``tourism=museum`` stays ahead of ``historic`` and ``amenity`` ahead of
    both. Pure function: no HTTP call."""
    selector = overpass_client._extract_osm_tag(tags)  # pyright: ignore[reportPrivateUsage]

    assert selector == osm_tag
    assert map_to_terminus(selector) == terminus_class


@respx.mock
async def test_fetch_pois_unknown_tag_yields_generic() -> None:
    """Element with only unmapped tags -> empty osm_tags and GenericUrbanPOI."""
    payload = {
        "elements": [
            {
                "type": "node",
                "id": 7,
                "lat": 41.0,
                "lon": 12.0,
                "tags": {"leisure": "park", "name": "Parco"},
            }
        ]
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert pois[0]["osm_tags"] == ""
    assert pois[0]["terminus_class"] == "GenericUrbanPOI"


@respx.mock
async def test_fetch_pois_element_without_coords_or_center_is_skipped() -> None:
    """Element with tags but no lat/lon nor 'center' is discarded."""
    payload = {
        "elements": [
            {"type": "node", "id": 8, "tags": {"amenity": "bank", "name": "X"}}
        ]
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    assert await fetch_pois(_BBOX, "Roma") == []


@respx.mock
async def test_fetch_pois_element_without_type_is_skipped() -> None:
    """Element without ``type`` is discarded instead of producing an id ``"/123"``.

    A silent fallback to an empty string would reopen the same collision between
    different ``id`` that #265 closes: two elements equally lacking ``type`` would
    both end up on ``"/<number>"``.
    """
    payload = {
        "elements": [
            {
                "id": 55,
                "lat": 41.0,
                "lon": 12.0,
                "tags": {"amenity": "bank", "name": "X"},
            }
        ]
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    assert await fetch_pois(_BBOX, "Roma") == []


@respx.mock
async def test_fetch_pois_way_without_coords_is_skipped() -> None:
    """Way with a center lacking numeric coordinates is discarded."""
    payload = {
        "elements": [
            {
                "type": "way",
                "id": 9,
                "center": {"foo": "bar"},
                "tags": {"amenity": "bank", "name": "X"},
            }
        ]
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    assert await fetch_pois(_BBOX, "Roma") == []


@respx.mock
async def test_fetch_pois_payload_not_object_raises() -> None:
    """Non-object JSON payload (list) -> OverpassError."""
    respx.post(DEFAULT_OVERPASS_URL).mock(return_value=httpx.Response(200, json=["x"]))

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma")


@respx.mock
async def test_fetch_pois_missing_elements_raises() -> None:
    """Payload lacking the 'elements' list -> OverpassError."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"version": 0.6})
    )

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma")


@respx.mock
async def test_fetch_pois_skips_non_dict_elements() -> None:
    """Non-object elements in the list are ignored without error."""
    payload = {
        "elements": [
            "garbage",
            {
                "type": "node",
                "id": 1,
                "lat": 41.0,
                "lon": 12.0,
                "tags": {"amenity": "bank", "name": "B"},
            },
        ]
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    pois = await fetch_pois(_BBOX, "Roma")
    assert len(pois) == 1
    assert pois[0]["id"] == "node/1"


# --- #372: Overpass ``remark`` and truncated responses ---
# When ``[timeout:25]`` fires (or the server-side memory) Overpass answers
# 200 with a ``remark`` field and the elements found UP TO THERE: the selectors
# at the bottom of the query are missing. The interruption forms below follow the
# ``runtime error:`` prefix; those without a prefix exercise the fallback phrases of
# ``_TRUNCATION_HINTS`` in case the prefix changed.

_REMARK_TIMEOUT = (
    'runtime error: Query timed out in "query" at line 3 after 26 seconds.'
)

_REMARK_MEMORY = "runtime error: Query run out of memory using about 2048 MB of RAM."

_REMARK_INCOMPLETE = (
    _REMARK_TIMEOUT,
    _REMARK_MEMORY,
    'runtime error: Query timed out in "recurse" at line 41 after 25 seconds.',
    'runtime error: Query run out of memory in "query" at line 7 using about '
    "2048 MB of RAM.",
    'runtime error: Query ran out of memory in "union" at line 12. It would need '
    "at least 0 MB of RAM to continue.",
    "Runtime error: something went wrong while executing the query.",
    # Without the ``runtime error`` prefix: detected only by the fallback phrases.
    'Error: Query timed out in "query" at line 3 after 26 seconds.',
    "Query ran out of memory",
    "Query run out of memory",
)

# HYPOTHETICAL, defensive forms: it is not proven that Overpass emits them. If a
# remark that does not declare an interruption ever appeared, it must not be retried.
_REMARK_INFORMATIVE = (
    "runtime remark: Timeout is 180 and maxsize is 536870912.",
    "runtime remark: The query has been executed with the attic data.",
    "",
)


@pytest.mark.parametrize("remark", _REMARK_INCOMPLETE)
def test_interruption_remark_signals_incomplete_response(remark: str) -> None:
    assert remark_signals_incomplete_response(remark) is True


@pytest.mark.parametrize("remark", _REMARK_INFORMATIVE)
def test_informative_remark_does_not_signal_incomplete_response(remark: str) -> None:
    assert remark_signals_incomplete_response(remark) is False


# Ids of the complete sample after ``select_pois`` (node/1004 has no name); the
# truncated response carries only node/1001.
_FULL_SAMPLE_IDS = ["node/1001", "node/1002", "node/1003", "way/2001"]


def _truncated() -> dict[str, object]:
    """Truncated 200 response: first element of the sample and the timeout remark."""
    sample = _sample()
    elements = cast(list[object], sample["elements"])
    return {**sample, "elements": elements[:1], "remark": _REMARK_TIMEOUT}


@respx.mock
async def test_timeout_remark_is_not_accepted_as_a_complete_sample() -> None:
    """A truncated response is not a complete sample.

    Retries exhausted -> :class:`OverpassError`.
    """
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_truncated())
    )

    with pytest.raises(OverpassError) as exc_info:
        await fetch_pois(_BBOX, "Roma")

    message = str(exc_info.value)
    assert "Risposta incompleta di Overpass" in message
    assert _REMARK_TIMEOUT in message
    assert "dopo 2 tentativi" in message
    # Interactive policy: one attempt + one retry, then the error.
    assert route.call_count == 1 + len(overpass_client.INTERACTIVE_RETRY.pause_s)


@respx.mock
async def test_timeout_remark_also_exhausts_the_offline_policy() -> None:
    waits: list[float] = []
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_truncated())
    )

    with pytest.raises(
        OverpassError, match=r"Risposta incompleta di Overpass.*dopo 5 tentativi"
    ):
        await fetch_pois_with_cut(
            _BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(waits)
        )

    assert route.call_count == 1 + len(OFFLINE_RETRY.pause_s)
    assert waits == list(OFFLINE_RETRY.pause_s)


@respx.mock
async def test_memory_remark_is_not_described_as_timeout() -> None:
    """An out of memory is not a timeout, and without retries we do not say «after»."""
    sample = {**_sample(), "remark": _REMARK_MEMORY}
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=sample)
    )
    without_retries = replace(INTERACTIVE_RETRY, pause_s=())

    with pytest.raises(OverpassError) as exc_info:
        await fetch_pois(_BBOX, "Roma", retry=without_retries)

    message = str(exc_info.value)
    assert "timeout" not in message.lower()
    assert "tentativi" not in message
    assert "Risposta incompleta di Overpass" in message
    assert _REMARK_MEMORY in message
    assert route.call_count == 1


@respx.mock
async def test_timeout_remark_then_complete_response_retries_and_uses_the_second(
    caplog: pytest.LogCaptureFixture,
) -> None:
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.Response(200, json=_truncated()),
            httpx.Response(200, json=_sample()),
        ]
    )

    with caplog.at_level("WARNING"):
        pois = await fetch_pois(_BBOX, "Roma")

    assert route.call_count == 2
    # The sample is that of the second response, not the truncated one.
    assert sorted(p["id"] for p in pois) == _FULL_SAMPLE_IDS
    messages = [r.getMessage() for r in caplog.records]
    assert any("risposta incompleta" in m and "retry 1/1" in m for m in messages), (
        messages
    )


@respx.mock
async def test_informative_remark_neither_fails_nor_retries() -> None:
    sample = {**_sample(), "remark": _REMARK_INFORMATIVE[0]}
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=sample)
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert route.call_count == 1
    assert sorted(p["id"] for p in pois) == _FULL_SAMPLE_IDS


@respx.mock
async def test_non_string_remark_does_not_fail() -> None:
    """A ``remark`` of unexpected shape is not a declared interruption."""
    sample = {**_sample(), "remark": None}
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=sample)
    )

    await fetch_pois(_BBOX, "Roma")

    assert route.call_count == 1


@respx.mock
async def test_capture_does_not_write_a_snapshot_from_a_truncated_response(
    tmp_path: Path,
) -> None:
    """An incomplete sample must not end up on disk as if it were complete."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_truncated())
    )

    async def inner(bbox: Bbox, citta: str) -> tuple[list[Poi], OsmCut | None]:
        return await fetch_pois_with_cut(
            bbox, citta, retry=OFFLINE_RETRY, sleep=_recording_sleep([])
        )

    path = tmp_path / "snap.json"
    source = capturing_source(path, inner=inner, zona="Colosseo")

    with pytest.raises(OverpassError, match="incompleta di Overpass"):
        await source(_BBOX, "Roma")

    assert not path.exists()


@pytest.mark.integration
async def test_fetch_pois_integration_real_overpass() -> None:
    """Real integration with Overpass (skipped by default; -m integration to run it)."""
    pois = await fetch_pois(
        Bbox(41.889, 12.490, 41.892, 12.494), "Roma", ["amenity=bank", "tourism=museum"]
    )
    assert isinstance(pois, list)
