"""Unit sull'orchestratore /analyze (#18)."""

from __future__ import annotations

import pytest

from crime_risk_analyzer.llm.client import LLMError, LLMResponse
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.orchestrator import (
    _build_poi_list,  # pyright: ignore[reportPrivateUsage]
    _risk_models_from_grounded,  # pyright: ignore[reportPrivateUsage]
    _structured_response,  # pyright: ignore[reportPrivateUsage]
    run_analysis,
    run_baseline,
)
from crime_risk_analyzer.overpass_client import Poi
from tests.eval._doubles import FakeLLMClient as _FakeLLMClient
from tests.eval._doubles import FakeProfiler as _FakeProfiler
from tests.eval._doubles import default_llm_response as _llm_response


def _poi(poi_id: str, name: str, terminus_class: str) -> dict[str, object]:
    return {
        "id": poi_id,
        "name": name,
        "lat": 41.89,
        "lon": 12.49,
        "osm_tags": "amenity=bank",
        "terminus_class": terminus_class,
        "citta": "Roma",
    }


def _vr(poi: str, terminus_class: str, hazards: list[str]) -> dict[str, object]:
    risks = [
        {
            "hazard": h,
            "tag": "ONTOLOGIA",
            "confidence": "confermato",
            "source": f"{terminus_class} → havingHazard → {h}",
        }
        for h in hazards
    ]
    return {
        "poi": poi,
        "terminus_class": terminus_class,
        "risks": risks,
        "vulnerabilities": [],
        "sparql_path": risks[0]["source"] if risks else None,
    }


class _RaisingLLMClient:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        raise LLMError("provider giu'")


def _patch_io(monkeypatch: pytest.MonkeyPatch, pois: list[Poi] | None = None) -> None:
    from crime_risk_analyzer.models.geo import Bbox
    from crime_risk_analyzer.rag import retrieval

    resolved_pois: list[Poi] = (
        pois
        if pois is not None
        else [
            {
                "id": "1",
                "name": "Banca A",
                "lat": 41.89,
                "lon": 12.49,
                "osm_tags": "amenity=bank",
                "terminus_class": "Bank",
                "citta": "Roma",
            }
        ]
    )

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
        return resolved_pois

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode)
    monkeypatch.setattr(retrieval, "fetch_pois", _fake_fetch)


_BANK_PROFILE = PoiRiskProfile(
    terminus_class="Bank",
    hazards=["Bank_robbery"],
    sparql_paths=["Bank → havingHazard → Bank_robbery"],
)


def test_build_poi_list_confidence_and_path() -> None:
    retrieval_ctx = {
        "pois": [_poi("1", "Banca A", "Bank"), _poi("2", "Bar Roma", "GenericUrbanPOI")]
    }
    grounded = {
        "validated_risks": [
            _vr("Banca A", "Bank", ["Bank_robbery"]),
            _vr("Bar Roma", "GenericUrbanPOI", []),
        ]
    }
    out = _build_poi_list(retrieval_ctx, grounded)  # type: ignore[arg-type]
    assert [p.confidence for p in out] == ["confermato", "speculativo"]
    assert out[0].sparql_path == "Bank → havingHazard → Bank_robbery"
    assert out[0].id == "1"
    assert out[1].sparql_path is None


def test_build_poi_list_strict_zip_mismatch() -> None:
    with pytest.raises(ValueError):
        _build_poi_list(
            {"pois": [_poi("1", "Banca A", "Bank")]},  # type: ignore[arg-type]
            {"validated_risks": []},  # type: ignore[arg-type]
        )


def test_risk_models_from_grounded() -> None:
    grounded = {
        "validated_risks": [
            _vr("Banca A", "Bank", ["Bank_robbery", "Theft"]),
            _vr("Bar Roma", "GenericUrbanPOI", []),
        ]
    }
    models = _risk_models_from_grounded(grounded)  # type: ignore[arg-type]
    assert [m.poi for m in models] == ["Banca A", "Bar Roma"]
    assert [r.hazard for r in models[0].risks] == ["Bank_robbery", "Theft"]
    assert models[0].risks[0].tag == "ONTOLOGIA"
    assert models[1].risks == []


def test_structured_response_no_llm() -> None:
    grounded = {
        "zona": "Centro",
        "validated_risks": [_vr("Banca A", "Bank", ["Bank_robbery"])],
        "confidence_summary": {"confermato": 1, "plausibile": 0, "speculativo": 0},
    }
    poi_out = _build_poi_list(
        {"pois": [_poi("1", "Banca A", "Bank")]},  # type: ignore[arg-type]
        grounded,  # type: ignore[arg-type]
    )
    resp = _structured_response(
        "Roma",
        "Centro",
        poi_out,
        grounded,  # type: ignore[arg-type]
        latenza_ms=5,
        fallback=False,
    )
    assert resp.narrativa == ""
    assert resp.llm_used == ""
    assert resp.cache_hit is False
    assert resp.fallback is False
    assert resp.repro.prompt_hash == ""
    assert resp.risk_models[0].risks[0].hazard == "Bank_robbery"
    assert resp.confidence_summary.confermato == 1


async def test_run_analysis_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_FakeLLMClient(_llm_response()),
    )
    assert resp.citta == "Roma"
    assert resp.zona_normalizzata == "Centro"
    assert resp.fallback is False
    assert resp.narrativa.startswith("Analisi:")
    assert resp.llm_used == "claude-sonnet-4-6"
    assert [p.confidence for p in resp.poi] == ["confermato"]
    assert resp.latenza_ms >= 0


async def test_run_analysis_llm_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_RaisingLLMClient(),
    )
    assert resp.fallback is True
    assert resp.narrativa == ""
    assert resp.llm_used == ""
    assert resp.cache_hit is False
    assert [m.poi for m in resp.risk_models] == ["Banca A"]
    assert resp.risk_models[0].risks[0].hazard == "Bank_robbery"
    assert resp.confidence_summary.confermato == 1


async def test_run_analysis_zero_pois(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch, pois=[])
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({}),
        llm_client=_FakeLLMClient(_llm_response()),
    )
    assert resp.poi == []
    assert resp.risk_models == []
    assert resp.confidence_summary.confermato == 0
    assert resp.confidence_summary.plausibile == 0
    assert resp.confidence_summary.speculativo == 0
    assert resp.fallback is False


async def test_run_baseline_no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    resp = await run_baseline(
        "Roma", "Centro", executor=_FakeProfiler({"Bank": _BANK_PROFILE})
    )
    assert resp.fallback is False
    assert resp.narrativa == ""
    assert resp.llm_used == ""
    assert [m.poi for m in resp.risk_models] == ["Banca A"]
    assert resp.risk_models[0].risks[0].hazard == "Bank_robbery"
    assert resp.confidence_summary.confermato == 1
    assert resp.latenza_ms >= 0


async def test_run_analysis_exposes_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_FakeLLMClient(_llm_response()),
    )
    assert resp.tokens_input == 10
    assert resp.tokens_output == 20


async def test_run_analysis_fallback_zero_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_io(monkeypatch)
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_RaisingLLMClient(),
    )
    assert resp.tokens_input == 0
    assert resp.tokens_output == 0


async def test_run_analysis_accepts_poi_source(monkeypatch: pytest.MonkeyPatch) -> None:
    from crime_risk_analyzer.models.geo import Bbox
    from crime_risk_analyzer.rag import retrieval

    def _fake_geocode(zona: str, citta: str) -> dict[str, object]:
        return {"lat": 41.89, "lon": 12.49, "bbox": Bbox(41.88, 12.48, 41.90, 12.50)}

    monkeypatch.setattr(retrieval, "geocode_zone", _fake_geocode)

    async def src(bbox: object, citta: str) -> list[dict[str, object]]:
        return [
            {
                "id": "1",
                "name": "Banca A",
                "lat": 41.89,
                "lon": 12.49,
                "osm_tags": "amenity=bank",
                "terminus_class": "Bank",
                "citta": "Roma",
            }
        ]

    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_FakeLLMClient(_llm_response()),
        poi_source=src,  # type: ignore[arg-type]
    )
    assert [p.name for p in resp.poi] == ["Banca A"]
