"""Le due fasi di ``/analyze`` (#259) e le rotte che le espongono (#292).

Fase 1: risposta strutturata veloce, narrativa non ancora generata. Fase 2:
``POST /analyze/narrativa`` genera il testo sul contesto scaldato dalla fase 1.
"""

from __future__ import annotations

import inspect
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from crime_risk_analyzer import zone_context_cache
from crime_risk_analyzer.config import Settings, get_settings
from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.llm.client import LLMError, LLMResponse, get_llm_client
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.poi_narrative import ContextMismatchError
from crime_risk_analyzer.rag import retrieval
from crime_risk_analyzer.rag.generation import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_REQUEST_TOKEN_BUDGET,
)
from crime_risk_analyzer.sparql_module.query_executor import get_executor

_BANK = PoiRiskProfile(
    terminus_class="Bank",
    hazards=["Bank_robbery"],
    vulnerabilities=["Accesso non controllato"],
    sparql_paths=["Bank → havingHazard → Bank_robbery"],
)


class _FakeProfiler:
    def profile(self, terminus_class: str) -> PoiRiskProfile:
        return {"Bank": _BANK}.get(
            terminus_class, PoiRiskProfile(terminus_class=terminus_class)
        )


def _pois(citta: str) -> list[Poi]:
    return [
        {
            "id": "node/1",
            "name": "Banca A",
            "lat": 41.8900,
            "lon": 12.4920,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": citta,
        },
    ]


def _pois_densi(citta: str) -> list[Poi]:
    """Cattura OSM diversa da :func:`_pois`: un POI in piu', anch'esso con rischi.

    Serve a due scopi: e' la cattura DIVERGENTE dei test su #242 (fra le due fasi
    OSM cambia, o il cap ``MAX_POIS`` fa entrare un punto) ed e' il minimo per cui
    ``build_context_str`` puo' troncare il contesto (con un solo POI non tronca
    mai), che i test sui tetti di token richiedono.
    """
    return [
        *_pois(citta),
        {
            "id": "node/2",
            "name": "Banca B",
            "lat": 41.8901,
            "lon": 12.4921,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": citta,
        },
    ]


async def _geo_source(citta: str, zona: str) -> GeoResult:
    return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))


async def _poi_source(bbox: Bbox, citta: str) -> list[Poi]:
    return _pois(citta)


async def _poi_source_divergente(bbox: Bbox, citta: str) -> list[Poi]:
    return _pois_densi(citta)


async def test_fast_response_has_no_narrativa_yet() -> None:
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast

    out = await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    assert out.narrativa is None
    assert out.fallback is False
    assert len(out.poi) == 1
    assert out.poi[0].id == "node/1"
    assert (out.zona_geo.lat, out.zona_geo.lon) == (41.89, 12.49)
    assert out.messaggio is None


async def test_fast_response_zero_poi_has_explicit_message() -> None:
    """#260: zero POI in copertura ma zona geocodificata — la response porta
    ``zona_geo`` (per ricentrare la mappa) e un ``messaggio`` esplicito che
    distingue questo caso da una zona non trovata."""
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast

    async def _no_poi(bbox: Bbox, citta: str) -> list[Poi]:
        return []

    out = await run_analysis_fast(
        "Roma",
        "Zona senza POI",
        executor=_FakeProfiler(),
        poi_source=_no_poi,
        geo_source=_geo_source,
    )
    assert out.poi == []
    assert (out.zona_geo.lat, out.zona_geo.lon) == (41.89, 12.49)
    assert out.messaggio is not None


async def test_phase1_then_phase2_zero_poi_narrativa_reale_annulla_messaggio() -> None:
    """#260 (reperto review): la fase 2 ricalcola ``messaggio`` da zero, non
    eredita quello della fase 1 — se l'LLM scrive comunque prosa reale su un
    contesto senza POI, un ``messaggio`` che lascia intendere "nulla da vedere"
    accanto a quella narrativa sarebbe un'informazione contraddittoria per chi
    legge la response finale."""
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import (
        run_analysis_fast,
        run_zone_narrative,
    )

    async def _no_poi(bbox: Bbox, citta: str) -> list[Poi]:
        return []

    fase1 = await run_analysis_fast(
        "Roma",
        "Zona senza POI fase2",
        executor=_FakeProfiler(),
        poi_source=_no_poi,
        geo_source=_geo_source,
    )
    assert fase1.poi == []
    assert fase1.narrativa is None
    assert fase1.messaggio is not None

    fase2 = await run_zone_narrative(
        "Roma",
        "Zona senza POI fase2",
        contesto_hash=fase1.contesto_hash,
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
    )
    assert fase2.narrativa != ""
    assert fase2.messaggio is None


async def test_phase1_then_phase2_zero_poi_llm_fallback_keeps_message() -> None:
    """Stessa sequenza fase1->fase2 su zona vuota, ma la fase 2 cade sull'LLM:
    senza narrativa reale, il messaggio esplicito resta l'unica informazione
    disponibile — non deve sparire solo perche' e' la seconda chiamata."""
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import (
        run_analysis_fast,
        run_zone_narrative,
    )

    async def _no_poi(bbox: Bbox, citta: str) -> list[Poi]:
        return []

    fase1 = await run_analysis_fast(
        "Roma",
        "Zona senza POI fase2 fallback",
        executor=_FakeProfiler(),
        poi_source=_no_poi,
        geo_source=_geo_source,
    )
    fase2 = await run_zone_narrative(
        "Roma",
        "Zona senza POI fase2 fallback",
        contesto_hash=fase1.contesto_hash,
        executor=_FakeProfiler(),
        llm_client=_RaisingLLMClient(),
    )
    assert fase2.narrativa == ""
    assert fase2.fallback is True
    assert fase2.messaggio is not None


async def test_fast_response_warms_the_zone_context_cache() -> None:
    """Il contesto resta depositato: /analyze/narrativa e /analyze/poi non devono
    rifare Overpass (#232). E' la fase 1 l'unica a scaldare la cache — il
    percorso di valutazione (`run_analysis`) non la tocca."""
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast

    await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    assert zone_context_cache.get("Roma", "Colosseo") is not None


async def test_fast_response_contesto_hash_matches_the_cached_context() -> None:
    """L'impronta restituita è quella che /analyze/narrativa dovrà ricevere
    indietro per passare la verifica (#242)."""
    zone_context_cache.clear()
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast
    from crime_risk_analyzer.context_fingerprint import fingerprint

    out = await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    cached = zone_context_cache.get("Roma", "Colosseo")
    assert cached is not None
    assert out.contesto_hash == fingerprint(cached["retrieval"]["pois"])


class _FakeLLMClient:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        return LLMResponse(
            text=(
                "Sintesi.\n\n[ONTOLOGIA]\nRischio rapina.\n\n"
                "[CONTESTO]\nZona centrale.\n"
            ),
            llm_used="test-model",
            tokens_input=5,
            tokens_output=8,
            cache_hit=False,
            temperature=0.2,
            seed=42,
            prompt_hash="h",
        )


class _RaisingLLMClient:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        raise LLMError("provider giu'")


async def _prime_cache() -> str:
    from crime_risk_analyzer.analyze_narrative import run_analysis_fast

    zone_context_cache.clear()
    resp = await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    assert resp.contesto_hash is not None
    return resp.contesto_hash


async def test_zone_narrative_returns_text_for_the_cached_zone() -> None:
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    contesto_hash = await _prime_cache()
    out = await run_zone_narrative(
        "Roma",
        "Colosseo",
        contesto_hash=contesto_hash,
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
    )
    assert out.narrativa != ""
    assert out.fallback is False


async def test_zone_narrative_cache_hit_does_not_touch_overpass() -> None:
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    contesto_hash = await _prime_cache()

    async def _exploding(bbox: Bbox, citta: str) -> list[Poi]:
        raise AssertionError("Overpass non deve essere chiamato su cache hit")

    out = await run_zone_narrative(
        "Roma",
        "Colosseo",
        contesto_hash=contesto_hash,
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_exploding,
    )
    assert out.narrativa != ""


async def test_zone_narrative_cold_cache_rebuilds_the_context() -> None:
    """TTL scaduto fra le due fasi: con OSM invariato la narrativa esce comunque.

    E' il percorso che la rotta rende raggiungibile per davvero (#292): il
    frontend puo' chiedere il testo molto dopo l'analisi. La ricostruzione
    coincide col contesto mostrato, quindi passa la verifica di #242, e il
    contesto torna in cache per i clic successivi sui POI.
    """
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    contesto_hash = await _prime_cache()
    zone_context_cache.clear()
    out = await run_zone_narrative(
        "Roma",
        "Colosseo",
        contesto_hash=contesto_hash,
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    assert out.narrativa != ""
    assert zone_context_cache.get("Roma", "Colosseo") is not None


async def test_zone_narrative_cold_cache_divergent_rebuild_refuses() -> None:
    """A cache fredda la ricostruzione da' una lista di POI diversa da quella a
    schermo -> rifiuto, non prosa silenziosa su un altro vicinato (#242).

    E il contesto rifiutato NON entra in cache: nessuno l'ha mai avuto davanti e
    occuperebbe uno slot sfrattando, a cache piena, una zona valida (stessa
    scelta di ``run_poi_narrative``).
    """
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    contesto_hash = await _prime_cache()
    zone_context_cache.clear()
    with pytest.raises(ContextMismatchError):
        await run_zone_narrative(
            "Roma",
            "Colosseo",
            contesto_hash=contesto_hash,
            executor=_FakeProfiler(),
            llm_client=_FakeLLMClient(),
            poi_source=_poi_source_divergente,
            geo_source=_geo_source,
        )
    assert zone_context_cache.get("Roma", "Colosseo") is None


async def test_zone_narrative_context_mismatch_raises() -> None:
    """Zona ri-analizzata fra le due chiamate (#242): stessa guardia di /analyze/poi."""
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    await _prime_cache()
    with pytest.raises(ContextMismatchError):
        await run_zone_narrative(
            "Roma",
            "Colosseo",
            contesto_hash="hash-vecchio-non-valido",
            executor=_FakeProfiler(),
            llm_client=_FakeLLMClient(),
        )


async def test_zone_narrative_llm_error_falls_back_without_raising() -> None:
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    contesto_hash = await _prime_cache()
    out = await run_zone_narrative(
        "Roma",
        "Colosseo",
        contesto_hash=contesto_hash,
        executor=_FakeProfiler(),
        llm_client=_RaisingLLMClient(),
    )
    assert out.fallback is True
    assert out.narrativa == ""


async def test_zone_narrative_dichiara_il_modello_che_ha_scritto() -> None:
    """Quale dei due modelli ha prodotto la narrativa deve essere osservabile.

    Lo switch manuale Claude/Groq (`LLM_PROVIDER`, mai failover automatico) è il
    perno del confronto della tesi: dopo lo split (#292) la fase 1 espone un
    ``llm_used`` vuoto per costruzione e, senza questo campo, nessuna delle due
    risposte direbbe più chi ha scritto il testo che si sta leggendo. Stessa
    fonte del ramo LLM di ``run_analysis``: il ``llm_used`` del generation layer.
    """
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    contesto_hash = await _prime_cache()
    out = await run_zone_narrative(
        "Roma",
        "Colosseo",
        contesto_hash=contesto_hash,
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
    )
    assert out.llm_used == "test-model"


async def test_zone_narrative_fallback_non_attribuisce_il_testo_a_un_modello() -> None:
    """Nel fallback nessun modello ha scritto nulla: ``llm_used`` resta vuoto,
    come in ``_structured_response`` per il ramo senza LLM."""
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative

    contesto_hash = await _prime_cache()
    out = await run_zone_narrative(
        "Roma",
        "Colosseo",
        contesto_hash=contesto_hash,
        executor=_FakeProfiler(),
        llm_client=_RaisingLLMClient(),
    )
    assert out.fallback is True
    assert out.llm_used == ""


def test_zone_narrative_response_has_no_numeric_danger_scoring_field() -> None:
    """Stesso vincolo di `PoiNarrativeResponse` (_project.md §Vincoli): l'insieme
    esatto impedisce di intrufolare un punteggio numerico di pericolosità.

    ``messaggio`` (#260) è testo esplicativo condizionato su POI/narrativa
    vuoti, non un punteggio: aggiunta legittima allo stesso titolo di
    ``AnalyzeResponse.messaggio``."""
    from crime_risk_analyzer.analyze_narrative import ZoneNarrativeResponse

    assert set(ZoneNarrativeResponse.model_fields) == {
        "narrativa",
        "narrativa_fonti",
        "llm_used",
        "tokens_input",
        "tokens_output",
        "latenza_ms",
        "repro",
        "fallback",
        "messaggio",
    }


# --- #119: il tetto sulla ``domanda`` vive dove vive il campo ---
# Era ``AnalyzeRequest`` a portare la domanda; dopo lo split (#292) la fase 1 non
# chiama il modello e il campo è rimasto solo qui, quindi qui va il bound su
# token/costo/superficie di prompt-injection.


def test_zone_narrative_request_rejects_overlong_domanda() -> None:
    from crime_risk_analyzer.analyze_narrative import ZoneNarrativeRequest

    with pytest.raises(ValidationError):
        ZoneNarrativeRequest(
            citta="Roma", zona="Colosseo", contesto_hash="0" * 64, domanda="x" * 501
        )


def test_zone_narrative_request_accepts_domanda_at_max_length() -> None:
    from crime_risk_analyzer.analyze_narrative import ZoneNarrativeRequest

    req = ZoneNarrativeRequest(
        citta="Roma", zona="Colosseo", contesto_hash="0" * 64, domanda="x" * 500
    )
    assert req.domanda is not None
    assert len(req.domanda) == 500


# --- #292: le due fasi sulle rotte HTTP ---
# Stessa impalcatura dei test di ``/analyze/poi``: doppi via ``dependency_overrides``,
# I/O (geocoding/Overpass) sostituito con monkeypatch, nessuna rete.


class _RecordingLLMClient:
    """Spia: registra i prompt che la rotta fa arrivare al modello."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        self.calls.append((system_prompt, user_content))
        return LLMResponse(
            text="Sintesi.\n\n[ONTOLOGIA]\nRischio rapina.\n",
            llm_used="test-model",
            tokens_input=5,
            tokens_output=8,
            cache_hit=False,
            temperature=0.2,
            seed=42,
            prompt_hash="h",
        )


def _patch_io(monkeypatch: pytest.MonkeyPatch, *, densa: bool = False) -> None:
    """Sostituisce geocoding e Overpass per i test delle rotte HTTP."""

    def _fake_geocode(zona: str, citta: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois_densi(citta) if densa else _pois(citta)

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode)
    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)


def _client(llm: object = None, settings: Settings | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_executor] = lambda: _FakeProfiler()
    app.dependency_overrides[get_llm_client] = lambda: llm or _FakeLLMClient()
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app, raise_server_exceptions=False)


def _analizza(client: TestClient) -> str:
    """Fase 1: analisi di zona; restituisce l'impronta, come farebbe il client."""
    zone_context_cache.clear()
    zona = cast(
        httpx.Response,
        client.post("/analyze", json={"citta": "Roma", "zona": "Colosseo"}),  # pyright: ignore[reportUnknownMemberType]
    )
    assert zona.status_code == 200
    return str(zona.json()["contesto_hash"])


def _narrativa(
    client: TestClient, contesto_hash: str, *, domanda: str | None = None
) -> httpx.Response:
    """Fase 2: la stessa chiamata che fa il frontend dopo aver reso i dati."""
    body: dict[str, str] = {
        "citta": "Roma",
        "zona": "Colosseo",
        "contesto_hash": contesto_hash,
    }
    if domanda is not None:
        body["domanda"] = domanda
    return cast(
        httpx.Response,
        client.post("/analyze/narrativa", json=body),  # pyright: ignore[reportUnknownMemberType]
    )


def test_endpoint_completa_la_narrativa_lasciata_aperta_dalla_fase_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Il percorso reale del prodotto: ``/analyze`` senza testo, poi il testo.

    Le due asserzioni stanno nello stesso test di proposito: e' la sequenza che
    il frontend esegue, e ``narrativa=None`` della fase 1 ha senso solo se la
    fase 2 la completa.
    """
    _patch_io(monkeypatch)
    client = _client()
    zona = cast(
        httpx.Response,
        client.post("/analyze", json={"citta": "Roma", "zona": "Colosseo"}),  # pyright: ignore[reportUnknownMemberType]
    )
    assert zona.status_code == 200
    assert zona.json()["narrativa"] is None

    resp = _narrativa(client, str(zona.json()["contesto_hash"]))

    assert resp.status_code == 200
    body = resp.json()
    assert body["narrativa"] != ""
    assert body["narrativa_fonti"]["ontologia"] != ""
    assert body["fallback"] is False
    # Sul filo, non solo nel modello: e' la risposta di questa rotta l'unico posto
    # in cui si puo' vedere quale dei due provider ha scritto il testo.
    assert body["llm_used"] == "test-model"


def test_endpoint_cache_calda_non_richiama_overpass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La fase 2 riusa il contesto scaldato dalla fase 1 (#232): due chiamate
    HTTP, una sola cattura OSM — altrimenti lo split costerebbe una chiamata in
    piu' a un servizio pubblico gratuito."""
    _patch_io(monkeypatch)
    client = _client()
    contesto_hash = _analizza(client)

    async def _esplode(*args: object, **kwargs: object) -> list[Poi]:
        raise AssertionError("Overpass non deve essere chiamato in fase 2")

    monkeypatch.setattr(retrieval, "fetch_pois", _esplode)
    resp = _narrativa(client, contesto_hash)

    assert resp.status_code == 200
    assert resp.json()["narrativa"] != ""


def test_endpoint_returns_409_for_mismatched_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#242 sul percorso di zona: impronta che non identifica il contesto -> 409
    con invito a rilanciare, non una narrativa dall'aria normale. Stesso registro
    (handler centrale) di ``/analyze/poi``."""
    _patch_io(monkeypatch)
    client = _client()
    _analizza(client)

    resp = _narrativa(client, "0" * 64)

    assert resp.status_code == 409
    assert resp.json()["detail"]["errore"] == "contesto_disallineato"
    assert "rilancia" in resp.json()["detail"]["messaggio"]


def test_endpoint_409_non_spende_una_chiamata_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Il rifiuto precede la generazione: un 409 non costa token."""
    _patch_io(monkeypatch)
    llm = _RecordingLLMClient()
    client = _client(llm=llm)
    _analizza(client)

    resp = _narrativa(client, "0" * 64)

    assert resp.status_code == 409
    assert llm.calls == []


def test_endpoint_requires_the_context_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Il campo e' obbligatorio: senza impronta non esiste una richiesta valida,
    altrimenti la garanzia di #242 sarebbe opt-in anche qui."""
    _patch_io(monkeypatch)
    client = _client()
    _analizza(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/narrativa", json={"citta": "Roma", "zona": "Colosseo"}
        ),
    )
    assert resp.status_code == 422


# --- Validazione del body: gli stessi 422 pre-I/O che ha ``/analyze`` ---
# La rotta ricostruisce il contesto a cache fredda, quindi un body fuori bound che
# non fosse respinto dalla validazione costerebbe geocoding e Overpass.


def test_endpoint_rejects_overlong_citta(monkeypatch: pytest.MonkeyPatch) -> None:
    """``citta`` oltre max_length=100 -> 422, come su ``/analyze``: e' una
    stringa del client che finisce nella chiave di cache e nella query
    Nominatim (#170)."""
    _patch_io(monkeypatch)
    client = _client()
    contesto_hash = _analizza(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/narrativa",
            json={
                "citta": "A" * 101,
                "zona": "Colosseo",
                "contesto_hash": contesto_hash,
            },
        ),
    )
    assert resp.status_code == 422


def test_endpoint_rejects_overlong_zona(monkeypatch: pytest.MonkeyPatch) -> None:
    """``zona`` oltre max_length=200 -> 422 (stesso bound di ``AnalyzeRequest``)."""
    _patch_io(monkeypatch)
    client = _client()
    contesto_hash = _analizza(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/narrativa",
            json={
                "citta": "Roma",
                "zona": "z" * 201,
                "contesto_hash": contesto_hash,
            },
        ),
    )
    assert resp.status_code == 422


def test_endpoint_rejects_overlong_domanda(monkeypatch: pytest.MonkeyPatch) -> None:
    """``domanda`` oltre max_length=500 -> 422 sulla ROTTA, non solo nel modello.

    Il bound di ``ZoneNarrativeRequest`` e' verificato altrove sul modello, ma la
    garanzia che interessa (#119) e' che il tetto valga sul filo: la domanda e'
    l'unico input NON fidato che raggiunge il prompt, quindi il rifiuto deve
    arrivare in validazione — prima della ricostruzione del contesto a cache
    fredda e prima di spendere token su una domanda smisurata.
    """
    _patch_io(monkeypatch)
    llm = _RecordingLLMClient()
    client = _client(llm=llm)
    contesto_hash = _analizza(client)

    resp = _narrativa(client, contesto_hash, domanda="x" * 501)

    assert resp.status_code == 422
    assert llm.calls == []


def test_endpoint_rejects_overlong_contesto_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``contesto_hash`` oltre max_length=64 -> 422 prima di ogni I/O.

    L'impronta e' un digest sha256 (64 caratteri esadecimali): un valore piu'
    lungo non puo' identificare alcun contesto, e respingerlo alla validazione
    evita che a cache fredda la rotta paghi una cattura Overpass per poi
    rifiutare comunque.
    """
    _patch_io(monkeypatch)
    client = _client()
    _analizza(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/narrativa",
            json={"citta": "Roma", "zona": "Colosseo", "contesto_hash": "0" * 65},
        ),
    )
    assert resp.status_code == 422


def test_endpoint_rejects_too_short_contesto_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``contesto_hash`` sotto min_length=64 -> 422, non 409.

    Prima il campo dichiarava solo un tetto e un'impronta corta arrivava intatta
    fino al confronto con la cache, uscendo come «contesto disallineato»: un
    responso piu' caro del dovuto, perche' a cache fredda la rotta ricostruisce
    il contesto (una cattura Overpass) per poi rifiutare un valore che non aveva
    la forma di un digest sha256. Con ``min_length=64`` la forma si respinge
    prima di ogni I/O; il 409 resta per il caso che merita, l'impronta ben
    formata che identifica un ALTRO contesto.
    """
    _patch_io(monkeypatch)
    client = _client()
    _analizza(client)
    resp = _narrativa(client, "0" * 8)
    assert resp.status_code == 422


def test_endpoint_domanda_reaches_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """#119 dopo lo split (#292): la domanda arriva allo user_content da QUI.

    Era la fase 1 a portarla al prompt; ora la fase 1 non chiama il modello,
    quindi il vettore #119 vive su questa rotta (e il client deve ripeterla).
    """
    _patch_io(monkeypatch)
    llm = _RecordingLLMClient()
    client = _client(llm=llm)
    contesto_hash = _analizza(client)

    resp = _narrativa(client, contesto_hash, domanda="Rischi di notte?")

    assert resp.status_code == 200
    assert len(llm.calls) == 1
    _system, user = llm.calls[0]
    assert "Rischi di notte?" in user


def test_endpoint_without_domanda_omits_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Senza ``domanda`` lo user_content non porta la sezione dedicata."""
    _patch_io(monkeypatch)
    llm = _RecordingLLMClient()
    client = _client(llm=llm)
    contesto_hash = _analizza(client)

    assert _narrativa(client, contesto_hash).status_code == 200

    _system, user = llm.calls[0]
    assert "DOMANDA UTENTE" not in user


def test_endpoint_llm_down_returns_200_with_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider giu' -> 200 con ``fallback=True`` e narrativa vuota, non un 500:
    i dati strutturati sono gia' a schermo dalla fase 1 e restano validi."""
    _patch_io(monkeypatch)
    client = _client(llm=_RaisingLLMClient())
    contesto_hash = _analizza(client)

    resp = _narrativa(client, contesto_hash)

    assert resp.status_code == 200
    assert resp.json()["fallback"] is True
    assert resp.json()["narrativa"] == ""


def _user_content_di_fase_2(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> str:
    """Esegue le due fasi con le ``settings`` date e restituisce lo user_content."""
    _patch_io(monkeypatch, densa=True)
    llm = _RecordingLLMClient()
    client = _client(llm=llm, settings=settings)
    contesto_hash = _analizza(client)
    assert _narrativa(client, contesto_hash).status_code == 200
    return llm.calls[0][1]


def test_endpoint_propaga_il_budget_di_richiesta_dalle_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#210 dopo lo split: il tetto di token viene dalla config, non dai default.

    La fase 2 e' ormai l'unica chiamata a ``generate_analysis`` del prodotto:
    se la rotta non propagasse ``Settings``, il tuning del TPM da env sarebbe
    silenziosamente ignorato. I default di modulo COINCIDONO con quelli di
    ``Settings``, quindi solo un valore diverso dal default rende visibile la
    differenza: con un budget minuscolo il contesto va troncato.
    """
    user = _user_content_di_fase_2(monkeypatch, Settings(llm_request_token_budget=1))

    assert "piu' rilevanti su 2" in user


def test_endpoint_propaga_i_max_tokens_dalle_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anche i token riservati all'OUTPUT arrivano da ``Settings``: entrano nel
    calcolo dell'allowance dello user_content, quindi un valore enorme deve
    stringere il contesto tanto quanto un budget minuscolo."""
    user = _user_content_di_fase_2(monkeypatch, Settings(llm_max_tokens=100_000))

    assert "piu' rilevanti su 2" in user


def test_endpoint_response_never_contains_a_danger_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guardia anti-scoring estesa alla nuova rotta (#184)."""
    _patch_io(monkeypatch)
    client = _client()
    contesto_hash = _analizza(client)

    resp = _narrativa(client, contesto_hash)

    assert resp.status_code == 200
    payload = resp.text.lower()
    for vietato in ("punteggio", "score", "livello di rischio", "pericolosit"):
        assert vietato not in payload


# --- #292: il prompt della valutazione e quello del prodotto non devono divergere ---
# I due percorsi chiamano ``generate_analysis`` da moduli diversi e con tetti di
# token che arrivano da posti diversi: ``eval/harness`` non li passa mai (default
# di modulo), la rotta li propaga da ``Settings``. La parita' che i numeri della
# tesi presuppongono non e' quindi un fatto sui default, ma la SIMMETRIA dei
# parametri: a tetti uguali, prompt uguale. I test qui sotto la provano ai default
# E fuori dai default, mostrano che i tetti fuori default il prompt li sente
# davvero (altrimenti la prova sarebbe vacua) e che a tetti diversi la divergenza
# si vede — cioe' che questa rete si strapperebbe, invece di restare verde.

#: ``(request_token_budget, max_tokens)``: i due tetti che modellano il prompt.
_Tetti = tuple[int, int]

#: I tetti che entrambi i percorsi usano quando nessuno li passa: e' la coppia
#: con cui gira ``eval/harness`` e, via ``Settings``, quella della rotta a config
#: vuota (l'uguaglianza fra i due la fissa
#: ``test_i_due_percorsi_partono_dagli_stessi_tetti``).
_TETTI_DEFAULT: _Tetti = (DEFAULT_REQUEST_TOKEN_BUDGET, DEFAULT_MAX_TOKENS)

#: Coppia FUORI default scelta perche' il prompt la sente: con un budget minuscolo
#: l'allowance dello user_content si azzera e il contesto va troncato (cfr. i test
#: sulla propagazione da ``Settings``). Il caso realistico e' un
#: ``LLM_REQUEST_TOKEN_BUDGET`` abbassato in produzione per stare sotto il TPM.
_TETTI_STRETTI: _Tetti = (1, 900)


async def _prompt_del_prodotto(domanda: str | None, tetti: _Tetti) -> tuple[str, str]:
    """Prompt che il PRODOTTO fa arrivare al modello: fase 1 + ``/analyze/narrativa``.

    Due POI (``_poi_source_divergente``) perche' e' il minimo in cui contano
    ordine e troncamento del contesto.
    """
    from crime_risk_analyzer.analyze_narrative import (
        run_analysis_fast,
        run_zone_narrative,
    )

    budget, max_tokens = tetti
    zone_context_cache.clear()
    fase_1 = await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_poi_source_divergente,
        geo_source=_geo_source,
    )
    spia = _RecordingLLMClient()
    await run_zone_narrative(
        "Roma",
        "Colosseo",
        contesto_hash=fase_1.contesto_hash,
        executor=_FakeProfiler(),
        llm_client=spia,
        domanda=domanda,
        request_token_budget=budget,
        max_tokens=max_tokens,
    )

    assert len(spia.calls) == 1
    return spia.calls[0]


async def _prompt_della_valutazione(
    domanda: str | None, tetti: _Tetti
) -> tuple[str, str]:
    """Prompt che la VALUTAZIONE misura: ``run_analysis``, l'entry point di
    ``eval/harness``.

    I tetti sono espliciti anche qui: il harness li lascia ai default, ma quello
    che si vuole provare e' la simmetria del parametro, non il suo default (che
    ha il suo test).
    """
    from crime_risk_analyzer.orchestrator import run_analysis

    budget, max_tokens = tetti
    spia = _RecordingLLMClient()
    await run_analysis(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        llm_client=spia,
        poi_source=_poi_source_divergente,
        geo_source=_geo_source,
        domanda=domanda,
        request_token_budget=budget,
        max_tokens=max_tokens,
    )

    assert len(spia.calls) == 1
    return spia.calls[0]


@pytest.mark.parametrize(
    "domanda", [None, "Rischi di notte?"], ids=["senza-domanda", "con-domanda"]
)
@pytest.mark.parametrize(
    "tetti",
    [
        pytest.param(_TETTI_DEFAULT, id="tetti-default"),
        pytest.param(_TETTI_STRETTI, id="tetti-non-default"),
    ],
)
async def test_prompt_del_prodotto_identico_a_quello_della_valutazione(
    tetti: _Tetti, domanda: str | None
) -> None:
    """A parità di contesto grounded E DI TETTI i due percorsi mandano lo STESSO
    prompt.

    Dopo lo split (#292) la narrativa del prodotto nasce in
    ``run_zone_narrative``, mentre le metriche di grounding/allucinazione
    (``eval/harness``) misurano quella di ``run_analysis``: due chiamate a
    ``generate_analysis`` in moduli diversi. Oggi coincidono byte per byte, ma
    nulla lo impone — e se un domani uno solo dei due cambiasse (un parametro, un
    ``context_format``, una domanda trattata in modo diverso) i numeri della tesi
    parlerebbero di un prompt che l'utente non riceve mai, in silenzio. Questo
    test è quella rete: non verifica il CONTENUTO del prompt (lo fanno i test del
    generation layer), solo che i due percorsi restino d'accordo.

    I tetti sono ESPLICITI e uguali sui due lati, ai default e fuori dai default:
    così la parità che si osserva è quella della simmetria dei parametri, non la
    coincidenza fortunata fra i default di modulo e quelli di ``Settings`` (che è
    un fatto a parte, e ha il suo test). Con e senza ``domanda`` perché l'input
    non fidato entra nello user_content solo su un ramo.
    """
    prodotto = await _prompt_del_prodotto(domanda, tetti)
    valutazione = await _prompt_della_valutazione(domanda, tetti)

    assert prodotto == valutazione


async def test_i_tetti_stretti_cambiano_davvero_il_prompt() -> None:
    """La parità a tetti non default non è una prova vacua: quei valori il prompt
    li sente (contesto troncato), quindi passarli su un lato solo si vedrebbe."""
    ai_default = await _prompt_del_prodotto(None, _TETTI_DEFAULT)
    stretti = await _prompt_del_prodotto(None, _TETTI_STRETTI)

    assert stretti != ai_default
    assert "piu' rilevanti su 2" in stretti[1]


async def test_prompt_diverge_se_i_due_percorsi_hanno_tetti_diversi() -> None:
    """Controllo negativo: a tetti diversi i due prompt divergono e il confronto
    di sopra andrebbe ROSSO.

    È il caso che la parità ai soli default non intercetterebbe: la rotta propaga
    ``Settings`` (un ``LLM_REQUEST_TOKEN_BUDGET`` configurato in produzione), il
    harness resta ai default di modulo. Serve a dimostrare che il test di parità
    misura la simmetria dei parametri e non l'uguaglianza di due prompt che
    sarebbero identici comunque.
    """
    prodotto = await _prompt_del_prodotto(None, _TETTI_STRETTI)
    valutazione = await _prompt_della_valutazione(None, _TETTI_DEFAULT)

    assert prodotto != valutazione


def test_i_due_percorsi_partono_dagli_stessi_tetti() -> None:
    """L'altra metà della garanzia: i tetti di partenza dei due percorsi coincidono.

    La simmetria dei parametri (test sopra) dà la parità solo se i valori che i
    due lati ricevono sono gli stessi, e non lo sono per costruzione: il harness
    non li passa (default di ``run_analysis``), la rotta propaga ``Settings``.
    Qui si fissa la catena ``run_zone_narrative`` = ``run_analysis`` =
    ``Settings`` = default di modulo, che un cambio di uno solo dei tre punti
    romperebbe in silenzio (stesso presidio di
    ``test_max_tokens_default_is_synced_across_modules``). Usa i DEFAULT dei
    campi, non un'istanza ``Settings()``, per non dipendere da un ``.env`` locale.

    Resta fuori dalla portata dei test il caso in cui ``LLM_REQUEST_TOKEN_BUDGET``/
    ``LLM_MAX_TOKENS`` siano davvero configurati da env: lì i due prompt divergono
    per davvero, ed è una proprietà del design (le run di valutazione sono pinnate
    ai default di modulo, non alla config della macchina che le lancia).
    """
    from crime_risk_analyzer.analyze_narrative import run_zone_narrative
    from crime_risk_analyzer.orchestrator import run_analysis

    prodotto = inspect.signature(run_zone_narrative).parameters
    valutazione = inspect.signature(run_analysis).parameters

    assert (
        prodotto["request_token_budget"].default
        == valutazione["request_token_budget"].default
        == Settings.model_fields["llm_request_token_budget"].default
        == DEFAULT_REQUEST_TOKEN_BUDGET
    )
    assert (
        prodotto["max_tokens"].default
        == valutazione["max_tokens"].default
        == Settings.model_fields["llm_max_tokens"].default
        == DEFAULT_MAX_TOKENS
    )
