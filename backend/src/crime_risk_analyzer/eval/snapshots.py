"""Capture-and-replay degli input POI per la riproducibilità (#34).

Ogni snapshot porta la propria PROVENIENZA (#241): la provenance esisteva per le
run (``RunRecord.provenance``) ma non per le fixture che le alimentano, e le
fixture sono la radice della catena di riproducibilità. OpenStreetMap è una
sorgente viva: fra sei mesi la stessa query darà POI diversi, quindi senza
istante di cattura «questi sono i POI di quella zona» non è verificabile.

Il formato su file è un envelope ``{"formato": 2, "provenienza": ..., "poi": [...]}``,
ma ``load_snapshot`` legge anche la lista nuda dei file catturati prima di #241: i
4 snapshot committati con #231 devono restare rigiocabili, altrimenti si
romperebbe il confronto iso-input già pubblicato.

**Quei 4 file non hanno provenienza e non è stata fabbricata**: inventarne
l'istante di cattura sarebbe stato un record falso. L'unico riferimento temporale
disponibile per loro è la data del commit che li ha introdotti (#231, 26/07/2026);
l'avranno reale alla prossima cattura, che però cambierebbe le fixture e quindi la
comparabilità dei risultati già pubblicati — perciò è una decisione dell'autore,
non un effetto collaterale.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.overpass_client import (
    MAX_POIS,
    OFFLINE_RETRY,
    PER_CLASS_CAP,
    PER_SELECTOR_CAP,
    Poi,
    fetch_pois,
)
from crime_risk_analyzer.rag.retrieval import GeoSource, PoiSource
from crime_risk_analyzer.sparql_module.osm_mapping import OSM_SELECTORS


class ConfigurazioneCanonica(TypedDict):
    """Costanti del codice che ha SCRITTO il file, non della query che l'ha prodotto.

    La distinzione non è pedanteria: ``capturing_source`` accetta un ``inner``
    arbitrario e ``fetch_pois`` accetta ``osm_selectors`` su misura, quindi da qui
    non si può sapere cosa sia stato davvero interrogato. Registrare queste
    costanti è utile — insieme al commit, dicono con quale binding e con quali cap
    lavorava il codice — ma il nome deve dire cosa sono, perché una provenienza
    che afferma piu' di quanto sa è peggio di una che tace.
    """

    selettori_hash: str
    n_selettori: int
    #: #212 li ha cambiati (50->20, 5->3): due fixture indistinguibili possono
    #: derivare da interrogazioni con cap diversi.
    max_pois: int
    per_selector_cap: int
    #: Tetto per classe TERMINUS della selezione (#254). E' parte di cosa ha
    #: prodotto il file quanto i cap della query: la sua assenza identifica uno
    #: snapshot catturato prima della selezione per prossimita'.
    per_class_cap: int


class SnapshotProvenance(TypedDict):
    """Da dove viene una fixture POI: istante, area, zona, configurazione."""

    #: Istante di cattura, ISO-8601 con offset esplicito (UTC). È l'orologio del
    #: processo che ha chiesto i dati: dice «quando ho chiesto», non «quale stato
    #: di OSM ho ottenuto» (per quello servirebbe ``osm3s.timestamp_osm_base`` del
    #: payload Overpass, che il contratto PoiSource oggi non trasporta).
    catturato_il: str
    #: Bbox interrogato, ``[min_lat, min_lon, max_lat, max_lon]``.
    bbox: list[float]
    citta: str
    #: ``None`` solo se il chiamante non l'ha dichiarata: lo slug del nome file è
    #: lossy, quindi senza questo campo il legame zona↔bbox non è verificabile.
    zona: str | None
    configurazione_canonica: ConfigurazioneCanonica


class SnapshotFile(TypedDict):
    """Formato su file di una fixture POI (#241)."""

    #: Versione del formato: permette a un lettore piu' vecchio di fallire
    #: dicendolo, invece di iterare le chiavi di un dizionario credendole POI.
    formato: int
    provenienza: SnapshotProvenance
    poi: list[Poi]


#: Versione corrente del formato su file (1 = lista nuda pre-#241, implicita).
FORMATO_SNAPSHOT = 2


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
    bbox: Bbox,
    citta: str,
    zona: str | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Serializza i POI e la loro provenienza su file (crea le cartelle).

    ``bbox`` e ``citta`` sono OBBLIGATORI: una provenienza che omette l'area
    interrogata non serve a nessuno, e renderli opzionali permetteva di scrivere
    un record con ``"bbox": null``. ``clock`` è iniettabile per i test — un
    callable e non una stringa, così l'istante non può essere fabbricato a mano:
    è il campo su cui poggia l'onestà dell'artefatto.

    Scrive con ``newline=""`` (nessuna traduzione): su Windows il default
    produceva CRLF nel working tree contro il blob LF in git, e con
    ``core.autocrlf=false`` le fixture risultavano modificate dopo ogni capture
    pur essendo identiche nel contenuto (#241, stessa classe di #103).
    """
    contenuto: SnapshotFile = {
        "formato": FORMATO_SNAPSHOT,
        "provenienza": {
            "catturato_il": clock().isoformat(),
            "bbox": [bbox.min_lat, bbox.min_lon, bbox.max_lat, bbox.max_lon],
            "citta": citta,
            "zona": zona,
            "configurazione_canonica": {
                "selettori_hash": _selettori_hash(),
                "n_selettori": len(OSM_SELECTORS),
                "max_pois": MAX_POIS,
                "per_selector_cap": PER_SELECTOR_CAP,
                "per_class_cap": PER_CLASS_CAP,
            },
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


async def offline_fetch_pois(bbox: Bbox, citta: str) -> list[Poi]:
    """Sorgente live della cattura: backoff lungo di cortesia (#232).

    Vive qui, accanto a :func:`capturing_source`, e non nel CLI: la politica di
    ritentativo della cattura è una proprietà della cattura, e come default
    dell'helper evita che un chiamante ottenga per distrazione quella
    interattiva, che il 26/07 ha rinunciato al secondo tentativo (504 poi 429)
    costringendo a un backoff scritto a mano fuori dal codice — cioè a una run
    non riproducibile.
    """
    return await fetch_pois(bbox, citta, retry=OFFLINE_RETRY)


def capturing_source(
    path: Path, inner: PoiSource = offline_fetch_pois, *, zona: str | None = None
) -> PoiSource:
    """PoiSource che chiama ``inner`` (Overpass reale) e salva lo snapshot.

    Il ``bbox`` ricevuto finisce nella provenienza (#241): è l'area effettivamente
    interrogata, non una ricostruita a posteriori. ``zona`` non è ricavabile né dal
    bbox né dai POI (lo slug del nome file è lossy), quindi va passata dal
    chiamante perché il legame zona↔bbox resti verificabile dal file.
    """

    async def _source(bbox: Bbox, citta: str) -> list[Poi]:
        pois = await inner(bbox, citta)
        save_snapshot(path, pois, bbox=bbox, citta=citta, zona=zona)
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
