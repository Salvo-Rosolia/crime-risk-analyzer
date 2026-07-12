"""Test del CORSMiddleware (#106).

Il deploy canonico e' same-origin (build Angular servita da FastAPI/StaticFiles):
li' il CORS non serve. Il middleware e' DIFESA IN PROFONDITA': abilita un
eventuale deploy split-origin e chiude i buchi cross-origin in dev su ``/health``
e ``/cities`` (non proxati da ``ng serve``, a differenza di ``/analyze`` e
``/analyze/baseline``). Opzione A: allowlist ESPLICITA da ``Settings``, mai
wildcard ``*`` (vincolo #106), ``allow_credentials=False`` (API stateless).

``cast`` + ignore puntuale sui metodi di ``TestClient``: il loro tipo non e'
risolto da pyright strict con questa combinazione di versioni (stesso pattern di
test_health.py / test_cities.py).
"""

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.main import app, create_app

client = TestClient(app)

_ALLOWED_ORIGIN = "http://localhost:4200"
_DISALLOWED_ORIGIN = "http://evil.example"
_ACAO = "access-control-allow-origin"
_ACAM = "access-control-allow-methods"


def test_cors_reflects_allowlisted_origin_on_health() -> None:
    """GET /health con origine allowlisted -> ACAO uguale a quell'origine (mai '*')."""
    response = cast(
        httpx.Response,
        client.get("/health", headers={"Origin": _ALLOWED_ORIGIN}),  # pyright: ignore[reportUnknownMemberType]
    )

    assert response.status_code == 200
    assert response.headers[_ACAO] == _ALLOWED_ORIGIN
    # Vincolo #106: il valore riflesso non deve MAI essere il wildcard.
    assert response.headers[_ACAO] != "*"


def test_cors_preflight_options_analyze_allows_post() -> None:
    """Preflight OPTIONS su /analyze da origine allowlisted -> POST tra i metodi.

    Il preflight e' intercettato dal middleware prima del routing: non tocca
    l'orchestrator ne' le dipendenze (ontologia/LLM), quindi e' deterministico.
    """
    response = cast(
        httpx.Response,
        client.options(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            headers={
                "Origin": _ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        ),
    )

    assert response.status_code == 200
    assert response.headers[_ACAO] == _ALLOWED_ORIGIN
    assert response.headers[_ACAO] != "*"
    assert "POST" in response.headers[_ACAM]


def test_cors_does_not_reflect_non_allowlisted_origin() -> None:
    """GET /health da origine NON allowlisted -> nessun ACAO per quell'origine.

    La richiesta arriva comunque (CORS e' enforcement lato browser), ma il
    server non emette l'header, quindi il browser bloccherebbe la lettura.
    """
    response = cast(
        httpx.Response,
        client.get("/health", headers={"Origin": _DISALLOWED_ORIGIN}),  # pyright: ignore[reportUnknownMemberType]
    )

    assert response.status_code == 200
    # L'origine ostile non viene riflessa e non compare alcun wildcard.
    assert response.headers.get(_ACAO) != _DISALLOWED_ORIGIN
    assert response.headers.get(_ACAO) != "*"


def test_cors_preflight_rejects_non_allowlisted_origin() -> None:
    """Preflight da origine NON allowlisted -> ACAO assente/non riflesso, mai '*'."""
    response = cast(
        httpx.Response,
        client.options(  # pyright: ignore[reportUnknownMemberType]
            "/analyze",
            headers={
                "Origin": _DISALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        ),
    )

    assert response.headers.get(_ACAO) != _DISALLOWED_ORIGIN
    assert response.headers.get(_ACAO) != "*"


def test_cors_allowlist_is_config_driven(monkeypatch: pytest.MonkeyPatch) -> None:
    """E' la CONFIG a guidare l'allowlist del middleware, non un hardcode.

    Difesa contro il falso-verde: se ``create_app`` fissasse
    ``allow_origins=["http://localhost:4200"]`` (il default), i test che usano
    l'origine di default passerebbero comunque. Qui l'origine allowlisted e'
    NON-default: viene riflessa solo se il middleware legge davvero
    ``settings.cors_allow_origins``, mentre il default NON deve piu' esserlo.

    La cache di ``get_settings`` viene svuotata prima (per far ricostruire una
    ``Settings`` dall'env) e ripristinata in teardown, cosi' il test non inquina
    gli altri (che condividono l'app di modulo costruita con il default).
    """
    custom_origin = "https://app.example.org"
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", f'["{custom_origin}"]')
    get_settings.cache_clear()
    try:
        fresh_client = TestClient(create_app())
        allowed = cast(
            httpx.Response,
            fresh_client.get("/health", headers={"Origin": custom_origin}),  # pyright: ignore[reportUnknownMemberType]
        )
        assert allowed.headers[_ACAO] == custom_origin
        assert allowed.headers[_ACAO] != "*"

        # Il default, se fosse hardcoded, verrebbe smascherato: non deve riflettersi.
        defaulted = cast(
            httpx.Response,
            fresh_client.get("/health", headers={"Origin": _ALLOWED_ORIGIN}),  # pyright: ignore[reportUnknownMemberType]
        )
        assert defaulted.headers.get(_ACAO) != _ALLOWED_ORIGIN
    finally:
        get_settings.cache_clear()
