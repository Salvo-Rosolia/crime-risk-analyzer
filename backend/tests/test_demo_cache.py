"""Test del loader di cache demo (#21).

Contratto (generation.md §Cache locale per demo, spec-root §C1): quando un'API
esterna e' down, in demo il sistema serve la risposta precalcolata dello scenario
da ``demo/cache/{scenario_id}.json`` invece di fallire (e *senza* failover Groq).
Qui si testa solo il loader in isolamento: niente rete, niente orchestrator.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crime_risk_analyzer.demo_cache import (
    DemoCacheError,
    DemoCacheNotFoundError,
    load_demo_cache,
)


def _write_cache(cache_dir: Path, scenario_id: str, payload: dict[str, object]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{scenario_id}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_loads_scenario_payload(tmp_path: Path) -> None:
    payload: dict[str, object] = {"scenario_id": "colosseo", "narrativa": "x"}
    _write_cache(tmp_path, "colosseo", payload)

    result = load_demo_cache("colosseo", cache_dir=tmp_path)

    assert result == payload


def test_missing_scenario_raises_not_found(tmp_path: Path) -> None:
    with pytest.raises(DemoCacheNotFoundError):
        load_demo_cache("inesistente", cache_dir=tmp_path)


def test_missing_scenario_is_a_demo_cache_error(tmp_path: Path) -> None:
    # DemoCacheNotFoundError e' una specializzazione di DemoCacheError: chi
    # gestisce il fallback puo' intercettare la classe base.
    with pytest.raises(DemoCacheError):
        load_demo_cache("inesistente", cache_dir=tmp_path)


def test_invalid_json_raises_demo_cache_error(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "rotto.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(DemoCacheError):
        load_demo_cache("rotto", cache_dir=tmp_path)


def test_non_object_json_raises_demo_cache_error(tmp_path: Path) -> None:
    # La cache di /analyze e' un oggetto JSON: un array al top-level e' invalido.
    (tmp_path / "lista.json").write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(DemoCacheError):
        load_demo_cache("lista", cache_dir=tmp_path)


def test_path_traversal_is_rejected(tmp_path: Path) -> None:
    # Lo scenario_id e' una chiave, non un path: separatori/relativi sono rifiutati
    # prima di toccare il filesystem (no directory traversal).
    with pytest.raises(DemoCacheError):
        load_demo_cache("../secret", cache_dir=tmp_path)


def test_dot_component_without_separator_is_rejected(tmp_path: Path) -> None:
    # ``.`` non contiene separatori ma non e' un nome di file valido
    # (Path(".").name == ""): deve essere rifiutato prima di toccare il fs.
    with pytest.raises(DemoCacheError):
        load_demo_cache(".", cache_dir=tmp_path)


def test_unreadable_cache_raises_demo_cache_error(tmp_path: Path) -> None:
    # Un OSError diverso da "file assente" (qui: il path e' una directory, non un
    # file) e' incapsulato in DemoCacheError, non propagato grezzo.
    (tmp_path / "dir.json").mkdir(parents=True)

    with pytest.raises(DemoCacheError):
        load_demo_cache("dir", cache_dir=tmp_path)
