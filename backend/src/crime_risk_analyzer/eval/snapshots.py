"""Capture-and-replay degli input POI per la riproducibilità (#34).

Ogni snapshot porta la propria PROVENIENZA (#241): la provenance esisteva per le
run (``RunRecord.provenance``) ma non per le fixture che le alimentano, e le
fixture sono la radice della catena di riproducibilità. OpenStreetMap è una
sorgente viva: fra sei mesi la stessa query darà POI diversi, quindi senza
istante di cattura «questi sono i POI di quella zona» non è verificabile.

Il formato su file è un envelope ``{"provenienza": ..., "poi": [...]}``, ma
``load_snapshot`` legge anche la lista nuda dei file catturati prima di #241: i 4
snapshot committati con #231 devono restare rigiocabili, altrimenti si romperebbe
il confronto iso-input già pubblicato.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.overpass_client import (
    MAX_POIS,
    PER_SELECTOR_CAP,
    Poi,
    fetch_pois,
)
from crime_risk_analyzer.rag.retrieval import GeoSource, PoiSource
from crime_risk_analyzer.sparql_module.osm_mapping import OSM_SELECTORS


class SnapshotProvenance(TypedDict):
    """Da dove viene una fixture POI: istante, area, e query che l'ha prodotta."""

    #: Istante di cattura, ISO-8601 con offset esplicito (UTC).
    catturato_il: str
    #: Bbox interrogato, ``[min_lat, min_lon, max_lat, max_lon]``; ``None`` se
    #: la cattura non l'ha dichiarato (chiamate diverse da ``capturing_source``).
    bbox: list[float] | None
    #: Impronta dell'insieme di selettori OSM usati: identifica la *versione* del
    #: binding senza copiarne 50 righe in ogni fixture.
    selettori_osm_hash: str
    n_selettori: int
    #: Cap che hanno plasmato il contenuto: #212 li ha cambiati (50->20, 5->3), e
    #: senza registrarli due fixture indistinguibili possono derivare da
    #: interrogazioni diverse.
    max_pois: int
    per_selector_cap: int


class SnapshotFile(TypedDict):
    """Formato su file di una fixture POI (#241)."""

    provenienza: SnapshotProvenance
    poi: list[Poi]


def _selettori_hash() -> str:
    """Impronta stabile dell'insieme canonico di selettori OSM."""
    canonico = "\n".join(sorted(OSM_SELECTORS))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def snapshot_path(results_dir: Path, key: str) -> Path:
    """Percorso della fixture POI per una chiave snapshot (#110).

    ``key`` è prodotta da ``harness.make_snapshot_key(citta, zona)`` e NON
    dipende da mode/model: i bracci comparativi (analyze/claude, analyze/groq,
    baseline) sulla stessa (citta, zona) condividono lo stesso file snapshot.
    """
    return results_dir / "snapshots" / f"{key}.json"


def save_snapshot(
    path: Path,
    pois: list[Poi],
    *,
    bbox: Bbox | None = None,
    now: str | None = None,
) -> None:
    """Serializza i POI e la loro provenienza su file (crea le cartelle).

    ``now`` (ISO-8601) è iniettabile per i test; ``None`` = istante reale in UTC.
    ``bbox`` è quello con cui la cattura è stata chiesta: lo passa
    :func:`capturing_source`, che lo riceve dal chiamante.

    Scrive con ``newline=""`` (nessuna traduzione): su Windows il default
    produceva CRLF nel working tree contro il blob LF in git, e con
    ``core.autocrlf=false`` le fixture risultavano modificate dopo ogni capture
    pur essendo identiche nel contenuto (#241, stessa classe di #103).
    """
    contenuto: SnapshotFile = {
        "provenienza": {
            "catturato_il": now or datetime.now(UTC).isoformat(),
            "bbox": None
            if bbox is None
            else [bbox.min_lat, bbox.min_lon, bbox.max_lat, bbox.max_lon],
            "selettori_osm_hash": _selettori_hash(),
            "n_selettori": len(OSM_SELECTORS),
            "max_pois": MAX_POIS,
            "per_selector_cap": PER_SELECTOR_CAP,
        },
        "poi": list(pois),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(contenuto, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )


def load_snapshot(path: Path) -> list[Poi]:
    """Carica i POI da una fixture salvata, con o senza provenienza (#241).

    Accetta due forme: l'envelope ``{"provenienza": ..., "poi": [...]}`` scritto
    da :func:`save_snapshot`, e la lista nuda dei file catturati prima di #241 —
    i 4 snapshot committati con #231, che devono restare rigiocabili.

    Solleva :class:`ValueError` su qualunque altra forma: uno snapshot JSON valido
    ma non riconoscibile non va rigiocato in silenzio come lista vuota. Il
    chiamante (``_snapshot_reusable``, #148) lo tratta come snapshot da
    ri-catturare.
    """
    data: object = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return cast(list[Poi], data)
    if isinstance(data, dict):
        pois = cast(dict[str, object], data).get("poi")
        if isinstance(pois, list):
            return cast(list[Poi], pois)
    raise ValueError(f"snapshot in un formato non riconosciuto: {path}")


def replay_source(path: Path) -> PoiSource:
    """PoiSource che rigioca dalla fixture (offline, ignora bbox/citta)."""

    async def _source(bbox: Bbox, citta: str) -> list[Poi]:
        return load_snapshot(path)

    return _source


def capturing_source(path: Path, inner: PoiSource = fetch_pois) -> PoiSource:
    """PoiSource che chiama ``inner`` (Overpass reale) e salva lo snapshot.

    Il ``bbox`` ricevuto finisce nella provenienza (#241): è l'area effettivamente
    interrogata, non una ricostruita a posteriori dalla zona.
    """

    async def _source(bbox: Bbox, citta: str) -> list[Poi]:
        pois = await inner(bbox, citta)
        save_snapshot(path, pois, bbox=bbox)
        return pois

    return _source


#: Placeholder deterministico per il geo in fase run. Il geo NON e' consumato a
#: valle (grounding/generation/metriche lo ignorano; replay_source ignora il bbox),
#: quindi un valore fisso rende la run ERMETICA (zero Nominatim) senza alterare alcun
#: output. Vedi #169 / review trasversale #115 (reperto A1).
_PLACEHOLDER_GEO: GeoResult = {"lat": 0.0, "lon": 0.0, "bbox": Bbox(0.0, 0.0, 0.0, 0.0)}


def offline_geo_source() -> GeoSource:
    """GeoSource placeholder deterministico: zero Nominatim, zero I/O (#169)."""

    async def _source(citta: str, zona: str) -> GeoResult:
        return _PLACEHOLDER_GEO

    return _source
