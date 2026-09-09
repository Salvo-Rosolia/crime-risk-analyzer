import json
from datetime import UTC, datetime
from pathlib import Path

from crime_risk_analyzer.eval.snapshots import (
    FORMATO_SNAPSHOT,
    capturing_source,
    describe_configurazione_mismatch,
    load_snapshot,
    offline_geo_source,
    replay_source,
    save_snapshot,
    snapshot_provenance,
)
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.overpass_client import (
    MAX_POIS,
    PER_CLASS_CAP,
    PER_SELECTOR_CAP,
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
        return _POIS

    source = capturing_source(p, inner=inner)  # type: ignore[arg-type]
    out = await source(Bbox(41.0, 12.0, 41.1, 12.1), "Roma")
    assert out[0]["name"] == "Banca A"
    assert load_snapshot(p)[0]["name"] == "Banca A"  # è stato scritto


async def test_offline_geo_source_returns_deterministic_placeholder() -> None:
    src = offline_geo_source()
    a = await src("Roma", "Colosseo")
    b = await src("Milano", "Duomo")
    # deterministico e indipendente dagli argomenti
    assert a == b
    assert isinstance(a["bbox"], Bbox)
    assert a == {"lat": 0.0, "lon": 0.0, "bbox": Bbox(0.0, 0.0, 0.0, 0.0)}


# --- #241: provenienza della fixture e newline espliciti ---
# Gli snapshot sono la RADICE della catena di riproducibilità: la provenance
# esisteva per le run (RunRecord.provenance) ma non per le fixture che le
# alimentano. OpenStreetMap è una sorgente viva: senza istante di cattura,
# «questi sono i POI di quella zona» non è un'affermazione verificabile.


def test_snapshot_porta_la_provenienza_di_cattura(tmp_path: Path) -> None:
    p = tmp_path / "snap.json"
    save_snapshot(
        p,
        _POIS,  # type: ignore[arg-type]
        bbox=_BBOX,
        citta="Roma",
        zona="Colosseo",
        clock=lambda: datetime(2026, 7, 26, 18, 40, tzinfo=UTC),
    )

    scritto = json.loads(p.read_text(encoding="utf-8"))
    assert scritto["formato"] == FORMATO_SNAPSHOT
    prov = scritto["provenienza"]
    assert prov["catturato_il"] == "2026-07-26T18:40:00+00:00"
    assert prov["bbox"] == [41.0, 12.0, 41.1, 12.1]
    assert prov["citta"] == "Roma"
    # La zona non è ricavabile dal file: lo slug del nome è lossy, quindi senza
    # questo campo il legame zona↔bbox non sarebbe verificabile.
    assert prov["zona"] == "Colosseo"
    # Costanti del codice che ha SCRITTO il file: il nome lo dichiara, perché da
    # qui non si può sapere cosa un ``inner`` arbitrario abbia interrogato.
    conf = prov["configurazione_canonica"]
    assert conf["max_pois"] == MAX_POIS
    assert conf["per_selector_cap"] == PER_SELECTOR_CAP
    # #254: la politica di selezione fa parte di cosa ha prodotto il file. Senza
    # questo campo due fixture indistinguibili potrebbero venire da tetti per
    # classe diversi, e uno snapshot pre-#254 non sarebbe riconoscibile come tale.
    assert conf["per_class_cap"] == PER_CLASS_CAP
    assert conf["n_selettori"] > 0
    assert len(conf["selettori_hash"]) == 64


def test_istante_di_cattura_reale_quando_non_iniettato(tmp_path: Path) -> None:
    """Senza clock iniettato l'istante è quello vero, in UTC con offset esplicito."""
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS, bbox=_BBOX, citta="Roma")  # type: ignore[arg-type]

    catturato = json.loads(p.read_text(encoding="utf-8"))["provenienza"]["catturato_il"]
    assert catturato.endswith("+00:00")
    assert catturato[:2] == "20"


def test_snapshot_legacy_senza_provenienza_resta_leggibile(tmp_path: Path) -> None:
    """I 4 snapshot committati con #231 sono liste nude: devono restare
    rigiocabili, altrimenti il confronto iso-input già pubblicato si rompe."""
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps(_POIS), encoding="utf-8")

    assert load_snapshot(p)[0]["name"] == "Banca A"


def test_snapshot_committati_restano_leggibili() -> None:
    """Guardia sui file veri, non su una loro imitazione: le fixture in
    ``results/snapshots/`` sono la radice della catena di riproducibilità."""
    cartella = Path(__file__).parents[2] / "results" / "snapshots"
    file = sorted(cartella.glob("*.json"))
    assert file, "attese le fixture POI versionate in results/snapshots/"
    for f in file:
        pois = load_snapshot(f)
        assert isinstance(pois, list)
        assert pois, f"snapshot vuoto: {f.name}"
        assert "terminus_class" in pois[0]


def test_scrittura_senza_churn_di_line_ending(tmp_path: Path) -> None:
    """Nessun CRLF: su Windows il working tree divergeva dal blob in git, e con
    ``core.autocrlf=false`` i 4 file risultavano modificati dopo ogni capture pur
    essendo identici nel contenuto (stessa classe del difetto chiuso in #103).

    Onestà sulla portata: questa guardia ha denti solo su Windows. In CI
    (``ubuntu-latest``) ``write_text`` produce LF anche senza ``newline=""``,
    quindi il test è verde per costruzione e una rimozione di quel parametro non
    verrebbe intercettata dalla pipeline.
    """
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS, bbox=_BBOX, citta="Roma")  # type: ignore[arg-type]

    assert b"\r\n" not in p.read_bytes()


# --- #267: la provenienza non basta più a saperla, va anche VERIFICATA ---
# Un file parsabile non è la stessa cosa di uno catturato con la politica di
# selezione corrente: senza un confronto esplicito, due esperimenti sulla
# stessa (citta, zona) possono mescolare in silenzio due configurazioni.


def test_snapshot_provenance_legge_l_envelope(tmp_path: Path) -> None:
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS, bbox=_BBOX, citta="Roma", zona="Colosseo")  # type: ignore[arg-type]

    prov = snapshot_provenance(p)
    assert prov is not None
    assert prov["citta"] == "Roma"
    assert prov["configurazione_canonica"]["max_pois"] == MAX_POIS


def test_snapshot_provenance_none_per_file_assente(tmp_path: Path) -> None:
    """Un file mancante non deve far esplodere il check: lo intercetta il vero
    consumatore (``load_snapshot`` dentro ``replay_source``), non questa sonda."""
    assert snapshot_provenance(tmp_path / "non-esiste.json") is None


def test_snapshot_provenance_none_per_lista_nuda_legacy(tmp_path: Path) -> None:
    """I 4 snapshot pre-#241 sono liste nude: nessuna provenienza da leggere."""
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps(_POIS), encoding="utf-8")

    assert snapshot_provenance(p) is None


def test_mismatch_none_quando_la_configurazione_e_quella_corrente(
    tmp_path: Path,
) -> None:
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS, bbox=_BBOX, citta="Roma")  # type: ignore[arg-type]

    assert describe_configurazione_mismatch(snapshot_provenance(p)) is None


def test_mismatch_segnala_provenienza_assente() -> None:
    """#267: la lista nuda pre-#241 riceve un avviso esplicito, non il silenzio."""
    msg = describe_configurazione_mismatch(None)
    assert msg is not None
    assert "nessuna provenienza" in msg


def test_mismatch_segnala_configurazione_divergente(tmp_path: Path) -> None:
    """Una fixture catturata con un ``per_class_cap`` diverso da quello corrente
    (es. pre-#254) non deve essere indistinguibile da una coerente."""
    p = tmp_path / "snap.json"
    save_snapshot(p, _POIS, bbox=_BBOX, citta="Roma")  # type: ignore[arg-type]
    prov = snapshot_provenance(p)
    assert prov is not None
    prov["configurazione_canonica"]["per_class_cap"] = PER_CLASS_CAP + 100

    msg = describe_configurazione_mismatch(prov)
    assert msg is not None
    assert "per_class_cap" in msg
    assert str(PER_CLASS_CAP + 100) in msg


def test_mismatch_segnala_configurazione_canonica_assente_nella_provenienza() -> None:
    msg = describe_configurazione_mismatch({"catturato_il": "x"})  # type: ignore[typeddict-item]
    assert msg is not None
    assert "senza configurazione_canonica" in msg


async def test_capturing_source_registra_il_bbox_richiesto(tmp_path: Path) -> None:
    """Il bbox della provenienza è quello con cui la cattura è stata chiesta, non
    un valore ricostruito a posteriori."""
    p = tmp_path / "snap.json"

    async def inner(bbox: object, citta: str):
        return _POIS

    source = capturing_source(p, inner=inner)  # type: ignore[arg-type]
    await source(_BBOX, "Roma")

    prov = json.loads(p.read_text(encoding="utf-8"))["provenienza"]
    assert prov["bbox"] == [41.0, 12.0, 41.1, 12.1]
