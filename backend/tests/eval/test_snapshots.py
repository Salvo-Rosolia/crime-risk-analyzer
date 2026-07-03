from pathlib import Path

from crime_risk_analyzer.eval.snapshots import (
    capturing_source,
    load_snapshot,
    replay_source,
    save_snapshot,
)
from crime_risk_analyzer.models.geo import Bbox

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


def test_save_load_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS)  # type: ignore[arg-type]
    assert load_snapshot(p)[0]["name"] == "Banca A"


async def test_replay_source_returns_saved_pois(tmp_path: Path) -> None:
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS)  # type: ignore[arg-type]
    source = replay_source(p)
    out = await source(Bbox(41.0, 12.0, 41.1, 12.1), "Roma")
    assert out[0]["name"] == "Banca A"


async def test_capturing_source_writes_and_passes_through(tmp_path: Path) -> None:
    p = tmp_path / "snap.json"

    async def inner(bbox: object, citta: str):
        return _POIS

    source = capturing_source(p, inner=inner)  # type: ignore[arg-type]
    out = await source(Bbox(41.0, 12.0, 41.1, 12.1), "Roma")
    assert out[0]["name"] == "Banca A"
    assert load_snapshot(p)[0]["name"] == "Banca A"  # è stato scritto
