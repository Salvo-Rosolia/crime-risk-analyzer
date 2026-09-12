"""Test endpoint POST /analyze (#18)."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer import circle_search, zone_context_cache
from crime_risk_analyzer.analyze_narrative import run_analysis_fast
from crime_risk_analyzer.context_fingerprint import fingerprint
from crime_risk_analyzer.geocoding import GeoResult, ZoneNotFoundError
from crime_risk_analyzer.llm.client import LLMResponse, get_llm_client
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.orchestrator import run_analysis, run_baseline
from crime_risk_analyzer.overpass_client import OverpassError, Poi
from crime_risk_analyzer.rag import retrieval
from crime_risk_analyzer.sparql_module.query_executor import get_executor

_BANK = PoiRiskProfile(
    terminus_class="Bank",
    hazards=["Bank_robbery"],
    sparql_paths=["Bank → havingHazard → Bank_robbery"],
)


class _FakeProfiler:
    def profile(self, terminus_class: str) -> PoiRiskProfile:
        profiles = {"Bank": _BANK}
        return profiles.get(
            terminus_class, PoiRiskProfile(terminus_class=terminus_class)
        )


class _FakeLLMClient:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        return LLMResponse(
            text="Analisi: rischio rapina.",
            llm_used="claude-sonnet-4-6",
            tokens_input=5,
            tokens_output=8,
            cache_hit=False,
            temperature=0.2,
            seed=42,
            prompt_hash="h",
        )


class _RecordingLLMClient:
    """Spia: registra lo ``user_content`` che l'endpoint fa arrivare al modello."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        self.calls.append((system_prompt, user_content))
        return LLMResponse(
            text="Analisi: rischio rapina.",
            llm_used="claude-sonnet-4-6",
            tokens_input=5,
            tokens_output=8,
            cache_hit=False,
            temperature=0.2,
            seed=42,
            prompt_hash="h",
        )


def _pois(citta: str) -> list[Poi]:
    return [
        {
            "id": "1",
            "name": "Banca A",
            "lat": 41.89,
            "lon": 12.49,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": citta,
        },
        {
            "id": "2",
            "name": "Bar Roma",
            "lat": 41.90,
            "lon": 12.50,
            "osm_tags": "amenity=bar",
            "terminus_class": "GenericUrbanPOI",
            "citta": citta,
        },
    ]


def _fake_reverse_geocode(lat: float, lon: float) -> tuple[str, str]:
    return ("Roma", "Trastevere")


def _patch_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patcha la sola I/O che il nuovo path a cerchio (#318) attraversa davvero.

    ``geocode_zone`` non e' piu' chiamato da ``/analyze``/``/analyze/baseline``:
    ``resolve_circle`` passa sempre un ``geo_source`` proprio. La label
    citta'/zona arriva da ``circle_search.reverse_geocode_label`` (reverse
    geocode del centro); il bbox da ``bbox_from_circle`` (puro, nessun I/O) —
    solo la label va quindi simulata qui.
    """
    monkeypatch.setattr(circle_search, "reverse_geocode_label", _fake_reverse_geocode)

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois(citta)

    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)


def _client(llm: object = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_executor] = lambda: _FakeProfiler()
    app.dependency_overrides[get_llm_client] = lambda: llm or _FakeLLMClient()
    return TestClient(app, raise_server_exceptions=False)


def test_analyze_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """#292: la rotta risponde in fase 1 — dati strutturati, ``narrativa`` assente.

    ``narrativa is None`` non e' un fallback (``fallback`` resta ``False``): dice
    al client che il testo e' in arrivo da ``POST /analyze/narrativa``. La
    distinzione e' il contratto su cui il frontend decide se mostrare lo
    scheletro della narrativa o il messaggio di LLM caduto.
    """
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["citta"] == "Roma"
    assert body["zona_normalizzata"] == "Trastevere"
    assert body["fallback"] is False
    assert body["narrativa"] is None
    assert [p["confidence"] for p in body["poi"]] == ["verificato", None]


def test_analyze_zone_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un errore alla risoluzione dell'etichetta (reverse geocode) propaga a 422.

    ``reverse_geocode_label`` reale non solleva mai (fallback cosmetico, #318):
    questo verifica solo che l'handler centrale di ``ZoneNotFoundError`` resti
    cablato anche dietro il nuovo ``resolve_circle``.
    """

    def _raise(lat: float, lon: float) -> tuple[str, str]:
        raise ZoneNotFoundError("zona ignota")

    monkeypatch.setattr(circle_search, "reverse_geocode_label", _raise)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["errore"] == "zona_non_geocodificabile"


def test_analyze_reports_reverse_geocoded_city(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#318: la ``citta'`` in risposta e' quella del reverse geocode del centro.

    Non c'e' piu' un'allowlist (gia' rimossa da #191) ne' un campo ``citta`` in
    richiesta: verifica che ``center.lat``/``center.lon`` raggiungano
    ``reverse_geocode_label`` e che l'etichetta restituita finisca in risposta.
    """
    seen: list[tuple[float, float]] = []

    def _recording_reverse(lat: float, lon: float) -> tuple[str, str]:
        seen.append((lat, lon))
        return ("Acireale", "Centro")

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois(citta)

    monkeypatch.setattr(circle_search, "reverse_geocode_label", _recording_reverse)
    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 37.61, "lon": 15.16}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["citta"] == "Acireale"
    assert seen == [(37.61, 15.16)]


def test_analyze_rejects_out_of_range_radius(monkeypatch: pytest.MonkeyPatch) -> None:
    """radius_m fuori da [search_radius_min_m, search_radius_max_m] -> 422 (#318).

    Validazione Pydantic pre-I/O, come il vecchio limite ``max_length=100`` su
    ``citta'`` (rimosso insieme al campo): il body malformato non deve
    raggiungere ne' il reverse geocode ne' Overpass.
    """
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 50_000.0},
        ),
    )
    assert resp.status_code == 422


def _pois_per_raggio(citta: str) -> list[Poi]:
    """Un POI al centro esatto della richiesta + uno a oltre un km (#318)."""
    return [
        {
            "id": "vicino",
            "name": "Banca A",
            "lat": 41.89,
            "lon": 12.49,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": citta,
        },
        {
            "id": "lontano",
            "name": "Bar Roma",
            "lat": 41.90,
            "lon": 12.50,
            "osm_tags": "amenity=bar",
            "terminus_class": "GenericUrbanPOI",
            "citta": citta,
        },
    ]


def test_analyze_radius_m_raggiunge_davvero_il_filtro_geospaziale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#318: prova al confine HTTP che ``radius_m`` filtra i POI, non solo che
    e' validato dal ``field_validator``.

    Senza ``radius_m=request.radius_m`` cablato da ``main.py`` a
    ``run_analysis_fast``, l'intera suite passerebbe comunque (nulla, a livello
    di rotta, prova che il raggio raggiunge davvero la pipeline). Il centro
    della richiesta coincide con ``Banca A`` (distanza ~0 m) mentre ``Bar Roma``
    e' a oltre un km: un raggio di 150 m (il minimo consentito) deve escludere
    la seconda dalla response.
    """
    monkeypatch.setattr(circle_search, "reverse_geocode_label", _fake_reverse_geocode)

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois_per_raggio(citta)

    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 150.0},
        ),
    )
    assert resp.status_code == 200
    assert [p["id"] for p in resp.json()["poi"]] == ["vicino"]


def test_analyze_overpass_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(circle_search, "reverse_geocode_label", _fake_reverse_geocode)

    async def _raise_fetch(*args: object, **kwargs: object) -> list[Poi]:
        raise OverpassError("overpass giu'")

    monkeypatch.setattr(retrieval, "fetch_pois", _raise_fetch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["errore"] == "overpass_non_disponibile"


def test_analyze_non_chiama_mai_l_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """#292: la fase 1 non spende una chiamata al modello — e' il suo scopo.

    Prima la rotta bloccava sull'LLM e i dati strutturati arrivavano solo dopo la
    narrativa. Se un refactor rimettesse ``run_analysis`` sulla rotta, la spia
    registrerebbe una chiamata e questo test diventerebbe rosso: e' la guardia
    della latenza percepita, non un dettaglio di implementazione.

    I ``risk_models`` restano nella response di fase 1 (li derivano il grounding,
    non l'LLM): il frontend aggancia i rischi al punto per ``poi_id``, quindi il
    nome della chiave e' verificato sul filo.
    """
    _patch_io(monkeypatch)
    llm = _RecordingLLMClient()
    resp = cast(
        httpx.Response,
        _client(llm=llm).post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"center": {"lat": 41.89, "lon": 12.49}, "radius_m": 2000.0},
        ),
    )
    assert resp.status_code == 200
    assert llm.calls == []
    body = resp.json()
    assert body["narrativa"] is None
    assert body["fallback"] is False
    assert body["risk_models"][0]["poi"] == "Banca A"
    assert body["risk_models"][0]["poi_id"] == "1"


async def test_run_analysis_threads_geo_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#169: geo_source passato a run_analysis raggiunge retrieve (nessun geocode)."""

    def _boom_geocode(zona: str, citta: str) -> GeoResult:
        raise AssertionError("geocode_zone non deve essere chiamato con geo_source")

    monkeypatch.setattr(retrieval, "geocode_zone", _boom_geocode)
    seen: list[tuple[str, str]] = []

    async def _geo(citta: str, zona: str) -> GeoResult:
        seen.append((citta, zona))
        return GeoResult(lat=0.0, lon=0.0, bbox=Bbox(0.0, 0.0, 0.0, 0.0))

    async def _pois(bbox: Bbox, citta: str) -> list[Poi]:
        return []

    await run_analysis(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_pois,
        geo_source=_geo,
    )
    assert seen == [("Roma", "Colosseo")]


async def test_analyze_populates_the_zone_context_cache() -> None:
    """#197: il contesto calcolato da /analyze resta disponibile a /analyze/poi.

    L'invariante di prodotto e' la stessa di prima, cambia chi la realizza: dopo
    lo split (#292) e' la fase 1 della rotta (``run_analysis_fast``) a depositare
    il contesto, non ``run_analysis`` — che nessuna rotta chiama piu'. Verificato
    sul contenuto, non solo sulla presenza: il clic su un POI legge da qui la
    zona, i punti e i rischi validati, quindi e' quello che deve restare intero.
    """

    async def _geo(citta: str, zona: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    async def _fetch(bbox: Bbox, citta: str) -> list[Poi]:
        return _pois(citta)

    zone_context_cache.clear()
    await run_analysis_fast(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_fetch,
        geo_source=_geo,
    )
    cached = zone_context_cache.get("Roma", "Colosseo")
    assert cached is not None
    assert cached["retrieval"]["zona"] == "Colosseo"
    assert [p["name"] for p in cached["retrieval"]["pois"]] == ["Banca A", "Bar Roma"]
    assert len(cached["grounded"]["validated_risks"]) == 2


# --- #242: impronta del contesto nella response ---
# ``retrieve`` passa la lista di POI COSI' COM'E' dalla source al contesto
# (``pois = await source(...)``: nessun filtro, nessun riordino), quindi
# l'impronta della response identifica esattamente la lista prodotta dalla
# sorgente e il confronto con ``fingerprint(_pois(...))`` e' legittimo.


async def test_run_analysis_espone_l_impronta_del_contesto() -> None:
    """#242: l'impronta identifica la lista POI della response che la contiene.

    Non e' (piu') una guardia della rotta: da #292 ``run_analysis`` e' il solo
    percorso di VALUTAZIONE, e la stessa proprieta' sulla rotta e' verificata da
    ``test_analyze_narrative`` sulla fase 1. Resta qui perche' il contratto di
    risposta e' unico, e i due percorsi devono continuare a emettere la stessa
    impronta della stessa lista.
    """

    async def _geo(citta: str, zona: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    async def _fetch(bbox: Bbox, citta: str) -> list[Poi]:
        return _pois(citta)

    resp = await run_analysis(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_fetch,
        geo_source=_geo,
    )
    assert resp.contesto_hash == fingerprint(_pois("Roma"))


async def test_impronta_diversa_se_il_set_di_poi_cambia() -> None:
    """Due catture con POI diversi non possono avere la stessa impronta:
    e' la condizione perche' /analyze/poi rilevi la divergenza (#242)."""

    async def _geo(citta: str, zona: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    async def _fetch_pieno(bbox: Bbox, citta: str) -> list[Poi]:
        return _pois(citta)

    async def _fetch_ridotto(bbox: Bbox, citta: str) -> list[Poi]:
        return _pois(citta)[:1]

    pieno = await run_analysis(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_fetch_pieno,
        geo_source=_geo,
    )
    ridotto = await run_analysis(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        llm_client=_FakeLLMClient(),
        poi_source=_fetch_ridotto,
        geo_source=_geo,
    )
    assert pieno.contesto_hash != ridotto.contesto_hash


async def test_baseline_espone_l_impronta_del_contesto() -> None:
    """Anche la pipeline senza LLM emette l'impronta: la response e' la stessa
    e il frontend in modalita' Base non deve restare senza (#242)."""

    async def _geo(citta: str, zona: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    async def _fetch(bbox: Bbox, citta: str) -> list[Poi]:
        return _pois(citta)

    resp = await run_baseline(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_fetch,
        geo_source=_geo,
    )
    assert resp.contesto_hash == fingerprint(_pois("Roma"))


async def test_impronta_baseline_calcolata_dopo_il_filtro_tipo_poi() -> None:
    """L'impronta identifica la lista RESTITUITA, non quella pre-filtro (#242).

    Senza questo test un refactor che riportasse ``fingerprint`` sopra
    ``_filter_pois_by_type`` (#119) resterebbe verde e reintrodurrebbe la
    divergenza che #242 chiude: un'impronta che identifica POI mai mostrati.
    """

    async def _geo(citta: str, zona: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    async def _fetch(bbox: Bbox, citta: str) -> list[Poi]:
        return _pois(citta)

    resp = await run_baseline(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_fetch,
        geo_source=_geo,
        tipo_poi="Bank",
    )
    filtrati = [p for p in _pois("Roma") if p["terminus_class"] == "Bank"]
    assert [p.name for p in resp.poi] == [p["name"] for p in filtrati]
    assert resp.contesto_hash == fingerprint(filtrati)
    assert resp.contesto_hash != fingerprint(_pois("Roma"))
