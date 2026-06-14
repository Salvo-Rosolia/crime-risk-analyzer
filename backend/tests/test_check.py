"""Test del runner unico dei controlli di qualità (scripts/check.py)."""

import pytest
from scripts import check


class _FakeCompleted:
    """Stub minimale di subprocess.CompletedProcess: espone solo returncode."""

    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def test_check_all_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Se ogni step ritorna 0, main() ritorna 0."""

    def fake_run(*a: object, **k: object) -> _FakeCompleted:
        return _FakeCompleted(0)

    monkeypatch.setattr(check.subprocess, "run", fake_run)

    assert check.main() == 0


def test_check_reports_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Se uno step fallisce, main() ritorna 1 e quello step è marcato FAIL."""
    calls = {"n": 0}

    def fake_run(*a: object, **k: object) -> _FakeCompleted:
        calls["n"] += 1
        # Fa fallire solo il terzo step della sequenza (pyright).
        return _FakeCompleted(1 if calls["n"] == 3 else 0)

    monkeypatch.setattr(check.subprocess, "run", fake_run)

    assert check.main() == 1
    out = capsys.readouterr().out
    assert "[FAIL] pyright" in out
