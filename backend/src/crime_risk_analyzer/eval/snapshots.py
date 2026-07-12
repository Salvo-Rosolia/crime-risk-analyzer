"""Capture-and-replay degli input POI per la riproducibilità (#34)."""

from __future__ import annotations

import json
from pathlib import Path

from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.overpass_client import Poi, fetch_pois
from crime_risk_analyzer.rag.retrieval import PoiSource


def snapshot_path(results_dir: Path, key: str) -> Path:
    """Percorso della fixture POI per una chiave snapshot (#110).

    ``key`` è prodotta da ``harness.make_snapshot_key(citta, zona)`` e NON
    dipende da mode/model: i bracci comparativi (analyze/claude, analyze/groq,
    baseline) sulla stessa (citta, zona) condividono lo stesso file snapshot.
    """
    return results_dir / "snapshots" / f"{key}.json"


def save_snapshot(path: Path, pois: list[Poi]) -> None:
    """Serializza i POI su file (crea le cartelle)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(list(pois), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_snapshot(path: Path) -> list[Poi]:
    """Carica i POI da una fixture salvata."""
    data: list[Poi] = json.loads(path.read_text(encoding="utf-8"))
    return data


def replay_source(path: Path) -> PoiSource:
    """PoiSource che rigioca dalla fixture (offline, ignora bbox/citta)."""

    async def _source(bbox: Bbox, citta: str) -> list[Poi]:
        return load_snapshot(path)

    return _source


def capturing_source(path: Path, inner: PoiSource = fetch_pois) -> PoiSource:
    """PoiSource che chiama ``inner`` (Overpass reale) e salva lo snapshot."""

    async def _source(bbox: Bbox, citta: str) -> list[Poi]:
        pois = await inner(bbox, citta)
        save_snapshot(path, pois)
        return pois

    return _source
