"""Endpoint e orchestrazione della narrativa per POI (#197), offline."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer import zone_context_cache
from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.llm.client import LLMError, LLMResponse, get_llm_client
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.orchestrator import run_analysis
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.poi_narrative import (
    ContextMismatchError,
    PoiNarrativeResponse,
    PoiNotFoundError,
    run_poi_narrative,
)
from crime_risk_analyzer.rag import retrieval
from crime_risk_analyzer.sparql_module.query_executor import get_executor

_POI_ID = "node/1"

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


class _FakeLLMClient:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        return LLMResponse(
            text=(
                "Sintesi.\n\n"
                "[ONTOLOGIA]\nRischio rapina.\n\n"
                "[CONTESTO]\nVicino a una scuola.\n"
            ),
            llm_used="claude-sonnet-4-6",
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


def _pois(citta: str) -> list[Poi]:
    return [
        {
            "id": _POI_ID,
            "name": "Banca A",
            "lat": 41.8900,
            "lon": 12.4920,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": citta,
        },
        {
            "id": "node/2",
            "name": "Liceo Cavour",
            "lat": 41.8901,
            "lon": 12.4921,
            "osm_tags": "amenity=school",
            "terminus_class": "School",
            "citta": citta,
        },
    ]


async def _geo_source(citta: str, zona: str) -> GeoResult:
    return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))


async def _poi_source(bbox: Bbox, citta: str) -> list[Poi]:
    return _pois(citta)


async def _prime_cache() -> str:
    """Popola la cache del contesto di zona eseguendo /analyze con i doppi.

    Restituisce l'impronta del contesto (#242): i test la rimandano come farebbe
    il client, invece di ricalcolarla e finire per testare la funzione contro se
    stessa.
    """
    zone_context_cache.clear()
    resp = await run_analysis(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    return resp.contesto_hash


def _patch_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sostituisce geocoding e Overpass per i test dell'endpoint HTTP."""

    def _fake_geocode(zona: str, citta: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois(citta)

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode)
    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)


def _client(llm: object = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_executor] = lambda: _FakeProfiler()
    app.dependency_overrides[get_llm_client] = lambda: llm or _FakeLLMClient()
    return TestClient(app, raise_server_exceptions=False)


async def test_returns_narrative_for_a_poi_in_the_cached_zone() -> None:
    contesto_hash = await _prime_cache()
    out = await run_poi_narrative(
        "Roma",
        "Colosseo",
        _POI_ID,
        contesto_hash=contesto_hash,
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
    )
    assert out.poi_id == _POI_ID
    assert out.narrativa != ""
    assert out.fallback is False
    assert [rm.poi for rm in out.risk_models] == ["Banca A"]


async def test_cache_hit_does_not_touch_overpass() -> None:
    """Su hit non si spende una chiamata a un servizio pubblico gratuito (#232)."""
    contesto_hash = await _prime_cache()

    async def _exploding(bbox: Bbox, citta: str) -> list[Poi]:
        raise AssertionError("Overpass non deve essere chiamato su cache hit")

    out = await run_poi_narrative(
        "Roma",
        "Colosseo",
        _POI_ID,
        contesto_hash=contesto_hash,
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_exploding,
    )
    assert out.narrativa != ""


async def test_cold_cache_rebuilds_the_context() -> None:
    """A cache fredda con OSM invariato il click resta utilizzabile (#242): la
    ricostruzione coincide con il contesto mostrato, quindi la narrativa esce.

    Scadenza del TTL riprodotta come la vive il client: l'analisi c'e' stata (e
    l'impronta e' quella), ma la cache non ha piu' il contesto.
    """
    contesto_hash = await _prime_cache()
    zone_context_cache.clear()
    out = await run_poi_narrative(
        "Roma",
        "Colosseo",
        _POI_ID,
        contesto_hash=contesto_hash,
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    assert out.narrativa != ""
    assert zone_context_cache.get("Roma", "Colosseo") is not None


async def test_narrative_context_carries_the_neighbourhood() -> None:
    """Il prompt del POI deve contenere il vicinato: e' cio' che lo distingue."""
    contesto_hash = await _prime_cache()
    seen: list[str] = []

    class _Recording:
        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            seen.append(user_content)
            return LLMResponse(
                text="x",
                llm_used="fake",
                tokens_input=1,
                tokens_output=1,
                cache_hit=False,
                temperature=0.0,
                seed=0,
                prompt_hash="h",
            )

    await run_poi_narrative(
        "Roma",
        "Colosseo",
        _POI_ID,
        contesto_hash=contesto_hash,
        executor=_FakeProfiler(),
        llm_client=_Recording(),
    )
    assert "PUNTO SELEZIONATO: Banca A" in seen[0]
    assert "Liceo Cavour" in seen[0]
    assert "COMPOSIZIONE DELLA ZONA:" in seen[0]


async def test_unknown_poi_id_raises_poi_not_found() -> None:
    """Con un'impronta ALLINEATA un id sconosciuto resta un 404, non un 409: il
    contratto continua a distinguere «il tuo contesto non e' il mio» da «quell'id
    non e' in questo contesto» (#242)."""
    contesto_hash = await _prime_cache()
    with pytest.raises(PoiNotFoundError):
        await run_poi_narrative(
            "Roma",
            "Colosseo",
            "non-esiste",
            contesto_hash=contesto_hash,
            executor=_FakeProfiler(),
            llm_client=_FakeLLMClient(),
        )


async def test_llm_error_falls_back_without_raising() -> None:
    """Stessa politica del percorso di zona: dati strutturati + fallback=True."""
    contesto_hash = await _prime_cache()
    out = await run_poi_narrative(
        "Roma",
        "Colosseo",
        _POI_ID,
        contesto_hash=contesto_hash,
        executor=_FakeProfiler(),
        llm_client=_RaisingLLMClient(),
    )
    assert out.fallback is True
    assert out.narrativa == ""
    assert out.risk_models != []


# --- #242: l'impronta del contesto rende verificabile l'ancoraggio ---


async def _poi_source_divergente(bbox: Bbox, citta: str) -> list[Poi]:
    """Cattura OSM diversa: un POI in piu' rispetto a ``_poi_source``.

    E' il caso reale del difetto (#242): fra l'analisi e il click, OSM cambia o
    il cap MAX_POIS fa entrare un punto, e il vicinato ricostruito non e' quello
    mostrato in mappa.
    """
    return [
        *_pois(citta),
        {
            "id": "node/3",
            "name": "Farmacia Nuova",
            "lat": 41.8902,
            "lon": 12.4922,
            "osm_tags": "amenity=pharmacy",
            "terminus_class": "Pharmacy",
            "citta": citta,
        },
    ]


async def test_cache_calda_con_impronta_diversa_rifiuta() -> None:
    """Il caso che l'issue non prevedeva: la zona e' stata ri-analizzata (altro
    tab, «Rigenera» di zona) e la cache porta un contesto che non e' quello
    mostrato. Senza confronto la narrativa nascerebbe su quell'altro contesto,
    in silenzio."""
    await _prime_cache()
    with pytest.raises(ContextMismatchError):
        await run_poi_narrative(
            "Roma",
            "Colosseo",
            _POI_ID,
            contesto_hash="impronta-di-un-altra-analisi",
            executor=_FakeProfiler(),
            llm_client=_FakeLLMClient(),
        )


async def test_impronta_disallineata_non_spende_una_chiamata_llm() -> None:
    """Il confronto precede la generazione: un rifiuto non costa token."""
    await _prime_cache()

    class _Esplosivo:
        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            raise AssertionError(
                "l'LLM non deve essere chiamato su impronta disallineata"
            )

    with pytest.raises(ContextMismatchError):
        await run_poi_narrative(
            "Roma",
            "Colosseo",
            _POI_ID,
            contesto_hash="non-combacia",
            executor=_FakeProfiler(),
            llm_client=_Esplosivo(),
        )


async def test_cache_fredda_con_ricostruzione_divergente_rifiuta() -> None:
    """Il caso descritto da #242: a cache fredda la ricostruzione restituisce un
    vicinato diverso da quello mostrato -> rifiuto, non prosa silenziosa."""
    contesto_hash = await _prime_cache()
    zone_context_cache.clear()
    with pytest.raises(ContextMismatchError):
        await run_poi_narrative(
            "Roma",
            "Colosseo",
            _POI_ID,
            contesto_hash=contesto_hash,
            executor=_FakeProfiler(),
            llm_client=_FakeLLMClient(),
            poi_source=_poi_source_divergente,
            geo_source=_geo_source,
        )


async def test_l_impronta_non_entra_nel_prompt() -> None:
    """Guardia #184/#197: l'impronta e' CONFRONTATA, mai consumata. Se finisse
    nel prompt sarebbe un dato del client dentro il contesto del modello."""
    contesto_hash = await _prime_cache()
    visti: list[str] = []

    class _Registrante:
        async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
            visti.append(user_content + system_prompt)
            return LLMResponse(
                text="x",
                llm_used="fake",
                tokens_input=1,
                tokens_output=1,
                cache_hit=False,
                temperature=0.0,
                seed=0,
                prompt_hash="h",
            )

    await run_poi_narrative(
        "Roma",
        "Colosseo",
        _POI_ID,
        contesto_hash=contesto_hash,
        executor=_FakeProfiler(),
        llm_client=_Registrante(),
    )
    assert contesto_hash not in visti[0]


def _analizza(client: TestClient) -> str:
    """Esegue l'analisi di zona e restituisce l'impronta, come farebbe il client."""
    zona = cast(
        httpx.Response,
        client.post("/analyze", json={"citta": "Roma", "zona": "Colosseo"}),  # pyright: ignore[reportUnknownMemberType]
    )
    return str(zona.json()["contesto_hash"])


def test_endpoint_returns_200_and_narrative(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    client = _client()
    contesto_hash = _analizza(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/poi",
            json={
                "citta": "Roma",
                "zona": "Colosseo",
                "poi_id": _POI_ID,
                "contesto_hash": contesto_hash,
            },
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["poi_id"] == _POI_ID
    assert body["narrativa_fonti"]["ontologia"] != ""
    assert body["fallback"] is False


def test_endpoint_returns_404_for_unknown_poi(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    client = _client()
    contesto_hash = _analizza(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/poi",
            json={
                "citta": "Roma",
                "zona": "Colosseo",
                "poi_id": "non-esiste",
                "contesto_hash": contesto_hash,
            },
        ),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["errore"] == "poi_non_nel_contesto"


def test_endpoint_returns_409_for_mismatched_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#242: impronta che non identifica il contesto -> 409 con invito a
    rilanciare l'analisi, non una narrativa dall'aria normale."""
    _patch_io(monkeypatch)
    client = _client()
    _analizza(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/poi",
            json={
                "citta": "Roma",
                "zona": "Colosseo",
                "poi_id": _POI_ID,
                "contesto_hash": "0" * 64,
            },
        ),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["errore"] == "contesto_disallineato"
    assert "rilancia" in resp.json()["detail"]["messaggio"]


def test_endpoint_requires_the_context_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Il campo e' obbligatorio: senza impronta non esiste una richiesta valida,
    altrimenti la garanzia di #242 sarebbe opt-in."""
    _patch_io(monkeypatch)
    client = _client()
    _analizza(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/poi",
            json={"citta": "Roma", "zona": "Colosseo", "poi_id": _POI_ID},
        ),
    )
    assert resp.status_code == 422


# --- #184: guardia anti-scoring estesa al contratto di ``/analyze/poi`` (#197) ---
# Stesso pattern exact-set di ``test_orchestrator``: il grep sul payload qui sotto
# intercetta solo nomi di campo gia' noti, mentre l'insieme esatto rende rosso
# QUALUNQUE campo nuovo, costringendo a una revisione cosciente del vincolo legale.


def test_poi_narrative_response_has_no_numeric_danger_scoring_field() -> None:
    """Contratto della risposta ``/analyze/poi``: nessuno scoring numerico di
    pericolosita' (_project.md §Vincoli). I campi numerici presenti
    (``tokens_*``/``latenza_ms``) misurano costo e performance, NON la magnitudo
    del pericolo. Un campo di rating aggiunto qui romperebbe l'insieme esatto."""
    assert set(PoiNarrativeResponse.model_fields) == {
        "poi_id",
        "narrativa",
        "narrativa_fonti",
        "risk_models",
        "tokens_input",
        "tokens_output",
        "latenza_ms",
        "repro",
        "fallback",
    }


def test_endpoint_response_never_contains_a_danger_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guardia anti-scoring estesa al nuovo endpoint (#184)."""
    _patch_io(monkeypatch)
    client = _client()
    contesto_hash = _analizza(client)
    resp = cast(
        httpx.Response,
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze/poi",
            json={
                "citta": "Roma",
                "zona": "Colosseo",
                "poi_id": _POI_ID,
                "contesto_hash": contesto_hash,
            },
        ),
    )
    assert resp.status_code == 200
    payload = resp.text.lower()
    for vietato in ("punteggio", "score", "livello di rischio", "pericolosit"):
        assert vietato not in payload
