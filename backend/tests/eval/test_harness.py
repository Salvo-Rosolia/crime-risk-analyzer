"""Test dell'harness di esecuzione esperimenti (#34, iso-input #110)."""

from __future__ import annotations

from pathlib import Path

import pytest

from crime_risk_analyzer.eval.harness import (
    _record_from_response,  # pyright: ignore[reportPrivateUsage]
    make_run_id,
    make_snapshot_key,
    run_case,
    run_experiment,
)
from crime_risk_analyzer.eval.schema import (
    ExperimentConfig,
    Mode,
    RunCase,
    RunStatus,
)
from crime_risk_analyzer.eval.snapshots import (
    capturing_source,
    load_snapshot,
    snapshot_path,
)
from crime_risk_analyzer.llm.client import GROQ_MODEL
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.vocab import ConfidenceSummary
from crime_risk_analyzer.orchestrator import AnalyzeResponse, ZonaGeo
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.rag.generation import RiskModel
from tests.eval._doubles import scrivi_snapshot


def _fake_geocode_fixture(zona: str, citta: str) -> dict[str, object]:
    return {"lat": 41.0, "lon": 12.0, "bbox": Bbox(41.0, 12.0, 41.1, 12.1)}


def _sample_pois() -> list[Poi]:
    """Fixture POI minimale condivisa dai test dell'harness."""
    return [
        Poi(
            id="1",
            name="Banca A",
            lat=41.0,
            lon=12.0,
            osm_tags="amenity=bank",
            terminus_class="Bank",
            citta="Roma",
        )
    ]


def test_make_run_id_deterministic() -> None:
    a = make_run_id("ablation", "Roma", "Centro Storico", "analyze", "claude")
    b = make_run_id("ablation", "Roma", "Centro Storico", "analyze", "claude")
    assert a == b
    assert " " not in a


def test_make_run_id_includes_repetition_index() -> None:
    """Ripetizioni distinte producono run_id distinti; default rep=0 → __rep00."""
    r0 = make_run_id("exp", "Roma", "Centro", "analyze", "claude")
    r0_explicit = make_run_id("exp", "Roma", "Centro", "analyze", "claude", 0)
    r1 = make_run_id("exp", "Roma", "Centro", "analyze", "claude", 1)
    assert r0 == r0_explicit
    assert r0.endswith("__rep00")
    assert r1.endswith("__rep01")
    assert r0 != r1


async def test_run_experiment_repeat_writes_k_records_no_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--repeat 3 → 3 record e 3 JSON distinti per caso (nessuna sovrascrittura)."""
    cfg = ExperimentConfig(
        name="exp",
        mode="analyze",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    scrivi_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    records = await run_experiment(
        cfg,
        executor=FakeProfiler(),
        llm_client=FakeLLMClient(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
        repeat=3,
    )
    assert len(records) == 3
    run_ids = {r.run_id for r in records}
    assert len(run_ids) == 3
    written = list((tmp_path / "runs").glob("*.json"))
    assert len(written) == 3


async def test_run_experiment_writes_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Snapshot pre-salvato per ogni caso → replay offline.
    cfg = ExperimentConfig(
        name="exp",
        mode="analyze",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    rid = make_run_id("exp", "Roma", "Centro", "analyze", "claude")
    # Snapshot chiavato per (citta, zona), condiviso dai bracci comparativi (#110).
    scrivi_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )

    # geocode mockato (replay ignora il bbox ma retrieve lo richiede)
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeLLMClient, FakeProfiler  # vedi nota sotto

    records = await run_experiment(
        cfg,
        executor=FakeProfiler(),
        llm_client=FakeLLMClient(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )
    assert len(records) == 1
    assert records[0].status == RunStatus.OK
    assert (tmp_path / "runs" / f"{rid}.json").exists()
    assert records[0].metrics.latency_ms >= 0


# --- #267: la run che rigioca uno snapshot riporta la SUA provenienza, non
# solo il commit di chi la esegue --- (evita che due politiche di selezione
# diverse finiscano nello stesso esperimento senza alcun segnale)


async def test_run_experiment_riporta_la_provenienza_dello_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = ExperimentConfig(
        name="exp",
        mode="analyze",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    scrivi_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )

    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    records = await run_experiment(
        cfg,
        executor=FakeProfiler(),
        llm_client=FakeLLMClient(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )
    prov = records[0].provenance
    assert prov.snapshot_catturato_il is not None
    assert prov.snapshot_configurazione_canonica is not None


async def test_run_experiment_avvisa_su_snapshot_senza_provenienza(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Una fixture pre-#241 (lista nuda) resta rigiocabile ma non più in
    silenzio: la run logga un avviso invece di trattarla come una qualunque."""
    import json

    cfg = ExperimentConfig(
        name="exp",
        mode="analyze",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([dict(p) for p in _sample_pois()]), encoding="utf-8")

    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    with caplog.at_level("WARNING"):
        records = await run_experiment(
            cfg,
            executor=FakeProfiler(),
            llm_client=FakeLLMClient(),
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )

    assert records[0].provenance.snapshot_catturato_il is None
    assert records[0].provenance.snapshot_configurazione_canonica is None
    assert any("#267" in rec.message for rec in caplog.records)
    assert any("nessuna provenienza" in rec.message for rec in caplog.records)


async def test_run_experiment_non_avvisa_su_snapshot_mancante(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Uno snapshot MAI catturato non e' un caso di provenienza da segnalare:
    e' un fallimento diverso (isolamento #252), non va confuso con un avviso
    di configurazione divergente prima ancora dell'errore vero e proprio."""
    cfg = ExperimentConfig(
        name="exp",
        mode="analyze",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    # Nessuno snapshot scritto per (Roma, Centro).

    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    with caplog.at_level("WARNING"):
        records = await run_experiment(
            cfg,
            executor=FakeProfiler(),
            llm_client=FakeLLMClient(),
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )

    assert records[0].status == RunStatus.ERROR
    assert not any("#267" in rec.message for rec in caplog.records)


async def test_run_experiment_ignora_catturato_il_di_tipo_sbagliato(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una provenienza con ``catturato_il`` non stringa (dato esterno malformato)
    non deve far fallire la validazione di ``Provenance`` e con essa la run."""
    import json

    cfg = ExperimentConfig(
        name="exp",
        mode="analyze",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    path = snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro"))
    scrivi_snapshot(path, _sample_pois())
    scritto = json.loads(path.read_text(encoding="utf-8"))
    scritto["provenienza"]["catturato_il"] = 12345  # tipo sbagliato
    path.write_text(json.dumps(scritto), encoding="utf-8")

    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    records = await run_experiment(
        cfg,
        executor=FakeProfiler(),
        llm_client=FakeLLMClient(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )

    assert records[0].status == RunStatus.OK
    assert records[0].provenance.snapshot_catturato_il is None


async def test_run_experiment_rejects_non_positive_repeat(tmp_path: Path) -> None:
    """repeat < 1 → ValueError (niente esperimento vuoto in silenzio)."""
    from tests.eval._doubles import FakeProfiler

    cfg = ExperimentConfig(
        name="x",
        mode="baseline",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    with pytest.raises(ValueError):
        await run_experiment(
            cfg,
            executor=FakeProfiler(),
            llm_client=None,
            results_dir=tmp_path,
            code_commit="c",
            ontology_hash="o",
            repeat=0,
        )


async def test_run_experiment_baseline_no_llm_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_experiment con mode='baseline' e llm_client=None → status=ok (fix T9).

    Baseline non chiama il provider LLM: passare None non deve fallire.
    """
    cfg = ExperimentConfig(
        name="base",
        mode="baseline",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    # Snapshot chiavato per (citta, zona) (#110): baseline usa la stessa fixture.
    scrivi_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )

    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeProfiler

    records = await run_experiment(
        cfg,
        executor=FakeProfiler(),
        llm_client=None,
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )
    assert len(records) == 1
    assert records[0].status == RunStatus.OK


async def test_run_experiment_error_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un caso senza snapshot → status=error; l'esperimento continua."""
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    cfg = ExperimentConfig(
        name="iso",
        mode="analyze",
        model="claude",
        cases=[
            RunCase(citta="Roma", zona="Centro"),
            RunCase(citta="Roma", zona="Prati"),
        ],
    )

    # Solo (Roma, Centro) ha lo snapshot: chiave per (citta, zona) (#110).
    rid_ok = make_run_id("iso", "Roma", "Centro", "analyze", "claude")
    scrivi_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    # Il secondo caso (Prati) non ha snapshot → FileNotFoundError → status=error.
    rid_err = make_run_id("iso", "Roma", "Prati", "analyze", "claude")

    records = await run_experiment(
        cfg,
        executor=FakeProfiler(),
        llm_client=FakeLLMClient(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )

    assert len(records) == 2
    assert records[0].status == RunStatus.OK
    assert records[1].status == RunStatus.ERROR
    assert (tmp_path / "runs" / f"{rid_ok}.json").exists()
    assert (tmp_path / "runs" / f"{rid_err}.json").exists()


async def test_run_case_non_maschera_un_errore_di_calcolo_delle_metriche(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Il ``try`` copre la chiamata al modello, non le metriche a valle.

    Un ``model_id`` non a listino (qui: ``KeyError`` da ``pricing.cost_usd``) e'
    un bug di codice/configurazione, non un fallimento del provider: deve
    propagare con il suo traceback invece di diventare un record
    ``status=ERROR`` con metriche a zero, indistinguibile da "il modello ha
    fallito". In una run live la differenza e' tutta: assorbirlo brucerebbe la
    quota Groq della giornata producendo il 100% di record ERROR senza un solo
    traceback da leggere.

    Resta vero anche dopo che ``run_experiment`` ha imparato a non morire su un
    caso rotto: l'isolamento sta un livello SOPRA (con traceback e uno status
    suo), non dentro questo ``try``. Rimetterlo qui richiuderebbe il buco
    sbagliato — e questo caso tornerebbe rosso.
    """
    from crime_risk_analyzer.llm.client import LLMResponse
    from crime_risk_analyzer.rag import retrieval
    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    scrivi_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    risposta_di_modello_non_prezzato = LLMResponse(
        text="Analisi: Banca A presenta rischio rapina.",
        llm_used="provider/modello-mai-prezzato",
        tokens_input=10,
        tokens_output=20,
        cache_hit=False,
        temperature=0.0,
        seed=0,
        prompt_hash="abc",
    )

    with pytest.raises(KeyError, match="modello-mai-prezzato"):
        await run_case(
            RunCase(citta="Roma", zona="Centro"),
            ExperimentConfig(
                name="exp",
                mode="analyze",
                model="groq",
                cases=[RunCase(citta="Roma", zona="Centro")],
            ),
            executor=FakeProfiler(),
            llm_client=FakeLLMClient(risposta_di_modello_non_prezzato),
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )


async def test_run_experiment_rifiuta_subito_un_braccio_senza_client(
    tmp_path: Path,
) -> None:
    """Una configurazione impossibile si ferma PRIMA di eseguire, non caso per caso.

    L'isolamento serve ai guasti che riguardano UN caso. Un braccio con modello
    a cui manca il client non e' quello: fallirebbe identico su tutti i casi e su
    tutte le ripetizioni, lasciando a terra N record ``HARNESS_ERROR`` che il
    confronto conterebbe poi come zone fallite. Non c'e' nulla da salvare
    proseguendo, e l'errore e' noto prima di partire.
    """
    from tests.eval._doubles import FakeProfiler

    with pytest.raises(ValueError, match="llm_client"):
        await run_experiment(
            ExperimentConfig(
                name="senza-client",
                mode="analyze",
                model="groq",
                cases=[RunCase(citta="Roma", zona="Centro")],
            ),
            executor=FakeProfiler(),
            llm_client=None,
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )

    assert not (tmp_path / "runs").exists(), "nessun record scritto: non si parte"


async def test_run_experiment_isola_un_errore_di_configurazione_e_prosegue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Un caso che esplode FUORI dal ``try`` di ``run_case`` non abbatte la run.

    L'eccezione che il fix precedente ha lasciato propagare (``KeyError`` dal
    listino prezzi su un ``llm_used`` non a listino — l'alias versionato che Groq
    riporta davvero) usciva da ``run_case`` e arrivava fino in cima: l'intero
    esperimento moriva sul PRIMO caso, perdendo tutti i successivi. In una run
    live con quota giornaliera e' il danno peggiore, perche' la quota consumata
    fin li' non torna indietro.

    Il caso rotto resta rotto (nessuna metrica inventata), ma e' isolato: gli
    altri casi girano, e il suo record lo dice per cio' che e'.
    """
    from crime_risk_analyzer.llm.client import LLMResponse
    from crime_risk_analyzer.rag import retrieval
    from tests.eval._doubles import FakeProfiler, default_llm_response

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    for zona in ("Centro", "Prati"):
        scrivi_snapshot(
            snapshot_path(tmp_path, make_snapshot_key("Roma", zona)), _sample_pois()
        )

    class _PrimoCasoNonPrezzato:
        """Primo caso: model id fuori listino → KeyError nelle metriche."""

        def __init__(self) -> None:
            self.chiamate = 0

        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            self.chiamate += 1
            if self.chiamate == 1:
                return default_llm_response().model_copy(
                    update={"llm_used": "provider/modello-mai-prezzato"}
                )
            return default_llm_response()

    cfg = ExperimentConfig(
        name="iso-harness",
        mode="analyze",
        model="groq",
        cases=[
            RunCase(citta="Roma", zona="Centro"),
            RunCase(citta="Roma", zona="Prati"),
        ],
    )

    with caplog.at_level("ERROR"):
        records = await run_experiment(
            cfg,
            executor=FakeProfiler(),
            llm_client=_PrimoCasoNonPrezzato(),
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )

    assert len(records) == 2
    assert records[0].status == RunStatus.HARNESS_ERROR
    assert records[1].status == RunStatus.OK
    # Entrambi i record finiscono su disco: la run e' completa e auditabile.
    for zona in ("Centro", "Prati"):
        rid = make_run_id("iso-harness", "Roma", zona, "analyze", "groq")
        assert (tmp_path / "runs" / f"{rid}.json").exists()


async def test_un_errore_di_configurazione_non_passa_inosservato(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Isolare non e' zittire: l'eccezione va loggata CON il suo traceback.

    E' la meta' che rende l'isolamento accettabile. Un ``except`` che si limita a
    scrivere un record marcato riprodurrebbe il bloccante precedente spostato di
    un livello: la run finirebbe, ma chi legge i risultati non avrebbe modo di
    sapere che a rompersi e' stato il codice e non il provider.
    """
    from crime_risk_analyzer.llm.client import LLMResponse
    from crime_risk_analyzer.rag import retrieval
    from tests.eval._doubles import FakeProfiler, default_llm_response

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    scrivi_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )

    class _NonPrezzato:
        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            return default_llm_response().model_copy(
                update={"llm_used": "provider/modello-mai-prezzato"}
            )

    with caplog.at_level("ERROR"):
        await run_experiment(
            ExperimentConfig(
                name="log-harness",
                mode="analyze",
                model="groq",
                cases=[RunCase(citta="Roma", zona="Centro")],
            ),
            executor=FakeProfiler(),
            llm_client=_NonPrezzato(),
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )

    errori = [rec for rec in caplog.records if rec.levelname == "ERROR"]
    assert errori, "l'eccezione isolata deve restare visibile nei log"
    assert any(rec.exc_info is not None for rec in errori), (
        "senza traceback il log dice che qualcosa e' fallito ma non dove"
    )
    assert any("Centro" in rec.getMessage() for rec in errori)


@pytest.mark.parametrize("mode", ["baseline", "analyze"])
async def test_run_does_not_geocode_when_replaying(
    mode: Mode, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run (replay): 0 geocode su ENTRAMBI i rami (baseline/analyze), repeat>1 (#169).

    Copre il fail-if-removed anche sul ramo analyze di ``run_case``: se il wiring
    di ``geo_source`` sparisse dalla chiamata ``run_analysis``, il ramo analyze
    tornerebbe a geocodificare live e questo caso fallirebbe.
    """
    from crime_risk_analyzer.geocoding import GeoResult
    from crime_risk_analyzer.rag import retrieval

    calls = {"n": 0}

    def _boom(zona: str, citta: str) -> GeoResult:
        calls["n"] += 1
        raise AssertionError("la run non deve geocodificare")

    monkeypatch.setattr(retrieval, "geocode_zone", _boom)

    # Pre-salva SOLO lo snapshot POI (nessun file geo esiste in #169).
    key = make_snapshot_key("Roma", "Colosseo")
    scrivi_snapshot(snapshot_path(tmp_path, key), _sample_pois())

    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    config = ExperimentConfig(
        name="exp",
        mode=mode,
        model="claude",
        cases=[RunCase(citta="Roma", zona="Colosseo")],
    )
    # analyze richiede un llm_client (fake gia' usato nel file); baseline no.
    llm_client = FakeLLMClient() if mode == "analyze" else None

    records = await run_experiment(
        config,
        executor=FakeProfiler(),
        llm_client=llm_client,
        results_dir=tmp_path,
        code_commit="c",
        ontology_hash="o",
        repeat=2,
    )
    assert calls["n"] == 0
    # Il test non deve passare per un errore a monte inghiottito da run_case.
    assert all(r.status == RunStatus.OK for r in records)


def test_make_snapshot_key_ignores_mode_and_model() -> None:
    """La chiave snapshot dipende SOLO da (citta, zona) (#110).

    I bracci comparativi (analyze/claude, analyze/groq, baseline) condividono la
    stessa fixture POI; il run_id resta invece per-run (varia con mode/model).
    """
    key = make_snapshot_key("Roma", "Centro Storico")
    assert key == make_snapshot_key("Roma", "Centro Storico")
    assert " " not in key
    rid_claude = make_run_id("ablation", "Roma", "Centro Storico", "analyze", "claude")
    rid_groq = make_run_id("ablation", "Roma", "Centro Storico", "analyze", "groq")
    rid_baseline = make_run_id(
        "ablation", "Roma", "Centro Storico", "baseline", "claude"
    )
    assert rid_claude != rid_groq != rid_baseline
    assert len({rid_claude, rid_groq, rid_baseline}) == 3


def test_make_snapshot_key_is_canonical() -> None:
    """Chiave canonica: case e whitespace normalizzati (#110).

    'Milano' e ' milano ' non devono generare snapshot separati.
    """
    assert make_snapshot_key("Milano", "Centro") == make_snapshot_key(
        " milano ", "CENTRO"
    )
    assert make_snapshot_key("Roma", "Centro Storico") == "roma__centro-storico"


async def test_comparative_arms_share_one_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #110: model/mode diversi sulla stessa (citta, zona) → STESSO snapshot.

    Una fixture salvata una volta è rigiocata dai tre bracci (analyze/claude,
    analyze/groq, baseline): nessuna divergenza di POI tra i bracci.
    """
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    key = make_snapshot_key("Roma", "Centro")
    scrivi_snapshot(snapshot_path(tmp_path, key), _sample_pois())

    cfg_claude = ExperimentConfig(
        name="ablation",
        mode="analyze",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    cfg_groq = ExperimentConfig(
        name="ablation",
        mode="analyze",
        model="groq",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    cfg_baseline = ExperimentConfig(
        name="ablation",
        mode="baseline",
        model="claude",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )

    rec_claude = (
        await run_experiment(
            cfg_claude,
            executor=FakeProfiler(),
            llm_client=FakeLLMClient(),
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )
    )[0]
    rec_groq = (
        await run_experiment(
            cfg_groq,
            executor=FakeProfiler(),
            llm_client=FakeLLMClient(),
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )
    )[0]
    rec_baseline = (
        await run_experiment(
            cfg_baseline,
            executor=FakeProfiler(),
            llm_client=None,
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )
    )[0]

    # Nessun braccio va in errore per snapshot mancante: leggono tutti la stessa.
    assert rec_claude.status == RunStatus.OK
    assert rec_groq.status == RunStatus.OK
    assert rec_baseline.status == RunStatus.OK
    # Provenienza auditabile: tutti citano lo stesso snapshot (citta, zona).
    assert rec_claude.provenance.snapshot_id == key
    assert rec_groq.provenance.snapshot_id == key
    assert rec_baseline.provenance.snapshot_id == key
    # Iso-input: stessa fixture → stesso conteggio POI per ogni braccio.
    assert rec_claude.n_poi == rec_groq.n_poi == rec_baseline.n_poi == 1
    # Un solo file snapshot per (citta, zona): nessuna copia per-braccio.
    assert list((tmp_path / "snapshots").glob("*.json")) == [
        snapshot_path(tmp_path, key)
    ]
    # N1: le LISTE di POI risolte dai tre bracci sono IDENTICHE (stesso input, non
    # solo stessa cardinalità), caricate dallo snapshot citato in provenance.
    pois_by_arm = [
        load_snapshot(snapshot_path(tmp_path, rec.provenance.snapshot_id))
        for rec in (rec_claude, rec_groq, rec_baseline)
    ]
    assert pois_by_arm[0] == pois_by_arm[1] == pois_by_arm[2] == _sample_pois()


async def test_capture_once_replayed_by_other_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #110: cattura live UNA volta per (citta, zona); l'altro braccio rigioca.

    Con model/mode diversi non parte una seconda query live: la fixture è condivisa.
    """
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    from tests.eval._doubles import FakeProfiler

    calls = 0

    async def counting_inner(bbox: Bbox, citta: str) -> tuple[list[Poi], None]:
        nonlocal calls
        calls += 1
        return _sample_pois(), None

    # Braccio A (analyze/claude) cattura live → scrive lo snapshot alla chiave.
    key = make_snapshot_key("Roma", "Centro")
    capture = capturing_source(snapshot_path(tmp_path, key), inner=counting_inner)
    await capture(Bbox(41.0, 12.0, 41.1, 12.1), "Roma")
    assert calls == 1

    # Braccio B (baseline/groq) rigioca dallo stesso snapshot: nessuna nuova query.
    cfg_baseline = ExperimentConfig(
        name="ablation",
        mode="baseline",
        model="groq",
        cases=[RunCase(citta="Roma", zona="Centro")],
    )
    records = await run_experiment(
        cfg_baseline,
        executor=FakeProfiler(),
        llm_client=None,
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )
    assert records[0].status == RunStatus.OK
    assert calls == 1  # nessuna seconda cattura live
    assert records[0].provenance.snapshot_id == key


async def test_no_ontology_arm_replays_the_snapshot_of_the_complete_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#236: i due bracci del confronto C3 girano sullo STESSO snapshot POI.

    Il braccio ablato non e' una seconda cattura: la chiave dello snapshot resta
    ``(citta, zona)`` (#110), quindi la variabile che cambia tra i bracci e' solo
    il prompt. Il test verifica insieme le due meta' del criterio di accettazione:
    iso-input (stesso ``snapshot_id``, stessi POI, un solo file di snapshot) e
    provenienza distinguibile (``run_id``, ``mode`` e ``prompt_hash`` diversi —
    quest'ultimo perche' i due bracci mandano al modello system prompt diversi).
    """
    import hashlib

    from crime_risk_analyzer.llm.client import LLMResponse
    from crime_risk_analyzer.models.risk import PoiRiskProfile
    from crime_risk_analyzer.rag import retrieval
    from tests.eval._doubles import FakeProfiler, default_llm_response

    class _HashingLLMClient:
        """Doppio che hashea il system prompt come fa il client reale (#114)."""

        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            self.calls.append((system_prompt, user_content))
            return default_llm_response().model_copy(
                update={
                    "prompt_hash": hashlib.sha256(system_prompt.encode()).hexdigest()
                }
            )

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    key = make_snapshot_key("Roma", "Centro")
    scrivi_snapshot(snapshot_path(tmp_path, key), _sample_pois())
    profiler = FakeProfiler(
        {
            "Bank": PoiRiskProfile(
                terminus_class="Bank",
                hazards=["Bank_robbery"],
                sparql_paths=["Bank → havingHazard → Bank_robbery"],
            )
        }
    )

    client_completo = _HashingLLMClient()
    client_ablato = _HashingLLMClient()
    rec_completo = (
        await run_experiment(
            ExperimentConfig(
                name="ablation-analyze-groq",
                mode="analyze",
                model="groq",
                cases=[RunCase(citta="Roma", zona="Centro")],
            ),
            executor=profiler,
            llm_client=client_completo,
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )
    )[0]
    rec_ablato = (
        await run_experiment(
            ExperimentConfig(
                name="ablation-no-ontology-groq",
                mode="no_ontology_prompt",
                model="groq",
                cases=[RunCase(citta="Roma", zona="Centro")],
            ),
            executor=profiler,
            llm_client=client_ablato,
            results_dir=tmp_path,
            code_commit="abc",
            ontology_hash="def",
        )
    )[0]

    assert rec_completo.status == RunStatus.OK
    assert rec_ablato.status == RunStatus.OK
    # Iso-input: stessa fixture, un solo file catturato, stesso numero di POI.
    assert (
        rec_ablato.provenance.snapshot_id == rec_completo.provenance.snapshot_id == key
    )
    assert rec_ablato.n_poi == rec_completo.n_poi == 1
    assert list((tmp_path / "snapshots").glob("*.json")) == [
        snapshot_path(tmp_path, key)
    ]
    # Provenienza: i due bracci restano distinguibili nei risultati.
    assert rec_ablato.mode == "no_ontology_prompt"
    assert rec_completo.mode == "analyze"
    assert rec_ablato.run_id != rec_completo.run_id
    assert rec_ablato.provenance.prompt_hash != rec_completo.provenance.prompt_hash
    # La variabile isolata: l'ontologia arriva al prompt solo nel braccio completo.
    assert "Bank_robbery" in client_completo.calls[0][1]
    assert "Bank_robbery" not in client_ablato.calls[0][1]
    assert "  POI: Banca A (Bank)" in client_ablato.calls[0][1]


async def test_no_ontology_arm_is_not_a_vacuous_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Il braccio produce prosa: i proxy di qualita' hanno di che pronunciarsi.

    E' il difetto che #236 chiude rispetto a ``baseline``, muto per costruzione:
    un braccio senza narrativa fa cadere ``grounding``/``hallucination`` nel ramo
    vacuo e a valle il verdetto viene TRATTENUTO (#231).
    """
    from crime_risk_analyzer.eval.compare import has_narrativa, is_vacuous_arm
    from crime_risk_analyzer.rag import retrieval
    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    scrivi_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    records = await run_experiment(
        ExperimentConfig(
            name="no-onto",
            mode="no_ontology_prompt",
            model="groq",
            cases=[RunCase(citta="Roma", zona="Centro")],
        ),
        executor=FakeProfiler(),
        llm_client=FakeLLMClient(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )
    assert has_narrativa(records[0])
    assert not is_vacuous_arm(records)


async def test_no_ontology_arm_is_measured_on_the_block_its_prompt_asks_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Il record porta il ``mode``, e il ``mode`` decide su cosa si misura.

    Il prompt ablato chiede per onesta' un blocco ``[SINTESI-LLM]``: se
    l'harness misurasse ogni braccio sull'etichetta ``[ONTOLOGIA]``, quel
    braccio prenderebbe 0.0/1.0 per NON-ATTRIBUZIONE su ogni run e il confronto
    C3 sarebbe deciso dal nome dell'etichetta invece che dall'ancoraggio.
    """
    from crime_risk_analyzer.llm.client import LLMResponse
    from crime_risk_analyzer.rag import retrieval
    from crime_risk_analyzer.rag.no_ontology_generation import (
        LLM_SYNTHESIS_BLOCK_HEADER,
    )
    from tests.eval._doubles import FakeLLMClient, FakeProfiler

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)
    scrivi_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    risposta = LLMResponse(
        text=(
            f"Sintesi della zona.\n\n{LLM_SYNTHESIS_BLOCK_HEADER}\n"
            "Banca A presenta rischio rapina."
        ),
        llm_used=GROQ_MODEL,
        tokens_input=10,
        tokens_output=20,
        cache_hit=False,
        temperature=0.0,
        seed=0,
        prompt_hash="abc",
    )
    records = await run_experiment(
        ExperimentConfig(
            name="no-onto",
            mode="no_ontology_prompt",
            model="groq",
            cases=[RunCase(citta="Roma", zona="Centro")],
        ),
        executor=FakeProfiler(),
        llm_client=FakeLLMClient(risposta),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )
    assert records[0].metrics.grounding == 1.0
    assert records[0].metrics.hallucination == 0.0


async def test_no_ontology_arm_requires_an_llm_client(tmp_path: Path) -> None:
    """Senza client il braccio non ha senso: e' il braccio CON l'LLM.

    Il ramo di ``run_case`` che solleva e' quello di ``analyze``: se il nuovo mode
    finisse per sbaglio nel ramo baseline, la run girerebbe senza modello e
    produrrebbe un secondo braccio muto invece del confronto cercato.
    """
    from tests.eval._doubles import FakeProfiler

    with pytest.raises(ValueError, match="llm_client"):
        await run_case(
            RunCase(citta="Roma", zona="Centro"),
            ExperimentConfig(
                name="no-onto",
                mode="no_ontology_prompt",
                model="groq",
                cases=[RunCase(citta="Roma", zona="Centro")],
            ),
            executor=FakeProfiler(),
            llm_client=None,
            results_dir=tmp_path,
            code_commit="c",
            ontology_hash="o",
        )


def _legacy_record(experiment: str, citta: str, zona: str):
    from crime_risk_analyzer.eval.schema import (
        Metrics,
        Provenance,
        RunRecord,
        RunStatus,
    )

    # run_id in formato PRE-#157: nessun suffisso __rep.
    return RunRecord(
        run_id=f"{experiment}__{citta}__{zona}__analyze__groq".lower(),
        experiment=experiment,
        citta=citta,
        zona=zona,
        mode="analyze",
        model_id="m",
        status=RunStatus.OK,
        metrics=Metrics(
            grounding=0.8, hallucination=0.2, latency_ms=1000, cost_usd=0.001
        ),
        narrativa="x",
        n_poi=1,
        provenance=Provenance(
            code_commit="c",
            ontology_hash="o",
            snapshot_id=f"{citta}__{zona}".lower(),
            model_id="m",
            prompt_hash="p",
            temperature=0.0,
            seed=0,
            experiment=experiment,
        ),
    )


def test_is_repeated_run_id() -> None:
    from crime_risk_analyzer.eval.harness import is_repeated_run_id, make_run_id

    assert is_repeated_run_id(
        make_run_id("e", "Roma", "Colosseo", "analyze", "groq", 0)
    )
    assert not is_repeated_run_id("e__roma__colosseo__analyze__groq")


def test_guard_no_legacy_runs_raises_on_legacy(tmp_path: Path) -> None:
    from crime_risk_analyzer.eval.harness import guard_no_legacy_runs, write_record

    write_record(tmp_path, _legacy_record("exp", "Roma", "Colosseo"))
    with pytest.raises(ValueError, match="legacy"):
        guard_no_legacy_runs(tmp_path, "exp")


def test_guard_no_legacy_runs_clean_stale_removes(tmp_path: Path) -> None:
    from crime_risk_analyzer.eval.harness import (
        guard_no_legacy_runs,
        legacy_run_paths,
        write_record,
    )

    p = write_record(tmp_path, _legacy_record("exp", "Roma", "Colosseo"))
    guard_no_legacy_runs(tmp_path, "exp", clean_stale=True)
    assert not p.exists()
    assert legacy_run_paths(tmp_path, "exp") == []


def test_guard_no_legacy_runs_ignores_repeated_and_other_experiments(
    tmp_path: Path,
) -> None:
    from crime_risk_analyzer.eval.harness import (
        guard_no_legacy_runs,
        make_run_id,
        write_record,
    )
    from crime_risk_analyzer.eval.schema import (
        Metrics,
        Provenance,
        RunRecord,
        RunStatus,
    )

    # record __rep dello stesso esperimento: NON deve far scattare la guardia.
    rec = RunRecord(
        run_id=make_run_id("exp", "Roma", "Colosseo", "analyze", "groq", 0),
        experiment="exp",
        citta="Roma",
        zona="Colosseo",
        mode="analyze",
        model_id="m",
        status=RunStatus.OK,
        metrics=Metrics(
            grounding=0.8, hallucination=0.2, latency_ms=1000, cost_usd=0.001
        ),
        narrativa="x",
        n_poi=1,
        provenance=Provenance(
            code_commit="c",
            ontology_hash="o",
            snapshot_id="roma__colosseo",
            model_id="m",
            prompt_hash="p",
            temperature=0.0,
            seed=0,
            experiment="exp",
        ),
    )
    write_record(tmp_path, rec)
    # legacy ma di ALTRO esperimento: irrilevante per "exp".
    write_record(tmp_path, _legacy_record("other", "Milano", "Duomo"))
    guard_no_legacy_runs(tmp_path, "exp")  # non solleva


def test_guard_no_legacy_runs_clean_stale_removes_only_target(tmp_path: Path) -> None:
    """--clean-stale rimuove SOLO i legacy dell'esperimento target.

    Sicurezza-dati: un record __rep dello stesso esperimento e un legacy di un
    ALTRO esperimento non devono essere toccati dalla pulizia.
    """
    from crime_risk_analyzer.eval.harness import (
        guard_no_legacy_runs,
        legacy_run_paths,
        make_run_id,
        write_record,
    )
    from crime_risk_analyzer.eval.schema import (
        Metrics,
        Provenance,
        RunRecord,
        RunStatus,
    )

    # (a) legacy TARGET dell'esperimento "exp": deve essere rimosso.
    target = write_record(tmp_path, _legacy_record("exp", "Roma", "Colosseo"))
    # (b) record __rep dello stesso "exp": ripetizione valida, NON va toccata.
    rep = RunRecord(
        run_id=make_run_id("exp", "Roma", "Colosseo", "analyze", "groq", 0),
        experiment="exp",
        citta="Roma",
        zona="Colosseo",
        mode="analyze",
        model_id="m",
        status=RunStatus.OK,
        metrics=Metrics(
            grounding=0.8, hallucination=0.2, latency_ms=1000, cost_usd=0.001
        ),
        narrativa="x",
        n_poi=1,
        provenance=Provenance(
            code_commit="c",
            ontology_hash="o",
            snapshot_id="roma__colosseo",
            model_id="m",
            prompt_hash="p",
            temperature=0.0,
            seed=0,
            experiment="exp",
        ),
    )
    rep_path = write_record(tmp_path, rep)
    # (c) legacy di ALTRO esperimento: fuori scope, NON va toccato.
    other = write_record(tmp_path, _legacy_record("other", "Milano", "Duomo"))

    guard_no_legacy_runs(tmp_path, "exp", clean_stale=True)

    assert not target.exists()  # (a) rimosso
    assert rep_path.exists()  # (b) intatto
    assert other.exists()  # (c) intatto
    assert legacy_run_paths(tmp_path, "exp") == []


async def test_run_experiment_propagates_and_records_the_context_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#273: la variante deve arrivare al prompt E finire nel record.

    Se arrivasse al prompt senza essere registrata, un A/B fra i due formati
    produrrebbe record indistinguibili (``prompt_hash`` copre il solo system
    prompt); se fosse registrata senza arrivare al prompt, il record mentirebbe.
    Il test chiude entrambi i lati.
    """
    from crime_risk_analyzer.llm.client import LLMResponse
    from tests.eval._doubles import FakeProfiler, default_llm_response

    visti: list[str] = []

    class _Recording:
        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            visti.append(user_content)
            return default_llm_response()

    scrivi_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    records = await run_experiment(
        ExperimentConfig(
            name="exp",
            mode="analyze",
            model="groq",
            cases=[RunCase(citta="Roma", zona="Centro")],
            context_format="per_classe",
        ),
        executor=FakeProfiler(),
        llm_client=_Recording(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )

    assert records[0].provenance.context_format == "per_classe"
    assert "raggruppati per classe TERMINUS" in visti[0]


async def test_run_experiment_default_keeps_the_historical_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un esperimento che non nomina il formato non deve muoversi di un byte."""
    from crime_risk_analyzer.llm.client import LLMResponse
    from tests.eval._doubles import FakeProfiler, default_llm_response

    visti: list[str] = []

    class _Recording:
        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            visti.append(user_content)
            return default_llm_response()

    scrivi_snapshot(
        snapshot_path(tmp_path, make_snapshot_key("Roma", "Centro")), _sample_pois()
    )
    from crime_risk_analyzer.rag import retrieval

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode_fixture)

    records = await run_experiment(
        ExperimentConfig(
            name="exp",
            mode="analyze",
            model="groq",
            cases=[RunCase(citta="Roma", zona="Centro")],
        ),
        executor=FakeProfiler(),
        llm_client=_Recording(),
        results_dir=tmp_path,
        code_commit="abc",
        ontology_hash="def",
    )

    assert records[0].provenance.context_format == "per_poi"
    assert "POI RILEVANTI:" in visti[0]


def test_record_from_response_copies_risk_models() -> None:
    """_record_from_response copia risk_models dalla response nel RunRecord."""
    from crime_risk_analyzer.rag.generation import Repro

    # Costruisci una AnalyzeResponse fittizia con risk_models non vuoti.
    risk_model = RiskModel(poi_id="node/1", poi="Banca A", risks=[])

    resp = AnalyzeResponse(
        citta="Roma",
        zona_normalizzata="Centro",
        poi=[],
        risk_models=[risk_model],
        narrativa="Analisi.",
        confidence_summary=ConfidenceSummary(verificato=0, da_confermare=0),
        llm_used="claude-sonnet-4-6",
        latenza_ms=100,
        repro=Repro(temperature=0.0, seed=0, prompt_hash="p"),
        cache_hit=False,
        contesto_hash="h",
        zona_geo=ZonaGeo(
            lat=41.0,
            lon=12.0,
            bbox_min_lat=40.9,
            bbox_min_lon=11.9,
            bbox_max_lat=41.1,
            bbox_max_lon=12.1,
        ),
    )

    # Chiama _record_from_response direttamente.
    record = _record_from_response(
        run_id="r",
        snapshot_id="s",
        config=ExperimentConfig(name="exp", mode="analyze", model="claude", cases=[]),
        case=RunCase(citta="Roma", zona="Centro"),
        model_id="claude-sonnet-4-6",
        resp=resp,
        code_commit="a",
        ontology_hash="b",
        snapshot_catturato_il=None,
        snapshot_configurazione_canonica=None,
    )

    # Verifica che il record porti i risk_models.
    assert len(record.risk_models) == 1
    assert record.risk_models[0].poi_id == "node/1"
