"""Overpass API client -> on-demand POIs (#16).

Queries Overpass in the bounding box of a city for a list of OSM keys and
returns the POIs in the RETRIEVAL contract: each POI exposes ``id``, ``name``,
``lat``, ``lon``, ``osm_tags``, ``ontology_class`` and ``citta``. The
``confidence`` and ``sparql_path`` fields are NOT added here: they are produced
by the downstream grounding/SPARQL layer.

Constraints (orchestrator.md): at most :data:`MAX_POIS` POIs per request; on
timeout, on a retryable status (429/5xx) or, in offline capture (#247), on a
transport blip (connection refused/closed/interrupted) it retries according to
the :class:`RetryPolicy` received, then :class:`OverpassError` (mapped to 503
by the orchestrator). A 200 response carrying an interruption remark is
retried like a timeout and, once the attempts are exhausted, raises
:class:`OverpassError` (503); the cost is latency: up to 2 attempts of ~26 s
each in interactive mode, 5 in offline. The calls are async
(``httpx.AsyncClient``): no blocking I/O.

Two policies, because the two contexts have opposite costs (#232):
:data:`INTERACTIVE_RETRY` for ``/analyze``, where a user is waiting and failing
early is correct; :data:`OFFLINE_RETRY` for the capture of the evaluation
snapshots, where waiting is free and failing means having no experiment. A
single implementation, parametrised.

Truncated responses (#372): when the query's ``[timeout:25]`` fires, or the
server-side memory runs out, Overpass does NOT answer with an HTTP error but
with a 200 carrying a ``remark`` field (``runtime error: Query timed out ...``)
and the elements found up to that point: the selectors at the bottom of the
query are missing. Such a response is treated as a timeout (same
:class:`RetryPolicy`) and, once the retries are exhausted, becomes
:class:`OverpassError`: never a partial pool silently accepted, neither returned
to ``/analyze`` nor written into a snapshot. A ``remark`` that does not declare
an interruption, if it ever appeared, changes nothing
(:func:`remark_signals_incomplete_response`).

The candidate pool is cut by Overpass before the selection by proximity:
see the DECLARED LIMIT on :data:`PER_SELECTOR_CAP`.

Way/relation duplicates (#371): a way that repeats a multipolygon relation
(same name, same family tags, centres within
:data:`MAX_DUPLICATE_DISTANCE_M`) is removed from the pool before the selection,
so it takes no seat among the :data:`MAX_POIS` nor in the per-class cap.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TypedDict, cast

import httpx

from crime_risk_analyzer.models.geo import Bbox, haversine_m
from crime_risk_analyzer.sources.context import current_osm

__all__ = [
    "MAX_DUPLICATE_DISTANCE_M",
    "INTERACTIVE_RETRY",
    "MAX_POIS",
    "OFFLINE_RETRY",
    "PER_CLASS_CAP",
    "PER_SELECTOR_CAP",
    "ELEMENT_TYPES",
    "Bbox",
    "OverpassError",
    "Poi",
    "RetryPolicy",
    "OsmCut",
    "fetch_pois",
    "fetch_pois_with_cut",
    "remark_signals_incomplete_response",
    "select_pois",
]

#: Default Overpass endpoint (can be overridden via parameter).
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

#: Maximum number of POIs returned per request (orchestrator.md / retrieval.md).
#: #212: reduced from 50 to 20 for less crowded and more readable results.
MAX_POIS = 20

#: Cap on elements returned by Overpass PER selector: it sizes the POOL of
#: CANDIDATES, not the result. The choice of the ``MAX_POIS`` that come out is up
#: to :func:`select_pois` (#254). Since #314 it applies to each of the two
#: selector blocks (node+way union and relation, see :func:`_build_query`), so a
#: selector brings at most ``2 * PER_SELECTOR_CAP`` candidates.
#: #212 had reduced it to 3 when the cut was "the first ones that arrive"; with
#: selection by proximity such a narrow pool would make the ordering barely
#: meaningful (3 elements per selector, chosen by Overpass, would be ordered).
#: DECLARED LIMIT: the cap is applied by Overpass with ``out center N``, which
#: prints the first N elements of the set by id (nodes before ways before
#: relations), not the closest to the centre of the area: proximity
#: (:func:`select_pois`) chooses only inside the already cut pool, and in a
#: dense zone a nearby object may be left out. Raising the cap reduces this
#: effect but does not eliminate it. It stays the same on both paths (interactive
#: and offline capture): a different cap would make production and snapshots
#: select from different pools, breaking the iso-input of #110.
PER_SELECTOR_CAP = 10

#: How many seats at most a single TERMINUS class can take within the
#: ``MAX_POIS`` (#254). Any seats left over are filled anyway with the closest
#: among the discarded, so the cap never reduces the number of POIs returned:
#: it only changes their composition.
PER_CLASS_CAP = 3

#: OSM element types queried by :func:`_build_query` (#314). Before #314 they were
#: only node and way, and monuments mapped as multipolygons (Colosseo,
#: Duomo di Milano) never entered the pool. Recorded in the provenance of the
#: snapshots: it changes the candidate pool as much as ``PER_SELECTOR_CAP``.
ELEMENT_TYPES: tuple[str, ...] = ("node", "way", "relation")

#: Maximum distance between the centres of a way and of a multipolygon relation
#: for the way to be treated as a duplicate of the relation (#371). The case
#: that motivated it, Ambiente 4 at the Palatino (way/597452722 and relation/1835450),
#: has centres ~34 m apart: the way is an area of ~8 m inside the box of
#: ~120 x 70 m of the relation, and the ``center`` of ``out center`` is the centre
#: of the box, not of the object. 50 m covers that case with margin while staying
#: on the order of a city block; the threshold alone would not be enough to avoid
#: wrong merges, and indeed it is the last of the filters after type, name and tag
#: (:func:`_discard_ways_duplicating_relations`). A way farther from the centre
#: of the box stays in the sample: an accepted false negative.
MAX_DUPLICATE_DISTANCE_M = 50.0

logger = logging.getLogger(__name__)

#: Retryable HTTP statuses: 429 (rate limit) and gateway/overload 5xx. A
#: response with these statuses is not a definitive error but a transient
#: Overpass condition -> it deserves a retry like a timeout.
_RETRYABLE_STATUS = frozenset({429, 502, 503, 504})

#: Hints of an interrupted execution in an Overpass ``remark`` (#372). The
#: ``runtime error`` prefix is the one Overpass uses for every interruption
#: of the query (timeout, memory); the two phrases cover the known forms even if
#: the prefix changed. A remark with none of these hints, if it ever
#: appeared, is defensively treated as not an interruption: it must not be
#: retried.
_TRUNCATION_HINTS: tuple[str, ...] = (
    "runtime error",
    "timed out",
    "out of memory",
)


@dataclass(frozen=True)
class RetryPolicy:
    """How hard to insist with Overpass, and how long to wait between attempts (#232).

    ``pause_s`` has one element for each RETRY, in order: its length *is* the
    number of retries, and the increasing values implement the backoff.
    Keeping them explicit instead of computing them (base * factor ** n) makes
    the policy readable in a test and in the report of a run.
    """

    #: Courtesy pauses before each retry, in seconds.
    pause_s: tuple[float, ...]
    #: Timeout of the first attempt.
    timeout_s: float
    #: Timeout of the retries (longer: a 504 under load needs room to breathe).
    retry_timeout_s: float
    #: How much waiting requested by ``Retry-After`` this policy is willing to
    #: accept. ``None`` = header IGNORED: it is the interactive case, where
    #: extending the wait because the server asks would worsen exactly the
    #: latency we want to keep low. A value = cap: beyond it we give up at once
    #: instead of retrying early, which would be hammering a free public
    #: service that has just said "later".
    retry_after_cap_s: float | None
    #: Whether a non-timeout transport blip (connection refused, connection
    #: closed mid-response, interrupted read) should be retried like a 429/5xx
    #: instead of being definitive (#247). ``False`` in interactive mode: that path
    #: must not gain latency for an error that today fails at once.
    retry_transport_errors: bool = False


#: Interactive path (``/analyze``): a user is waiting, so failing early is
#: correct. It is the pre-#232 behaviour to the letter — one retry, one second of
#: pause, ``Retry-After`` ignored — because that path must not gain latency.
#: It also holds for ``capture_city`` (#31), where wall-clock time is the
#: ``switch_ms`` metric and a longer pause would falsify it.
INTERACTIVE_RETRY = RetryPolicy(
    pause_s=(1.0,),
    timeout_s=30.0,
    retry_timeout_s=60.0,
    retry_after_cap_s=None,
)

#: Offline capture of the evaluation snapshots: here waiting is free and
#: failing means having no experiment (#232). The pauses are courtesy towards a
#: free public service — a 429 is exhausted slot quota and frees up in tens of
#: seconds — and sum to 155s; with each attempt's timeout the worst case for a
#: zone comes close to 7 minutes.
OFFLINE_RETRY = RetryPolicy(
    pause_s=(5.0, 15.0, 45.0, 90.0),
    timeout_s=30.0,
    retry_timeout_s=60.0,
    retry_after_cap_s=120.0,
    retry_transport_errors=True,
)

#: Explicit user-agent required by the public Overpass endpoint: without it
#: (httpx default ``python-httpx/...``) overpass-api.de answers 406.
_USER_AGENT = (
    "crime-risk-analyzer (https://github.com/Salvo-Rosolia/crime-risk-analyzer)"
)


class Poi(TypedDict):
    """POI in the retrieval contract (pre-grounding)."""

    #: ``"{type}/{id}"`` of the OSM element (e.g. ``"node/123"``, ``"way/123"``,
    #: ``"relation/123"`` since #314): node, way and relation live in separate
    #: namespaces, so the type is necessary to prevent two different objects
    #: from collapsing onto the same id (#265).
    #: It is the key by which risks are attributed to the POI (#255) and it enters
    #: ``context_fingerprint.fingerprint()`` — changing its format alters
    #: every ``contesto_hash`` produced from that moment on.
    #: Since #371 an id identifies an object of the sample, not each of its mappings:
    #: when a way repeats a homonymous, nearby multipolygon relation only
    #: ``"relation/…"`` comes out, and the way appears in no sample.
    id: str
    name: str
    lat: float
    lon: float
    osm_tags: str
    ontology_class: str
    citta: str


class OsmCut(TypedDict):
    """OSM DB cut declared by Overpass, and endpoint queried (#251).

    ``timestamp_osm_base`` mirrors the name of the Overpass field
    (``osm3s.timestamp_osm_base``) to stay cross-referenceable with the
    API documentation: it makes "these are the POIs of that zone at that
    instant" falsifiable against an OSM history dump. ``None`` when Overpass
    does not declare it (malformed payload or missing field) — a missing datum,
    not an error that must make the capture fail.
    """

    timestamp_osm_base: str | None
    overpass_url: str


class OverpassError(RuntimeError):
    """Overpass unreachable or invalid response (mappable to 503).

    Even a 200 response carrying an interruption remark, retried like a
    timeout until the attempts run out (#372): it costs latency, up to 2 attempts
    of ~26 s each in interactive mode, 5 in offline.
    """


def remark_signals_incomplete_response(remark: str) -> bool:
    """Whether a 200 response ``remark`` declares an interrupted execution (#372).

    True for the forms with which Overpass signals that the query stopped before
    the end, for example ``runtime error: Query timed out in "query" at line 3
    after 26 seconds.`` or ``runtime error: Query run out of memory ...``: the
    elements present are only those found up to there. False for an empty remark
    or one without interruption hints (hypothetical form, handled
    defensively). The comparison ignores
    case: the exact form is not an API contract.
    """
    text = remark.lower()
    return any(hint in text for hint in _TRUNCATION_HINTS)


def _truncation_remark(payload: object) -> str | None:
    """The payload's ``remark`` if it signals an incomplete response, or ``None``.

    A missing ``remark`` or one of unexpected type is not a declared interruption:
    the validity of the payload stays verified by :func:`_parse_elements`.
    """
    if not isinstance(payload, Mapping):
        return None
    remark = cast(Mapping[str, object], payload).get("remark")
    if isinstance(remark, str) and remark_signals_incomplete_response(remark):
        return remark
    return None


def _build_query(bbox: Bbox, osm_selectors: Sequence[str]) -> str:
    """Builds the Overpass QL query for the ``key=value`` selectors inside ``bbox``.

    Each selector ``k=v`` emits two blocks, each with its own local
    ``out center PER_SELECTOR_CAP`` (so no dense selector saturates the
    result): the node+way union, and the relations alone (#314). Bbox in the order
    ``(south, west, north, east)``.

    Relations do NOT enter the union because Overpass prints one set per type
    (node, then way, then relation): with the shared cap a dense selector like
    ``tourism=attraction`` would use up the seats with node and way before reaching
    the relations, and the Colosseo (relation/1834818) would stay out exactly as
    before. With its own ``out`` the node+way block stays identical to the
    pre-#314 one, so relations are ADDED to the pool without removing anything.
    ``out center`` also gives relations the ``center`` field, without which
    :func:`_coords` would discard them. It is NOT the centroid: it is the centre of
    the object's box (bounding box), so on an irregular shape it can
    fall outside its geometry too.

    The bbox filter on a relation selects it if at least one member falls in the
    bbox: for large relations the ``center`` can therefore lie outside the queried
    area, as already for a long way (observed in Rome: 13 relations out of 39
    at 401-598 m outside the bbox, none entered the sample). Selection by
    proximity (:func:`select_pois`) penalises them in proportion to the distance,
    without a dedicated filter.
    """
    lat_min, lon_min, lat_max, lon_max = bbox
    bbox_str = f"{lat_min},{lon_min},{lat_max},{lon_max}"
    blocks: list[str] = []
    for selector in osm_selectors:
        key, _, value = selector.partition("=")
        blocks.append(
            f'(\n  node["{key}"="{value}"]({bbox_str});\n'
            f'  way["{key}"="{value}"]({bbox_str});\n);\n'
            f"out center {PER_SELECTOR_CAP};"
        )
        blocks.append(
            f'relation["{key}"="{value}"]({bbox_str});\nout center {PER_SELECTOR_CAP};'
        )
    return "[out:json][timeout:25];\n" + "\n".join(blocks)


def _extract_osm_tag(tags: Mapping[str, object]) -> str:
    """Extracts the representative ``key=value`` selector from OSM ``tags``.

    Iterates the families in ``family_order`` of the active set (priority) and
    returns the FIRST ``key=value`` that exists in the ``osm_to_class`` binding. So a
    multi-tag POI is classified by the tag actually mapped and not by a spurious
    higher-priority tag. Returns an empty string if no known tag is present.

    Exception (#373): a selector in ``yielding_selectors`` yields to the indicated
    family if it carries a tag mapped on the same element
    (``tourism=attraction`` + ``historic=archaeological_site`` ->
    ``historic=archaeological_site``).
    """
    binding = current_osm()
    for family in binding.family_order:
        selector = _mapped_selector(tags, family)
        if selector:
            preferred_family = binding.yielding_selectors.get(selector)
            if preferred_family is not None:
                return _mapped_selector(tags, preferred_family) or selector
            return selector
    return ""


def _mapped_selector(tags: Mapping[str, object], family: str) -> str:
    """``family=value`` if ``tags`` has it and it is in the binding, else ``""``."""
    value = tags.get(family)
    if isinstance(value, str):
        selector = f"{family}={value}"
        if selector in current_osm().osm_to_class:
            return selector
    return ""


def _coords(element: Mapping[str, object]) -> tuple[float, float] | None:
    """Extracts ``(lat, lon)`` from an element, or ``None`` if unusable.

    ``node``s have direct ``lat``/``lon``; ``way`` and ``relation`` expose in
    ``center`` the centre of their box (bounding box), not the centroid
    (requested by ``out center`` in the query, #314). For a large relation that
    point may fall outside the queried bbox.
    """
    lat = element.get("lat")
    lon = element.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        center = element.get("center")
        if not isinstance(center, Mapping):
            return None
        center_map = cast(Mapping[str, object], center)
        lat = center_map.get("lat")
        lon = center_map.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    return float(lat), float(lon)


def _to_poi(element: Mapping[str, object], citta: str) -> Poi | None:
    """Converts an Overpass element into :class:`Poi`, or ``None`` if unusable.

    Discards elements without tags, without coordinates or without ``type``.
    """
    tags = element.get("tags")
    if not isinstance(tags, Mapping):
        return None
    tags_map = cast(Mapping[str, object], tags)

    coords = _coords(element)
    if coords is None:
        return None
    lat, lon = coords

    # node and way live in separate OSM namespaces: without the type, a node and a
    # way with the same number would collapse onto the same id (#265). Overpass
    # always declares it; an element lacking it must be discarded instead of
    # falling back to an empty string, which would reopen the same collision among
    # several elements equally lacking ``type``.
    element_type = element.get("type")
    if not isinstance(element_type, str) or not element_type:
        return None

    osm_tag = _extract_osm_tag(tags_map)
    return Poi(
        id=f"{element_type}/{element.get('id', '')}",
        name=str(tags_map.get("name", "")),
        lat=lat,
        lon=lon,
        osm_tags=osm_tag,
        ontology_class=current_osm().map(osm_tag),
        citta=citta,
    )


def _parse_elements(payload: object, citta: str) -> list[Poi]:
    """Maps ALL the ``elements`` of an Overpass response into POIs.

    No cut here (#254): this function produces the candidate pool, and
    which ``MAX_POIS`` come out is decided by :func:`select_pois`. Before, the cut was
    a ``break`` at ``MAX_POIS`` on the emission order, i.e. on the order in which
    the selectors were declared.

    It deduplicates twice: by ``(type, id)``, and since #371 it removes the way that
    repeats a homonymous, nearby multipolygon relation
    (:func:`_discard_ways_duplicating_relations`). The pool therefore counts objects,
    not OSM elements.
    """
    if not isinstance(payload, Mapping):
        raise OverpassError("Risposta Overpass non valida: payload non oggetto")
    payload_map = cast(Mapping[str, object], payload)
    elements = payload_map.get("elements")
    if not isinstance(elements, list):
        raise OverpassError("Risposta Overpass priva di 'elements'")
    elements_list = cast(list[object], elements)

    candidates: list[_Candidate] = []
    seen: set[tuple[str, str]] = set()
    for element in elements_list:
        if not isinstance(element, Mapping):
            continue
        element_map = cast(Mapping[str, object], element)
        # OSM identity = (type, id): the query has a block per selector and each
        # ``out`` prints its own set, so an object with several mapped tags
        # arrives once per block (verified live: the Arch of Constantine,
        # ``tourism=attraction`` + ``historic=monument``, arrives twice; since
        # #314 also the Colosseo, a relation with ``tourism=attraction`` +
        # ``historic=archaeological_site``). The ``type`` enters the key
        # because node, way and relation live in separate namespaces and the same
        # number identifies different objects (#265).
        element_key = (str(element_map.get("type", "")), str(element_map.get("id", "")))
        if element_key in seen:
            continue
        poi = _to_poi(element_map, citta)
        if poi is not None:
            seen.add(element_key)
            # ``_to_poi`` has already verified that ``tags`` is a Mapping.
            tags = cast(Mapping[str, object], element_map["tags"])
            candidates.append(_Candidate(poi, element_key[0], tags))
    return _discard_ways_duplicating_relations(candidates)


@dataclass(frozen=True)
class _Candidate:
    """A POI of the pool with the OSM type and raw tags that :class:`Poi` lacks."""

    poi: Poi
    element_type: str
    tags: Mapping[str, object]


def _duplicate_signature(tags: Mapping[str, object]) -> tuple[object, ...] | None:
    """Name and values of ALL the mapped families, or ``None`` if nameless (#371).

    Not just the representative selector (``osm_tags``): an area with an extra
    ``tourism=attraction`` is described differently, even if the TERMINUS class
    that comes out of it is the same. Tags outside the families (``inscription``,
    ``fixme``, ``website``, ``type``) do not enter: two mappings of the same
    object often have them different, but they do not say what the object is.
    """
    name = tags.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    return (name, *(tags.get(family) for family in current_osm().family_order))


def _discard_ways_duplicating_relations(candidates: list[_Candidate]) -> list[Poi]:
    """Removes the ways that repeat a multipolygon relation of the pool (#371).

    Since #314 a site mapped twice, as an area (way) and as a multipolygon
    (relation), entered the sample twice: Ambiente 4 at the Palatino took
    2 of the 20 seats and 2 of the 3 of Archaeological_site, with the same risks
    repeated and its duplicate as first neighbour in the per-POI narrative.

    Rule, deliberately narrow: a way is discarded only if the pool contains a
    relation with ``type=multipolygon``, the same non-empty name (exact equality,
    no approximate comparison), the same values on all the families
    of ``family_order`` and a centre within :data:`MAX_DUPLICATE_DISTANCE_M`.
    Nodes are never merged (two "Termini" stops are two stops), nor are two
    elements of the same type, nor elements without a name.

    The relation survives: it is the complete object, the one #314 brought
    into the pool to represent multi-part sites, and its id does not depend on
    which way arrives first. The choice does not depend on the emission order.
    It must be done before :func:`select_pois`, so the freed seat (also in the
    per-class cap) goes to the next candidate.
    """
    multipolygons = [
        (c.poi, signature)
        for c in candidates
        if c.element_type == "relation"
        and c.tags.get("type") == "multipolygon"
        and (signature := _duplicate_signature(c.tags)) is not None
    ]
    pois: list[Poi] = []
    for c in candidates:
        signature = _duplicate_signature(c.tags) if c.element_type == "way" else None
        duplicate_of = next(
            (
                rel["id"]
                for rel, rel_signature in multipolygons
                if signature is not None
                and rel_signature == signature
                and haversine_m(c.poi["lat"], c.poi["lon"], rel["lat"], rel["lon"])
                <= MAX_DUPLICATE_DISTANCE_M
            ),
            None,
        )
        if duplicate_of is not None:
            logger.debug("POI %s discarded: duplicate of %s", c.poi["id"], duplicate_of)
            continue
        pois.append(c.poi)
    return pois


def _osm_cut(payload: object, overpass_url: str) -> OsmCut:
    """Extracts the OSM DB cut from the Overpass payload, best-effort (#251).

    ``payload`` is not guaranteed to have ``osm3s``/``timestamp_osm_base`` in the
    expected form: here it is read defensively and ``None`` is returned for that
    field instead of raising, because the cut is an enrichment of the
    provenance, not a condition for considering the response valid (that
    check is already done by :func:`_parse_elements`).
    """
    timestamp: str | None = None
    if isinstance(payload, Mapping):
        osm3s = cast(Mapping[str, object], payload).get("osm3s")
        if isinstance(osm3s, Mapping):
            value = cast(Mapping[str, object], osm3s).get("timestamp_osm_base")
            if isinstance(value, str):
                timestamp = value
    return OsmCut(timestamp_osm_base=timestamp, overpass_url=overpass_url)


def select_pois(
    pois: list[Poi],
    center: tuple[float, float],
    *,
    max_pois: int = MAX_POIS,
    per_class_cap: int = PER_CLASS_CAP,
) -> list[Poi]:
    """The ``max_pois`` POIs to return, chosen by proximity to ``center`` (#254).

    Before #254 the cut took the first ``MAX_POIS`` in the order in which
    Overpass emitted them, i.e. in the order of declaration of the selectors: in a
    dense zone the first selectors used up the seats and the tag families at the
    tail never appeared. On the 4 snapshots captured before this change the
    effect is visible: only ``amenity=*`` POIs, no museum, monument or station.

    Declared ordering: increasing distance and, at equal distance, increasing ``id``
    as a STRING. It is needed because the context enters the prompt and
    ``repro.prompt_hash`` must stay stable for the same input. It is not a
    strictly total ordering: two OSM objects at the same coordinates would
    tie on both components and the tie would fall back on the stability of
    ``sorted``, i.e. on Overpass's emission order. The case is not reachable
    for two independent reasons: ``_parse_elements`` deduplicates by
    ``(type, id)``, and the POI ``id`` carries the element type
    (``"node/123"`` vs ``"way/123"``), so a node and a way with the same
    number no longer share the same string (#265).

    Two passes over the same ordered list. In the first a POI enters only if its
    TERMINUS class does not already have ``per_class_cap`` seats: without this cap, in
    the city centre the closest POIs are often all of the same class (eight
    ATMs within 150 m) and the zone would be described on a homogeneous sample.
    The second pass fills any remaining seats with the closest discarded:
    without it a zone of only banks would return ``per_class_cap``
    points instead of ``max_pois``, i.e. fewer than before.
    """
    lat, lon = center
    ordered = sorted(
        pois,
        key=lambda poi: (haversine_m(lat, lon, poi["lat"], poi["lon"]), poi["id"]),
    )
    chosen: list[Poi] = []
    discarded: list[Poi] = []
    per_class: dict[str, int] = {}
    for poi in ordered:
        if len(chosen) >= max_pois:
            break
        ontology_class_name = poi["ontology_class"]
        if per_class.get(ontology_class_name, 0) >= per_class_cap:
            discarded.append(poi)
            continue
        per_class[ontology_class_name] = per_class.get(ontology_class_name, 0) + 1
        chosen.append(poi)
    if len(chosen) < max_pois:
        chosen.extend(discarded[: max_pois - len(chosen)])
        # The discarded are farther than the chosen in the first pass, but not
        # necessarily at the tail: we re-sort to keep the invariant "the list
        # comes out in order of distance" (the numbering on the map mirrors it).
        chosen.sort(
            key=lambda poi: (haversine_m(lat, lon, poi["lat"], poi["lon"]), poi["id"])
        )
    return chosen


#: Non-timeout transport blips treated as transient when the policy allows it
#: (#247): the whole ``NetworkError`` family (connection refused,
#: interrupted read or write, abnormal close) plus ``RemoteProtocolError``
#: (connection closed mid-response). Overpass under load closes
#: connections at least as often as it returns 504 -> same treatment, no longer a
#: definitive failure.
_RETRYABLE_TRANSPORT_ERRORS: tuple[type[httpx.HTTPError], ...] = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.CloseError,
    httpx.RemoteProtocolError,
)


@dataclass(frozen=True)
class _Outcome:
    """Outcome of an attempt towards Overpass (#372).

    ``payload`` is meaningful only for a 2xx response; ``remark`` is not
    ``None`` when Overpass truncated the execution, and in that case the payload
    must not be used.
    """

    response: httpx.Response | None
    payload: object = None
    transport_reason: str | None = None
    remark: str | None = None

    @property
    def should_retry(self) -> bool:
        """No response, transient status (429/5xx) or truncated 200."""
        return (
            self.response is None
            or self.remark is not None
            or self.response.status_code in _RETRYABLE_STATUS
        )

    @property
    def reason(self) -> str:
        """Why the attempt did not go through, for the log and for the error."""
        if self.remark is not None:
            return f"ha dato una risposta incompleta ({self.remark})"
        if self.response is None:
            return self.transport_reason or "nessuna risposta"
        return f"ha risposto {self.response.status_code}"


async def _attempt(
    client: httpx.AsyncClient,
    url: str,
    query: str,
    timeout: float,
    *,
    retry_transport_errors: bool,
) -> _Outcome:
    """A complete attempt: POST, JSON decoding of a 2xx, ``remark`` check.

    A 2xx that is not JSON remains a definitive error, as before #372.
    """
    response, reason = await _try_post(
        client, url, query, timeout, retry_transport_errors=retry_transport_errors
    )
    if response is None or not response.is_success:
        return _Outcome(response, transport_reason=reason)
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise OverpassError("Risposta Overpass non e' JSON valido") from exc
    return _Outcome(response, payload=payload, remark=_truncation_remark(payload))


async def _try_post(
    client: httpx.AsyncClient,
    url: str,
    query: str,
    timeout: float,
    *,
    retry_transport_errors: bool,
) -> tuple[httpx.Response | None, str | None]:
    """Performs a POST attempt to Overpass with the indicated timeout.

    Returns ``(response, reason)``: ``response`` is ``None`` when the attempt
    must be retried and ``reason`` describes why, for the caller's log. A
    non-timeout transport error (:data:`_RETRYABLE_TRANSPORT_ERRORS`) is
    retryable ONLY if ``retry_transport_errors`` (offline policy, #247):
    otherwise it stays definitive as before, rethrown at once as
    :class:`OverpassError` — the interactive path must not gain
    latency for a blip that today fails at once.
    """
    try:
        return await client.post(url, content=query, timeout=timeout), None
    except httpx.TimeoutException:
        return None, "timeout"
    except _RETRYABLE_TRANSPORT_ERRORS as exc:
        if retry_transport_errors:
            return None, f"errore di trasporto ({exc})"
        raise OverpassError(f"Errore di rete verso Overpass: {exc}") from exc
    except httpx.HTTPError as exc:
        raise OverpassError(f"Errore di rete verso Overpass: {exc}") from exc


def _retry_after_s(response: httpx.Response | None) -> float | None:
    """The seconds indicated by ``Retry-After``, if readable as an integer (#232).

    Only the seconds form: the HTTP-date form exists in the standard but Overpass
    does not use it, and interpreting it would require date parsing for nothing.
    ``None`` = header missing or unreadable -> the planned pause applies.
    """
    if response is None:
        return None
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(float(int(raw.strip())), 0.0)
    except ValueError:
        return None


def _wait_before_retry(
    response: httpx.Response | None, planned: float, cap: float | None
) -> float:
    """How long to wait before the next attempt, or give up.

    Never less than the pause planned by the policy: towards a free public
    service courtesy is a minimum, not a maximum — so a shorter ``Retry-After``
    does not shorten it. The cap does NOT touch the planned pause (which the
    policy declared on purpose) but only the server's request.

    Raises :class:`OverpassError` if the server asks for more than the cap: retrying
    earlier would be hammering someone who has just said "later", and would burn
    the remaining retries on attempts with zero probability. Better to stop
    saying when to retry.
    """
    if cap is None:
        return planned
    requested = _retry_after_s(response)
    if requested is None:
        return planned
    if requested > cap:
        raise OverpassError(
            f"Overpass ha chiesto di ritentare fra {requested:.0f}s, oltre il "
            f"tetto di {cap:.0f}s di questa politica: riprova piu' tardi"
        )
    return max(planned, requested)


async def fetch_pois(
    bbox: Bbox,
    citta: str,
    osm_selectors: Iterable[str] | None = None,
    *,
    overpass_url: str = DEFAULT_OVERPASS_URL,
    retry: RetryPolicy | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[Poi]:
    """Fetches the POIs inside ``bbox`` for the OSM selectors ``osm_selectors``.

    Default: the whole OSM binding of the active set (``None``). Enriches each POI
    with ``ontology_class`` (#13). Retries if an attempt times out **or**
    answers with a retryable status (:data:`_RETRYABLE_STATUS`, 429/5xx),
    according to ``retry``; once the policy is exhausted, :class:`OverpassError`. A
    200 response carrying an interruption remark is retried like a
    timeout and, once the attempts are exhausted, raises
    :class:`OverpassError` (503): it costs latency, up to 2 attempts of ~26 s
    each in interactive mode, 5 in offline.

    ``retry`` is resolved to :data:`INTERACTIVE_RETRY` when ``None``: the resolution
    happens at CALL time and not as a signature default, so a test can
    replace the default policy without rewriting every caller. The offline
    capture passes :data:`OFFLINE_RETRY` (#232), which also retries a transport
    blip (:data:`_RETRYABLE_TRANSPORT_ERRORS`) like a 504 (#247); the
    interactive path instead treats it as definitive, fail-fast. ``sleep``
    is injectable: the tests verify the pauses without waiting for them.

    Core shared with :func:`fetch_pois_with_cut` (#251) via
    :func:`_fetch_payload`: here the OSM DB cut is NOT computed, not just not
    returned — the interactive path must not even pay for its extraction
    (isinstance + TypedDict construction) for a datum it would discard at once.
    """
    payload = await _fetch_payload(
        bbox,
        citta,
        osm_selectors,
        overpass_url=overpass_url,
        retry=retry,
        sleep=sleep,
    )
    return select_pois(_parse_elements(payload, citta), bbox.center())


async def fetch_pois_with_cut(
    bbox: Bbox,
    citta: str,
    osm_selectors: Iterable[str] | None = None,
    *,
    overpass_url: str = DEFAULT_OVERPASS_URL,
    retry: RetryPolicy | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[list[Poi], OsmCut]:
    """Like :func:`fetch_pois`, but also returns the OSM DB cut (#251).

    Used by the offline capture to make the provenance of a snapshot
    falsifiable: "these are the POIs of that zone at that instant" is
    verifiable against an OSM history dump only if the cut declared by
    Overpass is recorded too, not just the clock of whoever asked.

    A 200 response carrying an interruption remark is retried like a
    timeout and, once the attempts are exhausted, raises
    :class:`OverpassError` (503): with :data:`OFFLINE_RETRY` that is 5 attempts of
    ~26 s each, plus the pauses.
    """
    payload = await _fetch_payload(
        bbox,
        citta,
        osm_selectors,
        overpass_url=overpass_url,
        retry=retry,
        sleep=sleep,
    )
    # The candidate pool arrives complete; the choice of the MAX_POIS that come out is
    # by proximity to the centre of the queried area, with per-class cap (#254).
    pois = select_pois(_parse_elements(payload, citta), bbox.center())
    return pois, _osm_cut(payload, overpass_url)


async def _fetch_payload(
    bbox: Bbox,
    citta: str,
    osm_selectors: Iterable[str] | None,
    *,
    overpass_url: str,
    retry: RetryPolicy | None,
    sleep: Callable[[float], Awaitable[None]],
) -> object:
    """Queries Overpass with retries and returns the raw JSON payload (#251).

    Core shared by :func:`fetch_pois` and :func:`fetch_pois_with_cut`: neither
    duplicates the retry loop, and neither pays a cost it does not need
    (``fetch_pois`` never touches the payload for the OSM cut,
    ``fetch_pois_with_cut`` does not touch it twice).

    A 200 with an interruption ``remark`` (#372) is retried like a timeout and,
    once the policy is exhausted, raises :class:`OverpassError`: the truncated
    payload never leaves here.
    """
    policy = retry or INTERACTIVE_RETRY
    selectors = list(
        current_osm().selectors if osm_selectors is None else osm_selectors
    )
    query = _build_query(bbox, selectors)

    async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}) as client:
        outcome = await _attempt(
            client,
            overpass_url,
            query,
            policy.timeout_s,
            retry_transport_errors=policy.retry_transport_errors,
        )
        # One retry for each declared pause: it fires on no response
        # (timeout or, offline, a transport blip), on a transient
        # status (429/5xx) and on a 200 truncated by Overpass (#372). A
        # non-retryable non-2xx status (400/403/404) leaves the loop at once and
        # fails below, without waiting.
        for attempt_no, planned in enumerate(policy.pause_s, start=1):
            if not outcome.should_retry:
                break
            wait_s = _wait_before_retry(
                outcome.response, planned, policy.retry_after_cap_s
            )
            # Log on every retry (#232): with the offline policy the overall
            # wait reaches minutes, and without a trace "hung process" and
            # "courtesy backoff in progress" are indistinguishable — the condition
            # that on 26/07 drove writing the backoff by hand in a shell.
            logger.warning(
                "Overpass %s: retry %d/%d in %.0fs",
                outcome.reason,
                attempt_no,
                len(policy.pause_s),
                wait_s,
            )
            await sleep(wait_s)
            outcome = await _attempt(
                client,
                overpass_url,
                query,
                policy.retry_timeout_s,
                retry_transport_errors=policy.retry_transport_errors,
            )

    if outcome.remark is not None:
        # With a final remark the loop never stopped earlier: the attempts
        # were all those of the policy. The remark states the reason itself
        # (timeout, memory, other): here it is not requalified.
        attempts = 1 + len(policy.pause_s)
        after = f" dopo {attempts} tentativi" if attempts > 1 else ""
        raise OverpassError(f"Risposta incompleta di Overpass{after}: {outcome.remark}")
    if outcome.response is None:
        raise OverpassError(
            f"Overpass irraggiungibile dopo i ritentativi: {outcome.reason}"
        )
    if not outcome.response.is_success:
        raise OverpassError(f"Overpass ha risposto {outcome.response.status_code}")
    return outcome.payload
