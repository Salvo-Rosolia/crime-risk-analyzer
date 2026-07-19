"""Test endpoint POST /analyze (#18)."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer.geocoding import GeoResult, ZoneNotFoundError
from crime_risk_analyzer.llm.client import LLMError, LLMResponse, get_llm_client
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.orchestrator import run_analysis
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


class _RaisingLLMClient:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        raise LLMError("provider giu'")


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


def _patch_io(monkeypatch: pytest.MonkeyPatch) -> None:
    geo: dict[str, object] = {
        "lat": 41.89,
        "lon": 12.49,
        "bbox": Bbox(41.88, 12.48, 41.90, 12.50),
    }

    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        return geo

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


def test_analyze_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post("/analyze", json={"citta": "Roma", "zona": "Centro"}),  # pyright: ignore[reportUnknownMemberType]
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["citta"] == "Roma"
    assert body["zona_normalizzata"] == "Centro"
    assert body["fallback"] is False
    assert body["narrativa"].startswith("Analisi:")
    assert [p["confidence"] for p in body["poi"]] == ["confermato", "speculativo"]


def test_analyze_zone_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(zona: str, citta: str) -> dict[str, object]:
        raise ZoneNotFoundError("zona ignota")

    monkeypatch.setattr(retrieval, "geocode_zone", _raise)
    resp = cast(
        httpx.Response,
        _client().post("/analyze", json={"citta": "Roma", "zona": "Nessundove"}),  # pyright: ignore[reportUnknownMemberType]
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["errore"] == "zona_non_geocodificabile"


def test_analyze_accepts_non_allowlisted_city(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#191: una citta' fuori dall'allowlist NON e' piu' 400; arriva al geocoding.

    Rimossa l'allowlist di ``settings.supported_cities``, qualsiasi citta' italiana
    deve raggiungere il geocoding. Verifica che ``geocode_zone`` sia invocato con
    ``citta="Acireale"`` e che la pipeline serializzi una response 200.
    """
    seen: list[tuple[str, str]] = []

    def _recording_geocode(zona: str, citta: str) -> dict[str, object]:
        seen.append((zona, citta))
        return {
            "lat": 37.61,
            "lon": 15.16,
            "bbox": Bbox(37.60, 15.15, 37.62, 15.17),
        }

    async def _fake_fetch(
        bbox: object, citta: str, *args: object, **kwargs: object
    ) -> list[Poi]:
        return _pois(citta)

    monkeypatch.setattr(retrieval, "geocode_zone", _recording_geocode)
    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)
    resp = cast(
        httpx.Response,
        _client().post("/analyze", json={"citta": "Acireale", "zona": "Centro"}),  # pyright: ignore[reportUnknownMemberType]
    )
    assert resp.status_code == 200
    assert resp.json()["citta"] == "Acireale"
    assert seen == [("Centro", "Acireale")]


def test_analyze_non_allowlisted_city_zone_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#191: citta' fuori allowlist + zona non geocodificabile -> 422 pulito.

    Una citta'/zona inesistente non e' piu' respinta a monte (400): fallisce al
    geocoding con ``ZoneNotFoundError`` -> 422 ``zona_non_geocodificabile``.
    """

    def _raise(zona: str, citta: str) -> dict[str, object]:
        raise ZoneNotFoundError("zona ignota")

    monkeypatch.setattr(retrieval, "geocode_zone", _raise)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze", json={"citta": "Acireale", "zona": "Nessundove"}
        ),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["errore"] == "zona_non_geocodificabile"


def test_analyze_rejects_overlong_citta(monkeypatch: pytest.MonkeyPatch) -> None:
    """#191: citta' oltre max_length=100 -> 422 (validazione Pydantic, pre-I/O)."""
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze", json={"citta": "A" * 101, "zona": "Centro"}
        ),
    )
    assert resp.status_code == 422


def test_analyze_overpass_down(monkeypatch: pytest.MonkeyPatch) -> None:
    geo: dict[str, object] = {
        "lat": 41.89,
        "lon": 12.49,
        "bbox": Bbox(41.88, 12.48, 41.90, 12.50),
    }

    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        return geo

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode)

    async def _raise_fetch(*args: object, **kwargs: object) -> list[Poi]:
        raise OverpassError("overpass giu'")

    monkeypatch.setattr(retrieval, "fetch_pois", _raise_fetch)
    resp = cast(
        httpx.Response,
        _client().post("/analyze", json={"citta": "Roma", "zona": "Centro"}),  # pyright: ignore[reportUnknownMemberType]
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["errore"] == "overpass_non_disponibile"


def test_analyze_llm_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client(llm=_RaisingLLMClient()).post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze", json={"citta": "Roma", "zona": "Centro"}
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["fallback"] is True
    assert body["narrativa"] == ""
    assert body["risk_models"][0]["poi"] == "Banca A"


def test_analyze_accepts_domanda(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"citta": "Roma", "zona": "Centro", "domanda": "Quali rischi?"},
        ),
    )
    assert resp.status_code == 200


def test_analyze_domanda_reaches_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end (#119): la domanda del body arriva nello user_content dell'LLM."""
    _patch_io(monkeypatch)
    llm = _RecordingLLMClient()
    resp = cast(
        httpx.Response,
        _client(llm=llm).post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"citta": "Roma", "zona": "Centro", "domanda": "Rischi di notte?"},
        ),
    )
    assert resp.status_code == 200
    assert len(llm.calls) == 1
    _system, user = llm.calls[0]
    assert "Rischi di notte?" in user


def test_analyze_without_domanda_omits_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Senza ``domanda`` lo user_content non porta la sezione dedicata (invariato)."""
    _patch_io(monkeypatch)
    llm = _RecordingLLMClient()
    resp = cast(
        httpx.Response,
        _client(llm=llm).post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze", json={"citta": "Roma", "zona": "Centro"}
        ),
    )
    assert resp.status_code == 200
    _system, user = llm.calls[0]
    assert "DOMANDA UTENTE" not in user


def test_analyze_rejects_overlong_domanda(monkeypatch: pytest.MonkeyPatch) -> None:
    """#119: una domanda oltre max_length e' respinta con 422 prima di ogni I/O."""
    _patch_io(monkeypatch)
    resp = cast(
        httpx.Response,
        _client().post(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            json={"citta": "Roma", "zona": "Centro", "domanda": "x" * 501},
        ),
    )
    assert resp.status_code == 422


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
