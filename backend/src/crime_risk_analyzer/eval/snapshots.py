"""Capture-and-replay of the POI inputs for reproducibility (#34).

Every snapshot carries its own PROVENANCE (#241): provenance existed for the
runs (``RunRecord.provenance``) but not for the fixtures that feed them, and the
fixtures are the root of the reproducibility chain. OpenStreetMap is a
live source: in six months the same query will return different POIs, so without
a capture instant "these are the POIs of that zone" is not verifiable.

The on-file format is an envelope ``{"formato": 2, "provenienza": ..., "poi": [...]}``,
but ``load_snapshot`` also reads the bare list of the files captured before #241: the
4 snapshots committed with #231 must stay replayable, otherwise the
already published iso-input comparison would break.

**Those 4 files have no provenance and none has been fabricated**: inventing
the capture instant would have been a false record. The only time reference
available for them is the date of the commit that introduced them (#231, 26/07/2026);
they will get a real one at the next capture, which however would change the
fixtures and hence the
comparability of the already published results -- so it is a decision for the author,
not a side effect.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import NotRequired, TypedDict, cast

from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.overpass_client import (
    ELEMENT_TYPES,
    MAX_POIS,
    OFFLINE_RETRY,
    PER_CLASS_CAP,
    PER_SELECTOR_CAP,
    OsmCut,
    Poi,
    fetch_pois_with_cut,
)
from crime_risk_analyzer.rag.retrieval import GeoSource, PoiSource
from crime_risk_analyzer.sparql_module.osm_mapping import OSM_SELECTORS


class CanonicalConfig(TypedDict):
    """Constants of the code that WROTE the file, not of the query that produced it.

    The distinction is not pedantry: ``capturing_source`` accepts an arbitrary
    ``inner`` and ``fetch_pois`` accepts custom ``osm_selectors``, so from here
    one cannot know what was really queried. Recording these
    constants is useful -- together with the commit, they say with which binding and
    which caps the code was working -- but the name must say what they are, because a
    provenance that claims more than it knows is worse than one that stays silent.
    """

    selettori_hash: str
    n_selettori: int
    #: #212 changed them (50->20, 5->3): two indistinguishable fixtures can
    #: derive from queries with different caps.
    max_pois: int
    per_selector_cap: int
    #: Per-TERMINUS-class cap of the selection (#254). It is part of what
    #: produced the file as much as the query caps: its absence identifies a
    #: snapshot captured before the proximity selection.
    per_class_cap: int
    #: OSM element types queried (#314): with relations the pool of
    #: candidates widens and the sample of a zone may change (the Colosseum
    #: enters at Rome). Its absence identifies a snapshot captured with the
    #: node+way query only. List, not tuple: it must equal the value re-read
    #: from JSON in the comparison of :func:`describe_config_mismatch`.
    tipi_elemento: list[str]


class SnapshotProvenance(TypedDict):
    """Where a POI fixture comes from: instant, area, zone, configuration."""

    #: Capture instant, ISO-8601 with explicit offset (UTC). It is the clock of the
    #: process that asked for the data: it says "when I asked", not "which state
    #: of OSM I obtained" -- for that see :attr:`taglio_osm` (#251).
    catturato_il: str
    #: Bbox queried, ``[min_lat, min_lon, max_lat, max_lon]``.
    bbox: list[float]
    citta: str
    #: ``None`` only if the caller did not declare it: the file-name slug is
    #: lossy, so without this field the zone<->bbox link is not verifiable.
    zona: str | None
    #: Cut of the OSM DB declared by Overpass and URL queried (#251).
    #: ``NotRequired`` because an envelope-format snapshot written between #241 and
    #: #251 on disk does not have this key at all (not ``None``: ABSENT) -- reading it
    #: by subscript on such an old file would raise ``KeyError``, it must be read with
    #: ``.get("taglio_osm")``. ``None`` when the key is there but the caller of
    #: :func:`capturing_source` did not know the cut (a test double) -- a
    #: missing datum honestly declared, not a fabricated placeholder.
    #:
    #: Reuse of an existing snapshot (``_snapshot_reusable``, #148) NEVER forces
    #: a re-capture just to populate this field, not even when it is missing
    #: altogether: the acceptance criterion of #251 asks that existing snapshots
    #: stay "readable and replayable", not that they be updated. An operator
    #: who wants the cut also for already captured zones must re-capture with
    #: ``--force``, the same route already required for any other update
    #: of the canonical configuration.
    taglio_osm: NotRequired[OsmCut | None]
    configurazione_canonica: CanonicalConfig


class SnapshotFile(TypedDict):
    """On-file format of a POI fixture (#241)."""

    #: Format version: lets an older reader fail saying so, instead of
    #: iterating the keys of a dictionary believing them to be POIs.
    formato: int
    provenienza: SnapshotProvenance
    poi: list[Poi]


#: Current on-file format version (1 = bare list pre-#241, implicit).
SNAPSHOT_FORMAT = 2


def _selectors_hash() -> str:
    """Stable fingerprint of the canonical set of OSM selectors."""
    canonical = "\n".join(sorted(OSM_SELECTORS))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _current_canonical_config() -> CanonicalConfig:
    """Canonical configuration of the CURRENT code (#267).

    Single source of truth shared by ``save_snapshot`` (what to write) and by
    :func:`describe_config_mismatch` (what to compare against): keeping them
    derived from the same place prevents writing and checking from diverging.
    """
    return {
        "selettori_hash": _selectors_hash(),
        "n_selettori": len(OSM_SELECTORS),
        "max_pois": MAX_POIS,
        "per_selector_cap": PER_SELECTOR_CAP,
        "per_class_cap": PER_CLASS_CAP,
        "tipi_elemento": list(ELEMENT_TYPES),
    }


def snapshot_path(results_dir: Path, key: str) -> Path:
    """Path of the POI fixture for a snapshot key (#110).

    ``key`` is produced by ``harness.make_snapshot_key(citta, zona)`` and does NOT
    depend on mode/model: the comparative arms (analyze/claude, analyze/groq,
    baseline) on the same (citta, zona) share the same snapshot file.
    """
    return results_dir / "snapshots" / f"{key}.json"


def save_snapshot(
    path: Path,
    pois: list[Poi],
    *,
    bbox: Bbox,
    citta: str,
    zona: str | None = None,
    cut: OsmCut | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Serialize the POIs and their provenance to file (creates the folders).

    ``bbox`` and ``citta`` are REQUIRED: a provenance that omits the area
    queried is of no use to anyone, and making them optional allowed writing
    a record with ``"bbox": null``. ``clock`` is injectable for tests -- a
    callable and not a string, so the instant cannot be fabricated by hand:
    it is the field on which the honesty of the artefact rests. ``cut``, if known,
    is the
    cut of the OSM DB declared by Overpass (#251); ``None`` when the
    caller does not know it (a test double) stays a declared missing
    datum, not an error.

    Writes with ``newline=""`` (no translation): on Windows the default
    produced CRLF in the working tree against the LF blob in git, and with
    ``core.autocrlf=false`` the fixtures showed up modified after every capture
    while being identical in content (#241, same class as #103).
    """
    content: SnapshotFile = {
        "formato": SNAPSHOT_FORMAT,
        "provenienza": {
            "catturato_il": clock().isoformat(),
            "bbox": [bbox.min_lat, bbox.min_lon, bbox.max_lat, bbox.max_lon],
            "citta": citta,
            "zona": zona,
            "taglio_osm": cut,
            "configurazione_canonica": _current_canonical_config(),
        },
        "poi": list(pois),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(content, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )


def load_snapshot(path: Path) -> list[Poi]:
    """Load the POIs from a saved fixture, with or without provenance (#241).

    Accepts two forms: the envelope ``{"provenienza": ..., "poi": [...]}`` written
    by :func:`save_snapshot`, and the bare list of the files captured before #241 --
    the 4 snapshots committed with #231, which must stay replayable.

    Raises :class:`ValueError` on any other form: a valid JSON snapshot
    that is not recognisable must not be silently replayed as an empty list. The
    caller (``_snapshot_reusable``, #148) treats it as a snapshot to
    re-capture.
    """
    data: object = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return cast(list[Poi], data)
    if isinstance(data, dict):
        pois = cast(dict[str, object], data).get("poi")
        if isinstance(pois, list):
            return cast(list[Poi], pois)
    raise ValueError(f"snapshot in un formato non riconosciuto: {path}")


def snapshot_provenance(path: Path) -> SnapshotProvenance | None:
    """Provenance declared by the snapshot, if present (#241, #267).

    ``None`` for the bare pre-#241 list (no provenance to read), for a
    missing/unreadable file, or if it is not in the expected envelope format. It
    NEVER raises: a missing or corrupt file will in any case be caught by
    ``load_snapshot`` when the run actually consumes it (error isolation of the
    caller, #252) -- here only "provenance known or not" matters, not
    duplicating that diagnosis.
    """
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict):
        prov = cast(dict[str, object], data).get("provenienza")
        if isinstance(prov, dict):
            return cast(SnapshotProvenance, prov)
    return None


def describe_config_mismatch(
    provenance: SnapshotProvenance | None,
) -> str | None:
    """Warning message if the provenance is missing or diverges from the current config.

    ``None`` = consistent, no warning to give (#267). It does not raise: the 4
    pre-#241 snapshots stay replayable (#231), but no longer silently -- the
    caller logs the warning instead of treating them as indistinguishable from a
    snapshot captured with the current configuration.
    """
    if provenance is None:
        return "nessuna provenienza leggibile (pre-#241, non apribile o corrotta)"
    return describe_config_divergence(provenance.get("configurazione_canonica"))


def current_canonical_config() -> CanonicalConfig:
    """Public accessor of the canonical configuration of the CURRENT code (#374).

    For whoever (the C1 outcomes) must record the same configuration that
    ``save_snapshot`` writes, without importing a private name.
    """
    return _current_canonical_config()


def describe_config_divergence(declared: object) -> str | None:
    """Warning message if the declared configuration diverges from the current one.

    Core of :func:`describe_config_mismatch`, exposed because the C1
    outcomes (#374) too carry a ``configurazione_canonica`` but not the full
    envelope of a POI snapshot. ``None`` = consistent.
    """
    # The configuration is cast from external JSON (#241): at runtime the key may
    # be missing or have a different shape -- the check is for real data, not for the
    # static checker.
    if not isinstance(declared, dict):
        return "provenienza senza configurazione_canonica"
    declared = cast(dict[str, object], declared)
    current = _current_canonical_config()
    diverging = sorted(k for k in current if declared.get(k) != current[k])
    if not diverging:
        return None
    details = ", ".join(
        f"{k} registrato={declared.get(k)!r} corrente={current[k]!r}" for k in diverging
    )
    return f"configurazione diversa da quella corrente ({details})"


def replay_source(path: Path) -> PoiSource:
    """PoiSource that replays from the fixture (offline, ignores bbox/citta)."""

    async def _source(bbox: Bbox, citta: str) -> list[Poi]:
        return load_snapshot(path)

    return _source


#: Source for :func:`capturing_source`: also returns the OSM DB cut
#: of the invocation (#251), read and written in the SAME call -- unlike
#: ``PoiSource``, there is nothing to remember between one call and the next, so
#: no sequentiality constraint: safe even if ``_capture`` became
#: concurrent per case in the future. ``None`` for whoever does not know the cut (a
#: test double, adapted by ``eval.__main__._without_cut``).
PoiSourceWithCut = Callable[[Bbox, str], Awaitable[tuple[list[Poi], OsmCut | None]]]


async def offline_fetch_pois(bbox: Bbox, citta: str) -> tuple[list[Poi], OsmCut]:
    """Live capture source: long courtesy backoff (#232) and cut of the
    OSM DB of the invocation (#251).

    It lives here, next to :func:`capturing_source`, and not in the CLI: the
    retry policy of the capture is a property of the capture, and as the default
    of the helper it keeps a caller from absentmindedly getting the
    interactive one, which on 26/07 gave up on the second attempt (504 then 429)
    forcing a hand-written backoff outside the code -- i.e. a
    non-reproducible run.
    """
    return await fetch_pois_with_cut(bbox, citta, retry=OFFLINE_RETRY)


def capturing_source(
    path: Path,
    inner: PoiSourceWithCut = offline_fetch_pois,
    *,
    zona: str | None = None,
) -> PoiSource:
    """PoiSource that calls ``inner`` (real Overpass) and saves the snapshot.

    The ``bbox`` received ends up in the provenance (#241): it is the area actually
    queried, not one reconstructed afterwards. ``zona`` cannot be derived from the
    bbox nor from the POIs (the file-name slug is lossy), so it must be passed by the
    caller for the zone<->bbox link to stay verifiable from the file.

    ``inner`` also returns the OSM DB cut (#251), which ends up in the
    snapshot's provenance in the SAME call in which it was observed:
    no intermediate state to keep synchronized between calls.
    """

    async def _source(bbox: Bbox, citta: str) -> list[Poi]:
        pois, osm_cut = await inner(bbox, citta)
        save_snapshot(path, pois, bbox=bbox, citta=citta, zona=zona, cut=osm_cut)
        return pois

    return _source


#: Deterministic placeholder for the geo in the run phase. The geo is NOT consumed
#: downstream (grounding/generation/metrics ignore it; replay_source ignores the bbox),
#: so a fixed value makes the run HERMETIC (zero Nominatim) without altering any
#: output. See #169 / cross-cutting review #115 (finding A1).
_PLACEHOLDER_GEO: GeoResult = {"lat": 0.0, "lon": 0.0, "bbox": Bbox(0.0, 0.0, 0.0, 0.0)}


def offline_geo_source() -> GeoSource:
    """Deterministic placeholder GeoSource: zero Nominatim, zero I/O (#169)."""

    async def _source(citta: str, zona: str) -> GeoResult:
        return _PLACEHOLDER_GEO

    return _source
