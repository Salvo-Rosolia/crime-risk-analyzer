import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crime_risk_analyzer.eval import snapshots
from crime_risk_analyzer.eval.snapshots import (
    SNAPSHOT_FORMAT,
    capturing_source,
    describe_config_mismatch,
    load_snapshot,
    offline_fetch_pois,
    offline_geo_source,
    replay_source,
    save_snapshot,
    snapshot_provenance,
)
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.overpass_client import (
    MAX_POIS,
    OFFLINE_RETRY,
    PER_CLASS_CAP,
    PER_SELECTOR_CAP,
    OsmCut,
)

_POIS = [
    {
        "id": "1",
        "name": "Banca A",
        "lat": 41.0,
        "lon": 12.0,
        "osm_tags": "amenity=bank",
        "terminus_class": "Bank",
        "citta": "Roma",
    }
]

_BBOX = Bbox(41.0, 12.0, 41.1, 12.1)


def test_save_load_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS, bbox=_BBOX, citta="Roma")  # type: ignore[arg-type]
    assert load_snapshot(p)[0]["name"] == "Banca A"


async def test_replay_source_returns_saved_pois(tmp_path: Path) -> None:
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS, bbox=_BBOX, citta="Roma")  # type: ignore[arg-type]
    source = replay_source(p)
    out = await source(Bbox(41.0, 12.0, 41.1, 12.1), "Roma")
    assert out[0]["name"] == "Banca A"


async def test_capturing_source_writes_and_passes_through(tmp_path: Path) -> None:
    p = tmp_path / "snap.json"

    async def inner(bbox: object, citta: str):
        return _POIS, None

    source = capturing_source(p, inner=inner)  # type: ignore[arg-type]
    out = await source(Bbox(41.0, 12.0, 41.1, 12.1), "Roma")
    assert out[0]["name"] == "Banca A"
    assert load_snapshot(p)[0]["name"] == "Banca A"  # it was written


async def test_offline_geo_source_returns_deterministic_placeholder() -> None:
    src = offline_geo_source()
    a = await src("Roma", "Colosseo")
    b = await src("Milano", "Duomo")
    # deterministic and independent of the arguments
    assert a == b
    assert isinstance(a["bbox"], Bbox)
    assert a == {"lat": 0.0, "lon": 0.0, "bbox": Bbox(0.0, 0.0, 0.0, 0.0)}


# --- #241: fixture provenance and explicit newlines ---
# Snapshots are the ROOT of the reproducibility chain: provenance
# existed for the runs (RunRecord.provenance) but not for the fixtures that
# feed them. OpenStreetMap is a live source: without a capture instant,
# "these are the POIs of that zone" is not a verifiable statement.


def test_snapshot_carries_the_capture_provenance(tmp_path: Path) -> None:
    p = tmp_path / "snap.json"
    save_snapshot(
        p,
        _POIS,  # type: ignore[arg-type]
        bbox=_BBOX,
        citta="Roma",
        zona="Colosseo",
        clock=lambda: datetime(2026, 7, 26, 18, 40, tzinfo=UTC),
    )

    written = json.loads(p.read_text(encoding="utf-8"))
    assert written["formato"] == SNAPSHOT_FORMAT
    prov = written["provenienza"]
    assert prov["catturato_il"] == "2026-07-26T18:40:00+00:00"
    assert prov["bbox"] == [41.0, 12.0, 41.1, 12.1]
    assert prov["citta"] == "Roma"
    # The zone cannot be derived from the file: the name slug is lossy, so without
    # this field the zone<->bbox link would not be verifiable.
    assert prov["zona"] == "Colosseo"
    # Constants of the code that WROTE the file: the name declares it, because from
    # here one cannot know what an arbitrary ``inner`` queried.
    conf = prov["configurazione_canonica"]
    assert conf["max_pois"] == MAX_POIS
    assert conf["per_selector_cap"] == PER_SELECTOR_CAP
    # #254: the selection policy is part of what produced the file. Without
    # this field two indistinguishable fixtures could come from different per-class
    # caps, and a pre-#254 snapshot would not be recognisable as such.
    assert conf["per_class_cap"] == PER_CLASS_CAP
    assert conf["n_selettori"] > 0
    assert len(conf["selettori_hash"]) == 64


def test_real_capture_instant_when_not_injected(tmp_path: Path) -> None:
    """Without an injected clock the instant is the real one, in UTC with explicit
    offset."""
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS, bbox=_BBOX, citta="Roma")  # type: ignore[arg-type]

    captured_at = json.loads(p.read_text(encoding="utf-8"))["provenienza"][
        "catturato_il"
    ]
    assert captured_at.endswith("+00:00")
    assert captured_at[:2] == "20"


def test_legacy_snapshot_without_provenance_stays_readable(tmp_path: Path) -> None:
    """The 4 snapshots committed with #231 are bare lists: they must stay
    replayable, otherwise the already published iso-input comparison breaks."""
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps(_POIS), encoding="utf-8")

    assert load_snapshot(p)[0]["name"] == "Banca A"


def test_committed_snapshots_stay_readable() -> None:
    """Guard on the real files, not on an imitation of them: the fixtures in
    ``results/snapshots/`` are the root of the reproducibility chain."""
    cartella = Path(__file__).parents[2] / "results" / "snapshots"
    file = sorted(cartella.glob("*.json"))
    assert file, "attese le fixture POI versionate in results/snapshots/"
    for f in file:
        pois = load_snapshot(f)
        assert isinstance(pois, list)
        assert pois, f"snapshot vuoto: {f.name}"
        assert "terminus_class" in pois[0]


def test_write_without_line_ending_churn(tmp_path: Path) -> None:
    """No CRLF: on Windows the working tree diverged from the blob in git, and with
    ``core.autocrlf=false`` the 4 files showed up modified after every capture while
    being identical in content (same class of defect closed in #103).

    Honesty about the scope: this guard has teeth only on Windows. In CI
    (``ubuntu-latest``) ``write_text`` produces LF even without ``newline=""``,
    so the test is green by construction and a removal of that parameter would
    not be caught by the pipeline.
    """
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS, bbox=_BBOX, citta="Roma")  # type: ignore[arg-type]

    assert b"\r\n" not in p.read_bytes()


# --- #267: knowing the provenance is no longer enough, it must also be VERIFIED ---
# A parseable file is not the same as one captured with the current selection
# policy: without an explicit comparison, two experiments on the same
# (citta, zona) can silently mix two configurations.


def test_snapshot_provenance_reads_the_envelope(tmp_path: Path) -> None:
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS, bbox=_BBOX, citta="Roma", zona="Colosseo")  # type: ignore[arg-type]

    prov = snapshot_provenance(p)
    assert prov is not None
    assert prov["citta"] == "Roma"
    assert prov["configurazione_canonica"]["max_pois"] == MAX_POIS


def test_snapshot_provenance_none_for_missing_file(tmp_path: Path) -> None:
    """A missing file must not blow up the check: the real consumer catches it
    (``load_snapshot`` inside ``replay_source``), not this probe."""
    assert snapshot_provenance(tmp_path / "non-esiste.json") is None


def test_snapshot_provenance_none_for_legacy_bare_list(tmp_path: Path) -> None:
    """The pre-#241 snapshots are bare lists: no provenance to read."""
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps(_POIS), encoding="utf-8")

    assert snapshot_provenance(p) is None


def test_mismatch_none_when_configuration_is_the_current_one(
    tmp_path: Path,
) -> None:
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS, bbox=_BBOX, citta="Roma")  # type: ignore[arg-type]

    assert describe_config_mismatch(snapshot_provenance(p)) is None


def test_mismatch_reports_missing_provenance() -> None:
    """#267: the pre-#241 bare list gets an explicit warning, not silence."""
    msg = describe_config_mismatch(None)
    assert msg is not None
    assert "nessuna provenienza" in msg


def test_mismatch_reports_diverging_configuration(tmp_path: Path) -> None:
    """A fixture captured with a ``per_class_cap`` different from the current one
    (e.g. pre-#254) must not be indistinguishable from a consistent one."""
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS, bbox=_BBOX, citta="Roma")  # type: ignore[arg-type]
    prov = snapshot_provenance(p)
    assert prov is not None
    prov["configurazione_canonica"]["per_class_cap"] = PER_CLASS_CAP + 100

    msg = describe_config_mismatch(prov)
    assert msg is not None
    assert "per_class_cap" in msg
    assert str(PER_CLASS_CAP + 100) in msg


def test_provenance_records_the_queried_element_types(tmp_path: Path) -> None:
    """#314: the OSM types queried are part of what produced the file.

    With relations the pool of candidates widens and the sample of a zone
    may change (the Colosseum enters at Rome). Without this field a snapshot
    captured with the node+way query only would be indistinguishable from a new one.
    """
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS, bbox=_BBOX, citta="Roma")  # type: ignore[arg-type]

    conf = json.loads(p.read_text(encoding="utf-8"))["provenienza"][
        "configurazione_canonica"
    ]
    assert conf["tipi_elemento"] == ["node", "way", "relation"]


def test_mismatch_reports_snapshot_captured_without_relation(tmp_path: Path) -> None:
    """An envelope snapshot written before #314 has no ``tipi_elemento``:
    reuse must warn instead of treating it as captured with the new query."""
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS, bbox=_BBOX, citta="Roma")  # type: ignore[arg-type]
    # The file as the pre-#314 code would have written it: same provenance,
    # without the new key.
    raw = json.loads(p.read_text(encoding="utf-8"))
    del raw["provenienza"]["configurazione_canonica"]["tipi_elemento"]
    p.write_text(json.dumps(raw), encoding="utf-8")

    msg = describe_config_mismatch(snapshot_provenance(p))
    assert msg is not None
    assert "tipi_elemento" in msg


def test_mismatch_reports_missing_canonical_configuration_in_provenance() -> None:
    msg = describe_config_mismatch({"catturato_il": "x"})  # type: ignore[typeddict-item]
    assert msg is not None
    assert "senza configurazione_canonica" in msg


async def test_capturing_source_records_the_requested_bbox(tmp_path: Path) -> None:
    """The provenance bbox is the one with which the capture was requested, not
    a value reconstructed afterwards."""
    p = tmp_path / "snap.json"

    async def inner(bbox: object, citta: str):
        return _POIS, None

    source = capturing_source(p, inner=inner)  # type: ignore[arg-type]
    await source(_BBOX, "Roma")

    prov = json.loads(p.read_text(encoding="utf-8"))["provenienza"]
    assert prov["bbox"] == [41.0, 12.0, 41.1, 12.1]


# --- #251: OSM DB cut in the snapshot provenance ---
# ``catturato_il`` says "when I asked", not "which state of OSM I
# obtained": without the cut declared by Overpass, "these are the POIs of
# that zone at that instant" is not falsifiable against an OSM history dump.

_OSM_CUT: OsmCut = {
    "timestamp_osm_base": "2026-07-26T17:42:03Z",
    "overpass_url": "https://overpass-api.de/api/interpreter",
}


def test_save_snapshot_records_the_osm_cut_when_given(tmp_path: Path) -> None:
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS, bbox=_BBOX, citta="Roma", cut=_OSM_CUT)  # type: ignore[arg-type]

    prov = json.loads(p.read_text(encoding="utf-8"))["provenienza"]
    assert prov["taglio_osm"] == _OSM_CUT


def test_save_snapshot_cut_absent_by_default(tmp_path: Path) -> None:
    """A caller that does not know the cut (e.g. a test double) honestly
    declares the absence, it does not fabricate a value."""
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS, bbox=_BBOX, citta="Roma")  # type: ignore[arg-type]

    prov = json.loads(p.read_text(encoding="utf-8"))["provenienza"]
    assert prov["taglio_osm"] is None


async def test_capturing_source_records_the_osm_cut_returned_by_inner(
    tmp_path: Path,
) -> None:
    p = tmp_path / "snap.json"

    async def inner(bbox: object, citta: str):
        return _POIS, _OSM_CUT

    source = capturing_source(p, inner=inner)  # type: ignore[arg-type]
    await source(_BBOX, "Roma")

    prov = json.loads(p.read_text(encoding="utf-8"))["provenienza"]
    assert prov["taglio_osm"] == _OSM_CUT


async def test_capturing_source_without_cut_from_inner_records_no_cut(
    tmp_path: Path,
) -> None:
    """A test double that returns ``None`` for the cut (the existing test
    doubles, adapted by ``_without_cut``) declares it honestly absent."""
    p = tmp_path / "snap.json"

    async def inner(bbox: object, citta: str):
        return _POIS, None

    source = capturing_source(p, inner=inner)  # type: ignore[arg-type]
    await source(_BBOX, "Roma")

    prov = json.loads(p.read_text(encoding="utf-8"))["provenienza"]
    assert prov["taglio_osm"] is None


async def test_offline_fetch_pois_returns_pois_and_cut_with_offline_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The offline source (#232) uses OFFLINE_RETRY and also returns the OSM cut
    (#251) in the same call, without state to remember between one call and the next."""
    seen: list[object] = []

    async def _fetch_pois_with_cut_fake(bbox: object, citta: str, **kwargs: object):
        seen.append(kwargs.get("retry"))
        return _POIS, _OSM_CUT

    monkeypatch.setattr(snapshots, "fetch_pois_with_cut", _fetch_pois_with_cut_fake)

    pois, osm_cut = await offline_fetch_pois(_BBOX, "Roma")

    assert pois == _POIS
    assert osm_cut == _OSM_CUT
    assert seen == [OFFLINE_RETRY]
