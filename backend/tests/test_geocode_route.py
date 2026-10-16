"""Test endpoint GET /geocode (#318)."""

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer import geocoding
from crime_risk_analyzer.main import app

client = TestClient(app)


def _fake_geocode_found(query: str) -> tuple[float, float] | None:
    return (41.9, 12.5)


def _fake_geocode_not_found(query: str) -> tuple[float, float] | None:
    return None


def test_geocode_successo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(geocoding, "geocode_freeform", _fake_geocode_found)
    response = cast(
        httpx.Response, client.get("/geocode", params={"query": "Duomo di Milano"})
    )  # pyright: ignore[reportUnknownMemberType]
    assert response.status_code == 200
    assert response.json() == {"lat": 41.9, "lon": 12.5}


def test_geocode_non_trovato(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(geocoding, "geocode_freeform", _fake_geocode_not_found)
    response = cast(httpx.Response, client.get("/geocode", params={"query": "xyzxyz"}))  # pyright: ignore[reportUnknownMemberType]
    assert response.status_code == 404


#: Tutti i caratteri che ``str.split()`` tratta come spazio (``isspace``),
#: compresi i separatori U+001C-U+001F che il ``\s`` di una regex non conta.
_SPAZI_DI_SPLIT = [chr(c) for c in range(0x3001) if chr(c).isspace()]


@pytest.mark.parametrize(
    "query",
    ["", " ", "   ", "\t \n", "\x1c", "\x1f", " ", " \x1d \x1e "],
)
def test_geocode_query_vuota_o_solo_spazi_422(
    monkeypatch: pytest.MonkeyPatch, query: str
) -> None:
    """Query vuota o di soli spazi: 422 di validazione, niente Nominatim (#376)."""
    calls: list[str] = []

    def _recording(q: str) -> tuple[float, float] | None:
        calls.append(q)
        return (41.9, 12.5)

    monkeypatch.setattr(geocoding, "geocode_freeform", _recording)
    response = cast(httpx.Response, client.get("/geocode", params={"query": query}))  # pyright: ignore[reportUnknownMemberType]

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["loc"] == ["query", "query"]
    assert detail[0]["type"] == "value_error"
    assert calls == []


@pytest.mark.parametrize("spazio", _SPAZI_DI_SPLIT, ids=lambda s: f"U+{ord(s):04X}")
def test_geocode_validazione_coerente_con_la_chiave(
    monkeypatch: pytest.MonkeyPatch, spazio: str
) -> None:
    """Ogni testo con chiave di cache vuota e' un 422: stesso criterio (#376).

    Se la validazione usasse un'altra nozione di spazio (per esempio il ``\\s``
    di una regex), un carattere come U+001C passerebbe, arriverebbe a Nominatim
    e finirebbe in cache sotto la chiave ``""``.
    """
    calls: list[str] = []

    def _recording(q: str) -> tuple[float, float] | None:
        calls.append(q)
        return (41.9, 12.5)

    monkeypatch.setattr(geocoding, "geocode_freeform", _recording)
    query = spazio * 3
    assert geocoding._freeform_key(query) == ""  # pyright: ignore[reportPrivateUsage]

    response = cast(httpx.Response, client.get("/geocode", params={"query": query}))  # pyright: ignore[reportUnknownMemberType]

    assert response.status_code == 422
    assert calls == []


def test_geocode_query_con_spazi_ai_bordi_passa_grezza(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una query valida con spazi ai bordi non e' respinta e arriva com'e' (#376)."""
    calls: list[str] = []

    def _recording(q: str) -> tuple[float, float] | None:
        calls.append(q)
        return (41.9, 12.5)

    monkeypatch.setattr(geocoding, "geocode_freeform", _recording)
    response = cast(
        httpx.Response, client.get("/geocode", params={"query": "  Colosseo "})
    )  # pyright: ignore[reportUnknownMemberType]

    assert response.status_code == 200
    assert calls == ["  Colosseo "]


def test_geocode_query_oltre_200_caratteri_422() -> None:
    """Il tetto di lunghezza resta (#318): stessa forma d'errore del controllo vuoto."""
    response = cast(httpx.Response, client.get("/geocode", params={"query": "a" * 201}))  # pyright: ignore[reportUnknownMemberType]
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "query"]
