"""Unit sull'orchestratore /analyze (#18)."""

from __future__ import annotations

import inspect
import logging

import pytest
from pydantic import ValidationError

from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.llm.client import LLMError, LLMResponse
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.orchestrator import (
    AnalyzeRequest,
    AnalyzeResponse,
    BaselineRequest,
    PoiOut,
    _build_poi_list,  # pyright: ignore[reportPrivateUsage]
    _generated_response,  # pyright: ignore[reportPrivateUsage]
    _risk_models_from_grounded,  # pyright: ignore[reportPrivateUsage]
    _structured_response,  # pyright: ignore[reportPrivateUsage]
    run_analysis,
    run_baseline,
    run_no_ontology_prompt,
)
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.rag.generation import (
    USER_INPUT_FENCE_OPEN,
    SourceProse,
)
from crime_risk_analyzer.rag.no_ontology_generation import (
    LLM_SYNTHESIS_BLOCK_HEADER,
    NO_ONTOLOGY_SYSTEM_PROMPT,
)
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


def _vr(
    poi: str, terminus_class: str, hazards: list[str], *, poi_id: str
) -> dict[str, object]:
    """Validated risk sintetico. ``poi_id`` e' OBBLIGATORIO e keyword-only: con un
    default, una fixture poteva accoppiare un POI con id ``"1"`` a rischi con id
    vuoto — la stessa divergenza che questa story chiude — senza che nessun test se
    ne accorgesse."""
    risks = [
        {
            "hazard": h,
            "tag": "ONTOLOGIA",
            "confidence": "verificato",
            "source": f"{terminus_class} → havingHazard → {h}",
        }
        for h in hazards
    ]
    return {
        "poi": poi,
        "poi_id": poi_id,
        "terminus_class": terminus_class,
        "risks": risks,
        # I tre assi non-hazard (#256): vuoti per default, i test che li verificano
        # li popolano espressamente.
        "critical_events": [],
        "vulnerabilities": [],
        "sparql_path": risks[0]["source"] if risks else None,
    }


class _RaisingLLMClient:
    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        raise LLMError("provider giu'")


class _RecordingLLMClient:
    """Spia del client LLM: registra ``(system, user)`` di ogni chiamata."""

    def __init__(self, response: LLMResponse | None = None) -> None:
        self._response: LLMResponse = response or _llm_response()
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        self.calls.append((system_prompt, user_content))
        return self._response


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


async def _geo_source(citta: str, zona: str) -> GeoResult:
    """Doppio di geocoding per i test di ``_structured_response`` con narrativa
    pendente (#259): evita Nominatim, come ``_poi_source`` evita Overpass."""
    return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))


async def _poi_source(bbox: Bbox, citta: str) -> list[Poi]:
    return [
        {
            "id": "node/1",
            "name": "Colosseo",
            "lat": 41.8902,
            "lon": 12.4922,
            "osm_tags": "historic=monument",
            "terminus_class": "Historical_monument",
            "citta": citta,
        }
    ]


_BANK_PROFILE = PoiRiskProfile(
    terminus_class="Bank",
    hazards=["Bank_robbery"],
    sparql_paths=["Bank → havingHazard → Bank_robbery"],
)

_SCHOOL_PROFILE = PoiRiskProfile(
    terminus_class="School",
    hazards=["Vandalism"],
    sparql_paths=["School → havingHazard → Vandalism"],
)


def test_build_poi_list_confidence_and_path() -> None:
    retrieval_ctx = {
        "pois": [_poi("1", "Banca A", "Bank"), _poi("2", "Bar Roma", "GenericUrbanPOI")]
    }
    grounded = {
        "validated_risks": [
            _vr("Banca A", "Bank", ["Bank_robbery"], poi_id="1"),
            _vr("Bar Roma", "GenericUrbanPOI", [], poi_id="2"),
        ]
    }
    out = _build_poi_list(retrieval_ctx, grounded)  # type: ignore[arg-type]
    assert [p.confidence for p in out] == ["verificato", None]
    assert out[0].sparql_path == "Bank → havingHazard → Bank_robbery"
    assert out[0].id == "1"
    assert out[1].sparql_path is None


def test_build_poi_list_confidence_unified_with_per_risk() -> None:
    # #202/M1: la confidence per-POI e' unificata col livello per-rischio del
    # grounding: named+risks -> verificato; anonymous+risks -> da_confermare;
    # no-risks -> None (POI fuori ontologia: nessuna confidence da qualificare, #220).
    retrieval_ctx = {
        "pois": [
            _poi("1", "Banca A", "Bank"),
            _poi("2", "", "Bank"),
            _poi("3", "Bar Roma", "GenericUrbanPOI"),
        ]
    }
    grounded = {
        "validated_risks": [
            _vr("Banca A", "Bank", ["Bank_robbery"], poi_id="1"),
            _vr("", "Bank", ["Bank_robbery"], poi_id="2"),
            _vr("Bar Roma", "GenericUrbanPOI", [], poi_id="3"),
        ]
    }
    out = _build_poi_list(retrieval_ctx, grounded)  # type: ignore[arg-type]
    assert [p.confidence for p in out] == ["verificato", "da_confermare", None]


def test_build_poi_list_poi_fuori_ontologia_confidence_none() -> None:
    # #220: un POI FUORI ONTOLOGIA (nessun rischio) non ha una confidence da
    # qualificare -> confidence None (il livello "ipotesi" e' stato rimosso). Il
    # None marca l'assenza di rischi, non un livello di forza probatoria.
    retrieval_ctx = {"pois": [_poi("1", "Bar Roma", "GenericUrbanPOI")]}
    grounded = {"validated_risks": [_vr("Bar Roma", "GenericUrbanPOI", [], poi_id="1")]}
    out = _build_poi_list(retrieval_ctx, grounded)  # type: ignore[arg-type]
    assert out[0].confidence is None


def test_build_poi_list_strict_zip_mismatch() -> None:
    with pytest.raises(ValueError):
        _build_poi_list(
            {"pois": [_poi("1", "Banca A", "Bank")]},  # type: ignore[arg-type]
            {"validated_risks": []},  # type: ignore[arg-type]
        )


def test_build_poi_list_espone_gli_assi_con_etichette_e_citazione() -> None:
    """Eventi critici e vulnerabilita' arrivano al contratto (#256).

    L'executor SPARQL li estrae a ogni richiesta da sempre, ma gli eventi critici non
    li leggeva nessuno e le vulnerabilita' finivano solo nel prompt: l'ontologia da'
    quattro assi e la UI ne mostrava uno. Ognuno porta la propria citazione e
    l'etichetta IT del vocabolario controllato, come gli hazard. Lo stakeholder resta
    fuori finche' il vocabolario non lo copre (72 filler senza etichetta italiana).
    """
    retrieval_ctx = {"pois": [_poi("1", "Banca A", "Bank")]}
    vr = _vr("Banca A", "Bank", ["Bank_robbery"], poi_id="1")
    # Identifier REALI, presenti nel vocabolario controllato (#77): con un nome
    # inventato ``label_it`` degraderebbe all'inglese de-underscorato e il test
    # verificherebbe il fallback credendo di verificare il vocabolario.
    vr["critical_events"] = [
        {"name": "Hostages", "source": "Bank → havingCriticalEvent → Hostages"}
    ]
    vr["vulnerabilities"] = [
        {
            "name": "Poor_surveillance",
            "source": "Bank → isVulnerableTo → Poor_surveillance",
        }
    ]
    grounded = {"validated_risks": [vr]}

    out = _build_poi_list(retrieval_ctx, grounded)[0]  # type: ignore[arg-type]

    assert [e.name for e in out.critical_events] == ["Hostages"]
    assert out.critical_events[0].source == "Bank → havingCriticalEvent → Hostages"
    assert out.critical_events[0].label_it == "Ostaggi"
    assert out.vulnerabilities[0].label_it == "Sorveglianza insufficiente"


def test_build_poi_list_rejects_id_misalignment() -> None:
    """Liste di pari lunghezza ma disallineate per identita' devono fallire forte.

    ``zip(strict=True)`` verifica solo le LUNGHEZZE: due liste riordinate in modo
    diverso passerebbero, e ogni POI riceverebbe confidence e ``sparql_path`` di un
    altro punto — la stessa misattribuzione silenziosa che questa story chiude, per
    una via diversa. Ora che entrambe le liste portano l'id, il disallineamento e'
    rilevabile.
    """
    with pytest.raises(ValueError):
        _build_poi_list(
            {"pois": [_poi("1", "Banca A", "Bank"), _poi("2", "Scuola", "School")]},  # type: ignore[arg-type]
            {
                "validated_risks": [
                    _vr("Scuola", "School", ["Vandalism"], poi_id="2"),
                    _vr("Banca A", "Bank", ["Bank_robbery"], poi_id="1"),
                ]
            },  # type: ignore[arg-type]
        )


def test_risk_models_from_grounded() -> None:
    grounded = {
        "validated_risks": [
            _vr("Banca A", "Bank", ["Bank_robbery", "Theft"], poi_id="1"),
            _vr("Bar Roma", "GenericUrbanPOI", [], poi_id="2"),
        ]
    }
    models = _risk_models_from_grounded(grounded)  # type: ignore[arg-type]
    assert [(m.poi_id, m.poi) for m in models] == [("1", "Banca A"), ("2", "Bar Roma")]
    assert [r.hazard for r in models[0].risks] == ["Bank_robbery", "Theft"]
    assert models[0].risks[0].tag == "ONTOLOGIA"
    assert models[1].risks == []


def test_structured_response_no_llm() -> None:
    grounded = {
        "zona": "Centro",
        "validated_risks": [_vr("Banca A", "Bank", ["Bank_robbery"], poi_id="1")],
        "confidence_summary": {"verificato": 1, "da_confermare": 0},
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
        # L'impronta del contesto (#242) arriva dal chiamante: qui e' un
        # letterale, perche' il test verifica l'assemblaggio della response
        # senza LLM, non il calcolo dell'impronta.
        contesto_hash="h-ctx",
    )
    assert resp.narrativa == ""
    assert resp.contesto_hash == "h-ctx"
    assert resp.llm_used == ""
    assert resp.cache_hit is False
    assert resp.fallback is False
    assert resp.repro.prompt_hash == ""
    assert resp.risk_models[0].risks[0].hazard == "Bank_robbery"
    assert resp.confidence_summary.verificato == 1


async def test_structured_response_narrativa_none_when_pending() -> None:
    """``_structured_response`` con ``narrativa=None`` produce una risposta con
    narrativa in attesa (fase 1 di #259): non e' un fallback, ``fallback`` resta
    quello passato dal chiamante."""
    from crime_risk_analyzer.rag.grounding import ground
    from crime_risk_analyzer.rag.retrieval import retrieve

    ctx = await retrieve(
        "Roma",
        "Colosseo",
        executor=_FakeProfiler(),
        poi_source=_poi_source,
        geo_source=_geo_source,
    )
    grounded = ground(ctx)
    poi_out = _build_poi_list(ctx, grounded)
    resp = _structured_response(
        "Roma",
        "Colosseo",
        poi_out,
        grounded,
        latenza_ms=0,
        fallback=False,
        contesto_hash="h",
        narrativa=None,
    )
    assert resp.narrativa is None
    assert resp.fallback is False


def test_structured_response_default_narrativa_is_empty_string() -> None:
    """Default invariato: chi non passa ``narrativa`` (``run_baseline``, fallback
    di ``run_analysis``) continua a ricevere ``""``, non ``None`` — nessuna
    regressione."""
    from crime_risk_analyzer.rag.grounding import GroundedContext

    # Nessun await necessario: costruiamo un GroundedContext minimale a mano,
    # annotato esplicitamente (un dict letterale non annotato non passerebbe
    # pyright strict come argomento tipizzato GroundedContext).
    grounded: GroundedContext = {
        "zona": "Colosseo",
        "validated_risks": [],
        "confidence_summary": {},
    }
    resp = _structured_response(
        "Roma",
        "Colosseo",
        [],
        grounded,
        latenza_ms=0,
        fallback=False,
        contesto_hash="h",
    )
    assert resp.narrativa == ""


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
    assert resp.narrativa is not None
    assert resp.narrativa.startswith("Analisi:")
    assert resp.llm_used == "claude-sonnet-4-6"
    assert [p.confidence for p in resp.poi] == ["verificato"]
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
    assert resp.confidence_summary.verificato == 1


async def test_run_analysis_llm_fallback_logs_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """#210: il fallback su LLMError emette un warning col messaggio dell'eccezione.

    Prima l'errore veniva inghiottito senza traccia: un warning strutturato rende
    diagnosticabili i fallback futuri (perche' la narrativa e' vuota)."""
    _patch_io(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="crime_risk_analyzer.orchestrator"):
        resp = await run_analysis(
            "Roma",
            "Centro",
            executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
            llm_client=_RaisingLLMClient(),
        )
    assert resp.fallback is True
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "il fallback deve emettere almeno un warning"
    assert any("provider giu'" in r.getMessage() for r in warnings)


async def test_run_analysis_llm_timeout_triggers_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un provider LLM oltre il timeout scatena il fallback 200 (no hang/500)."""
    import asyncio

    from crime_risk_analyzer.llm.client import LLMClient

    _patch_io(monkeypatch)

    class _HangingMessages:
        async def create(self, **_kwargs: object) -> object:
            await asyncio.sleep(1)  # oltre il timeout: verra' cancellato
            raise AssertionError("create doveva essere cancellato dal timeout")

    class _HangingAnthropic:
        def __init__(self) -> None:
            self.messages = _HangingMessages()

    llm = LLMClient.for_claude(_HangingAnthropic(), timeout=0.01)  # pyright: ignore[reportArgumentType]

    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=llm,
    )

    assert resp.fallback is True
    assert resp.narrativa == ""
    assert resp.tokens_input == 0
    assert [m.poi for m in resp.risk_models] == ["Banca A"]


async def test_run_analysis_anonymous_poi_da_confermare_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#202/m3: un POI ANONIMO con rischi ontologici propaga ``da_confermare`` fino
    alla AnalyzeResponse. risk_models[].risks[].confidence, confidence_summary e
    poi[].confidence sono coerenti (nessuna divergenza badge-vs-rischi, M1)."""
    anon: list[Poi] = [
        {
            "id": "1",
            "name": "",
            "lat": 41.89,
            "lon": 12.49,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": "Roma",
        }
    ]
    _patch_io(monkeypatch, pois=anon)
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_FakeLLMClient(_llm_response()),
    )
    assert resp.risk_models[0].risks[0].confidence == "da_confermare"
    assert resp.confidence_summary.da_confermare == 1
    assert resp.confidence_summary.verificato == 0
    assert [p.confidence for p in resp.poi] == ["da_confermare"]


async def test_risk_models_distinguono_due_poi_anonimi_di_classe_diversa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Due feature OSM anonime di classe diversa restano attribuibili al punto giusto.

    Chi consuma la response aggancia i rischi al POI. Se l'unico identificatore e'
    il ``name``, due POI senza nome collassano sul primo e il dettaglio di uno
    mostra i rischi dell'altro: i nomi OSM non sono ne' unici ne' sempre presenti,
    quindi l'``id`` e' l'unica chiave che regge.
    """
    anonimi: list[Poi] = [
        {
            "id": "11",
            "name": "",
            "lat": 41.89,
            "lon": 12.49,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": "Roma",
        },
        {
            "id": "22",
            "name": "",
            "lat": 41.90,
            "lon": 12.50,
            "osm_tags": "amenity=school",
            "terminus_class": "School",
            "citta": "Roma",
        },
    ]
    _patch_io(monkeypatch, pois=anonimi)
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE, "School": _SCHOOL_PROFILE}),
        llm_client=_FakeLLMClient(_llm_response()),
    )
    hazard_per_id = {m.poi_id: [r.hazard for r in m.risks] for m in resp.risk_models}
    assert hazard_per_id == {"11": ["Bank_robbery"], "22": ["Vandalism"]}


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
    assert resp.confidence_summary.verificato == 0
    assert resp.confidence_summary.da_confermare == 0
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
    assert resp.confidence_summary.verificato == 1
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


# --- #119: domanda propagata da run_analysis fino allo user_content del prompt ---


async def test_run_analysis_passes_domanda_to_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_io(monkeypatch)
    client = _RecordingLLMClient()
    await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=client,
        domanda="Rischi per i pedoni?",
    )
    assert len(client.calls) == 1
    _system, user = client.calls[0]
    assert "Rischi per i pedoni?" in user
    assert USER_INPUT_FENCE_OPEN in user


async def test_run_analysis_without_domanda_omits_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_io(monkeypatch)
    client = _RecordingLLMClient()
    await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=client,
    )
    _system, user = client.calls[0]
    assert USER_INPUT_FENCE_OPEN not in user


# --- #196: narrativa_fonti espone la prosa per fonte (additivo, display) ---


async def test_run_analysis_popola_narrativa_fonti(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La prosa a blocchi dell'LLM viene esposta per fonte in ``narrativa_fonti``
    SENZA alterare ``narrativa`` (stringa intera, letta dall'eval)."""
    _patch_io(monkeypatch)
    narrativa = (
        "Sintesi.\n\n"
        "Rischi da ontologia [ONTOLOGIA]\nFurto.\n\n"
        "Rischi dal contesto [CONTESTO]\nBorseggio."
    )
    response = LLMResponse(
        text=narrativa,
        llm_used="claude-sonnet-4-6",
        tokens_input=10,
        tokens_output=20,
        cache_hit=False,
        temperature=0.2,
        seed=42,
        prompt_hash="abc123",
    )
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_FakeLLMClient(response),
    )
    assert resp.narrativa == narrativa  # invariata
    assert resp.narrativa_fonti.overview == "Sintesi."
    assert resp.narrativa_fonti.ontologia == "Furto."
    assert resp.narrativa_fonti.contesto == "Borseggio."
    assert resp.narrativa_fonti.speculativo == ""


async def test_run_analysis_fallback_llm_narrativa_fonti_vuoto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nel fallback LLM la prosa per fonte resta vuota (default ``SourceProse()``),
    coerente con ``narrativa == ""``."""
    _patch_io(monkeypatch)
    resp = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_RaisingLLMClient(),
    )
    assert resp.fallback is True
    assert resp.narrativa == ""
    assert resp.narrativa_fonti == SourceProse()


# --- #119: tipo_poi filtra i POI server-side nel baseline ---


def _two_pois() -> list[Poi]:
    return [
        {
            "id": "1",
            "name": "Banca A",
            "lat": 41.89,
            "lon": 12.49,
            "osm_tags": "amenity=bank",
            "terminus_class": "Bank",
            "citta": "Roma",
        },
        {
            "id": "2",
            "name": "Bar Roma",
            "lat": 41.90,
            "lon": 12.50,
            "osm_tags": "amenity=bar",
            "terminus_class": "GenericUrbanPOI",
            "citta": "Roma",
        },
    ]


async def test_run_baseline_filters_by_tipo_poi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_io(monkeypatch, pois=_two_pois())
    resp = await run_baseline(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        tipo_poi="Bank",
    )
    # solo i POI di classe TERMINUS "Bank": il GenericUrbanPOI e' escluso
    assert [p.terminus_class for p in resp.poi] == ["Bank"]
    assert [p.name for p in resp.poi] == ["Banca A"]
    assert [m.poi for m in resp.risk_models] == ["Banca A"]


async def test_run_baseline_no_filter_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_io(monkeypatch, pois=_two_pois())
    resp = await run_baseline(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
    )
    # default (None): nessun filtro, tutti i POI passano (comportamento invariato)
    assert [p.terminus_class for p in resp.poi] == ["Bank", "GenericUrbanPOI"]


async def test_run_baseline_blank_tipo_poi_is_no_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_io(monkeypatch, pois=_two_pois())
    resp = await run_baseline(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        tipo_poi="   ",
    )
    # tipo_poi vuoto/whitespace = nessun filtro (non un set vuoto di POI)
    assert [p.terminus_class for p in resp.poi] == ["Bank", "GenericUrbanPOI"]


async def test_run_baseline_tipo_poi_no_match_yields_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_io(monkeypatch, pois=_two_pois())
    resp = await run_baseline(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        tipo_poi="Hospital",
    )
    # nessun POI di quella classe -> lista vuota, nessun errore
    assert resp.poi == []
    assert resp.risk_models == []


# --- #236: braccio di ablazione «LLM senza contributo ontologico nel prompt» ---


async def test_run_no_ontology_prompt_hides_the_ontology_from_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Il modello vede i punti, non i rischi che l'ontologia associa alle classi.

    E' l'unica variabile che il braccio manipola: se gli hazard finissero
    comunque nel prompt, il confronto con ``analyze`` non isolerebbe nulla.
    """
    _patch_io(monkeypatch)
    client = _RecordingLLMClient()

    await run_no_ontology_prompt(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=client,
    )

    system, user = client.calls[0]
    assert system == NO_ONTOLOGY_SYSTEM_PROMPT
    assert "Bank_robbery" not in user
    assert "Hazard verificati" not in user
    assert "  POI: Banca A (Bank)" in user


async def test_run_no_ontology_prompt_keeps_the_structured_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stessa response di ``run_analysis``: cambia il prompt, non il contratto.

    ``risk_models``, ``sparql_path`` e ``confidence_summary`` restano ontologici
    perche' sono il dato ancorato con cui ``eval/metrics.py`` costruisce gli
    ancoraggi: se divergessero tra i bracci, il proxy misurerebbe denominatori
    diversi e il confronto non sarebbe leggibile.
    """
    _patch_io(monkeypatch)
    resp = await run_no_ontology_prompt(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_FakeLLMClient(_llm_response()),
    )
    riferimento = await run_analysis(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_FakeLLMClient(_llm_response()),
    )

    assert resp.fallback is False
    assert resp.narrativa is not None
    assert resp.narrativa.startswith("Analisi:")
    assert resp.risk_models == riferimento.risk_models
    assert resp.confidence_summary == riferimento.confidence_summary
    assert [(p.id, p.confidence, p.sparql_path) for p in resp.poi] == [
        (p.id, p.confidence, p.sparql_path) for p in riferimento.poi
    ]
    assert resp.contesto_hash == riferimento.contesto_hash


async def test_run_no_ontology_prompt_splits_prose_on_its_own_block_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La prosa per fonte si taglia sull'etichetta che il prompt ablato chiede.

    Quel prompt fa scrivere ``[SINTESI-LLM]`` (#236: il braccio non ha
    consultato alcuna ontologia e non lo dichiara). Tagliando la narrativa
    sull'etichetta dell'ALTRO braccio, il blocco misurato non verrebbe
    riconosciuto e finirebbe tutto in ``overview``: un campo che dice «nessuna
    attribuzione» dove il modello ha invece attribuito, sullo stesso testo che
    l'eval grada correttamente. Due letture divergenti dello stesso file.
    """
    _patch_io(monkeypatch)
    narrativa = (
        "Sintesi.\n\n"
        f"{LLM_SYNTHESIS_BLOCK_HEADER}\nFurto.\n\n"
        "Rischi dal contesto [CONTESTO]\nBorseggio."
    )
    response = LLMResponse(
        text=narrativa,
        llm_used="llama-3.3-70b-versatile",
        tokens_input=10,
        tokens_output=20,
        cache_hit=False,
        temperature=0.0,
        seed=0,
        prompt_hash="abc123",
    )
    resp = await run_no_ontology_prompt(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_FakeLLMClient(response),
    )
    assert resp.narrativa == narrativa  # invariata, come nel braccio completo
    assert resp.narrativa_fonti.overview == "Sintesi."
    assert resp.narrativa_fonti.ontologia == "Furto."
    assert resp.narrativa_fonti.contesto == "Borseggio."


def test_generated_response_has_no_default_measured_token() -> None:
    """Il token del blocco misurato lo dichiara il chiamante, sempre.

    Con un default, un terzo braccio che se lo dimenticasse erediterebbe
    ``[ONTOLOGIA]``: ``parse_source_prose`` non troverebbe la sua etichetta,
    tutta la prosa finirebbe in ``overview`` e la sua narrativa verrebbe misurata
    come NON-ATTRIBUZIONE (0.0/1.0) senza alcun errore — la classe di bug che
    #236 esiste per prevenire. Il tipo lo impedisce (pyright), questo test tiene
    il default fuori anche da una futura «comodita'».
    """
    param = inspect.signature(_generated_response).parameters["measured_token"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty


async def test_run_no_ontology_prompt_falls_back_on_llm_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stesso ramo di fallback strutturato del braccio completo."""
    _patch_io(monkeypatch)
    resp = await run_no_ontology_prompt(
        "Roma",
        "Centro",
        executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
        llm_client=_RaisingLLMClient(),
    )
    assert resp.fallback is True
    assert resp.narrativa == ""
    assert resp.risk_models[0].risks[0].hazard == "Bank_robbery"


async def test_run_no_ontology_prompt_does_not_touch_the_zone_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Il braccio sperimentale non deposita contesto per ``/analyze/poi``.

    ``run_analysis`` popola la cache di zona perche' serve il prodotto (un clic
    su un POI non deve rifare Overpass). Questo braccio non e' servito da alcuna
    rotta: lasciare li' un contesto costruito per un'ablazione sarebbe stato di
    processo che nessuno ha chiesto.
    """
    from crime_risk_analyzer import zone_context_cache

    _patch_io(monkeypatch)
    zone_context_cache.clear()
    try:
        await run_no_ontology_prompt(
            "Roma",
            "Centro",
            executor=_FakeProfiler({"Bank": _BANK_PROFILE}),
            llm_client=_FakeLLMClient(_llm_response()),
        )
        assert zone_context_cache.get("Roma", "Centro") is None
    finally:
        zone_context_cache.clear()


# --- #119: max_length sulla domanda (bound su token/costo/superficie) ---


def test_analyze_request_rejects_overlong_domanda() -> None:
    # oltre il tetto (500): la validazione Pydantic respinge la richiesta
    with pytest.raises(ValidationError):
        AnalyzeRequest(citta="Roma", zona="Centro", domanda="x" * 501)


def test_analyze_request_accepts_domanda_at_max_length() -> None:
    # esattamente al tetto: ammessa (il bound e' inclusivo)
    req = AnalyzeRequest(citta="Roma", zona="Centro", domanda="x" * 500)
    assert req.domanda is not None
    assert len(req.domanda) == 500


# --- #170: max_length sulla zona (free-text verso Nominatim + chiave _CACHE) ---


def test_analyze_request_rejects_overlong_zona() -> None:
    # oltre il tetto (200): la validazione Pydantic respinge la richiesta
    with pytest.raises(ValidationError):
        AnalyzeRequest(citta="Roma", zona="x" * 201)


def test_analyze_request_accepts_zona_at_max_length() -> None:
    # esattamente al tetto: ammessa (il bound e' inclusivo)
    req = AnalyzeRequest(citta="Roma", zona="x" * 200)
    assert len(req.zona) == 200


def test_baseline_request_rejects_overlong_zona() -> None:
    with pytest.raises(ValidationError):
        BaselineRequest(citta="Roma", zona="x" * 201)


def test_baseline_request_accepts_zona_at_max_length() -> None:
    req = BaselineRequest(citta="Roma", zona="x" * 200)
    assert len(req.zona) == 200


# --- #184: guardia anti-scoring estesa al contratto di risposta /analyze ---
# Stesso pattern exact-set di #118 (test_risk.py::PoiRiskProfile): l'insieme dei
# campi e' blindato, cosi' un futuro campo di scoring numerico di pericolosita'
# (es. ``score``/``risk_level``/``livello_rischio``) fa fallire il test e forza
# una revisione cosciente del vincolo legale (_project.md §Vincoli).


def test_analyze_response_has_no_numeric_danger_scoring_field() -> None:
    """Contratto della risposta ``/analyze``: nessuno scoring numerico di
    pericolosita' (_project.md §Vincoli). I campi numerici presenti
    (``latenza_ms``/``tokens_input``/``tokens_output``) misurano costo e
    performance della run, NON la magnitudo del pericolo: sono legittimi. Un
    campo di rating aggiunto qui romperebbe l'insieme esatto.

    ``contesto_hash`` (#242) e' un digest opaco di IDENTITA' del contesto, non
    una misura: non gradua nulla e non e' confrontabile per ordine."""
    assert set(AnalyzeResponse.model_fields) == {
        "citta",
        "zona_normalizzata",
        "poi",
        "risk_models",
        "narrativa",
        "narrativa_fonti",
        "confidence_summary",
        "llm_used",
        "latenza_ms",
        "tokens_input",
        "tokens_output",
        "repro",
        "cache_hit",
        "fallback",
        "contesto_hash",
    }


def test_poi_out_has_no_numeric_danger_scoring_field() -> None:
    """Il POI dello schema ``/analyze`` porta coordinate (``lat``/``lon``,
    numeriche legittime) e un ``confidence`` QUALITATIVO (forza probatoria, non
    pericolosita'). L'insieme esatto impedisce di intrufolare un punteggio di
    rischio per-POI (es. ``risk_score``), vietato da _project.md §Vincoli."""
    assert set(PoiOut.model_fields) == {
        "id",
        "name",
        "terminus_class",
        "lat",
        "lon",
        "confidence",
        "sparql_path",
        "terminus_label_it",
        "terminus_label_en",
        # #256: gli assi TERMINUS oltre agli hazard. Sono ELENCHI QUALITATIVI di
        # entita' ancorate, nessun conteggio e nessuna gradazione: non aprono il
        # vettore dello scoring che questo test difende. Lo stakeholder non c'e':
        # il vocabolario controllato non lo copre (vedi rag/grounding.py).
        "critical_events",
        "vulnerabilities",
    }


def test_poi_out_ontology_axes_reject_numeric_value() -> None:
    """Vettore oltre l'exact-set: cambio di TIPO di un asse in un numero.

    L'insieme esatto intercetta l'AGGIUNTA di un campo, non la sostituzione di una
    lista qualitativa con un conteggio — che sarebbe scoring travestito (#184 aveva
    riconosciuto lo stesso vettore per la ``confidence``). Pydantic lo rifiuta: qui
    lo si pinna, cosi' un refactor futuro non lo apre in silenzio."""
    for asse in ("critical_events", "vulnerabilities"):
        with pytest.raises(ValidationError):
            PoiOut(
                id="1",
                name="Banca A",
                terminus_class="Bank",
                lat=41.9,
                lon=12.5,
                **{asse: 3},  # pyright: ignore[reportArgumentType]
            )


def test_ontology_item_has_no_numeric_danger_scoring_field() -> None:
    """L'entita' di un asse non-hazard porta nome, citazione ed etichette.

    Nessun campo numerico e nessun livello: un ``peso``/``gravita'`` qui sarebbe
    esattamente lo scoring di pericolosita' vietato (_project.md §Vincoli), ed e' il
    posto piu' probabile dove intrufolarlo ora che gli assi sono quattro."""
    from crime_risk_analyzer.orchestrator import OntologyItem

    assert set(OntologyItem.model_fields) == {
        "name",
        "source",
        "label_it",
        "label_en",
    }


def test_poi_out_confidence_rejects_numeric_value() -> None:
    """Vettore #184 oltre l'exact-set (cambio di TIPO, non aggiunta di campo): il
    ``confidence`` del POI e' categoriale (Literal). Un valore NUMERICO e'
    rifiutato, cosi' non puo' diventare un punteggio di rischio per-POI travestito
    (_project.md §Vincoli): il test diventa rosso se il campo passasse a float."""
    with pytest.raises(ValidationError):
        PoiOut(
            id="1",
            name="Banca A",
            terminus_class="Bank",
            lat=41.89,
            lon=12.49,
            confidence=0.5,  # pyright: ignore[reportArgumentType]
        )
