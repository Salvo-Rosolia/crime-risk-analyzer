"""Test dell'endpoint ``GET /scenarios``.

Espone i 10 scenari demo precaricati (≥3 città, per dimostrare il city-agnostic;
spec ``backend/orchestrator.md`` §``GET /scenarios`` e ``spec-frontend.md``
§"10 Scenari pre-caricati"). La risposta è un array di ``ScenarioPreset``: la
*fonte unica* anche per il frontend, che popola le card scenario leggendo i campi
``id``/``city``/``zone``/``type`` e usa ``id`` come chiave di cache di fallback.
"""

from typing import cast

import httpx
from fastapi.testclient import TestClient

from crime_risk_analyzer.main import app

client = TestClient(app)

# `cast` + ignore puntuale: il tipo di `.get` di TestClient non è risolto da
# pyright strict con questa combinazione di versioni (difetto di stub di terze
# parti). Stesso pattern già adottato in test_health.py / test_cities.py.

EXPECTED_FIELDS = {"id", "city", "zone", "type", "zona"}

# Le tre zone di valutazione hanno una cache di analisi precalcolata
# (frontend/public/demo/cache/<id>.json): l'``id`` dello scenario deve coincidere
# con la chiave di quel file, altrimenti il fallback di cache del frontend rompe.
CACHED_SCENARIO_IDS = {"colosseo", "termini", "duomo"}


def _get_scenarios() -> list[dict[str, object]]:
    response = cast(httpx.Response, client.get("/scenarios"))  # pyright: ignore[reportUnknownMemberType]
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    return cast(list[dict[str, object]], payload)


def test_scenarios_returns_ten_presets() -> None:
    assert len(_get_scenarios()) == 10


def test_scenarios_each_has_canonical_fields() -> None:
    for scenario in _get_scenarios():
        assert EXPECTED_FIELDS <= set(scenario.keys())
        for field in EXPECTED_FIELDS:
            value = scenario[field]
            assert isinstance(value, str)
            assert value, f"campo {field!r} vuoto nello scenario {scenario}"


def test_scenarios_cover_at_least_three_cities() -> None:
    cities = {str(s["city"]) for s in _get_scenarios()}
    # Roma, Milano, Napoli sono garantite; Torino rafforza il city-agnostic.
    assert {"Roma", "Milano", "Napoli"} <= cities
    assert len(cities) >= 3


def test_scenarios_have_unique_ids() -> None:
    ids = [str(s["id"]) for s in _get_scenarios()]
    assert len(ids) == len(set(ids))


def test_scenarios_cached_zones_use_cache_keys_as_id() -> None:
    """Le 3 zone con cache devono esporre l'``id`` = chiave del file di cache."""
    ids = {str(s["id"]) for s in _get_scenarios()}
    assert CACHED_SCENARIO_IDS <= ids


def test_scenarios_zona_is_geocodable_city_pair() -> None:
    """``zona`` è la stringa pronta per il geocoding ("Zona, Città")."""
    for scenario in _get_scenarios():
        assert str(scenario["city"]) in str(scenario["zona"])
