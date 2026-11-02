"""Tests for the GET /geocode endpoint (#318)."""

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


def test_geocode_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(geocoding, "geocode_freeform", _fake_geocode_found)
    response = cast(
        httpx.Response, client.get("/geocode", params={"query": "Duomo di Milano"})
    )  # pyright: ignore[reportUnknownMemberType]
    assert response.status_code == 200
    assert response.json() == {"lat": 41.9, "lon": 12.5}


def test_geocode_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(geocoding, "geocode_freeform", _fake_geocode_not_found)
    response = cast(httpx.Response, client.get("/geocode", params={"query": "xyzxyz"}))  # pyright: ignore[reportUnknownMemberType]
    assert response.status_code == 404


#: All the characters that ``str.split()`` treats as space (``isspace``),
#: including the U+001C-U+001F separators that the ``\s`` of a regex does not count.
_SPLIT_SPACES = [chr(c) for c in range(0x3001) if chr(c).isspace()]


@pytest.mark.parametrize(
    "query",
    ["", " ", "   ", "\t \n", "\x1c", "\x1f", " ", " \x1d \x1e "],
)
def test_geocode_query_empty_or_only_spaces_422(
    monkeypatch: pytest.MonkeyPatch, query: str
) -> None:
    """Empty or whitespace-only query: validation 422, no Nominatim (#376)."""
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


@pytest.mark.parametrize("space_char", _SPLIT_SPACES, ids=lambda s: f"U+{ord(s):04X}")
def test_geocode_validation_consistent_with_the_key(
    monkeypatch: pytest.MonkeyPatch, space_char: str
) -> None:
    """Every text with an empty cache key is a 422: same criterion (#376).

    If the validation used another notion of space (for example the ``\\s`` of
    a regex), a character like U+001C would pass, reach Nominatim and end up in
    the cache under the key ``""``.
    """
    calls: list[str] = []

    def _recording(q: str) -> tuple[float, float] | None:
        calls.append(q)
        return (41.9, 12.5)

    monkeypatch.setattr(geocoding, "geocode_freeform", _recording)
    query = space_char * 3
    assert geocoding._freeform_key(query) == ""  # pyright: ignore[reportPrivateUsage]

    response = cast(httpx.Response, client.get("/geocode", params={"query": query}))  # pyright: ignore[reportUnknownMemberType]

    assert response.status_code == 422
    assert calls == []


def test_geocode_query_with_edge_spaces_passes_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid query with edge spaces is not rejected and arrives as is (#376)."""
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


def test_geocode_query_over_200_characters_422() -> None:
    """The length cap stays (#318): same error shape as the empty check."""
    response = cast(httpx.Response, client.get("/geocode", params={"query": "a" * 201}))  # pyright: ignore[reportUnknownMemberType]
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "query"]
