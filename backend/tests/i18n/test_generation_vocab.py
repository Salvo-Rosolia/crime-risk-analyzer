from __future__ import annotations

from typing import Any

import pytest

from crime_risk_analyzer.rag import generation
from crime_risk_analyzer.rag.generation import build_context_str


@pytest.fixture(autouse=True)
def _stub_labels(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    it: dict[str, str] = {"Bank_robbery": "Rapina in banca"}

    def _it(k: str) -> str:
        return it.get(k, k)

    def _vocab(ids: list[str]) -> list[str]:
        return [it.get(i, i) for i in ids]

    monkeypatch.setattr(generation, "label_it", _it)
    monkeypatch.setattr(generation, "controlled_vocab_for", _vocab)


def _context() -> dict[str, Any]:
    return {
        "zona": "Centro",
        "validated_risks": [
            {
                "poi": "Banca X",
                "terminus_class": "Bank",
                "risks": [
                    {
                        "hazard": "Bank_robbery",
                        "tag": "ONTOLOGIA",
                        "confidence": "confermato",
                    }
                ],
                "vulnerabilities": [],
                "sparql_path": "Bank -> havingHazard -> Bank_robbery",
            }
        ],
    }


def test_context_includes_controlled_vocab_section() -> None:
    out = build_context_str(_context())
    assert "VOCABOLARIO CONTROLLATO" in out
    assert "Rapina in banca" in out


def test_context_shows_it_label_next_to_hazard() -> None:
    out = build_context_str(_context())
    assert "Bank_robbery / Rapina in banca" in out
