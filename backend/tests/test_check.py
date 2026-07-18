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


def test_check_runs_all_steps_in_declared_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() esegue TUTTI i controlli, nell'ordine di ``CHECKS``, come moduli
    (``python -m <tool>``): format-check → lint → type-check → test."""
    invoked: list[list[str]] = []

    def fake_run(cmd: list[str], *a: object, **k: object) -> _FakeCompleted:
        invoked.append(list(cmd))
        return _FakeCompleted(0)

    monkeypatch.setattr(check.subprocess, "run", fake_run)

    check.main()

    assert invoked == [list(cmd) for _label, cmd in check.CHECKS]
    # Superficie invariante attesa: i quattro tool nell'ordine giusto, via -m.
    tools = [cmd[cmd.index("-m") + 1] for cmd in invoked]
    assert tools == ["ruff", "ruff", "pyright", "pytest"]


def test_check_runs_all_steps_even_when_first_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invariante 'non si ferma al primo errore' (docstring dello script): anche
    se il primo step fallisce, tutti gli step vengono comunque eseguiti."""
    calls = {"n": 0}

    def fake_run(*a: object, **k: object) -> _FakeCompleted:
        calls["n"] += 1
        # Fallisce SOLO il primo step (format --check).
        return _FakeCompleted(1 if calls["n"] == 1 else 0)

    monkeypatch.setattr(check.subprocess, "run", fake_run)

    assert check.main() == 1
    assert calls["n"] == len(check.CHECKS)  # tutti gli step eseguiti, non solo il 1°


def test_format_cmd_invokes_ruff_format_and_returns_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Il sottocomando ``format`` lancia ``ruff format .`` (via -m) e propaga il
    returncode del processo."""
    invoked: list[list[str]] = []

    def fake_run(cmd: list[str], *a: object, **k: object) -> _FakeCompleted:
        invoked.append(list(cmd))
        return _FakeCompleted(7)

    monkeypatch.setattr(check.subprocess, "run", fake_run)

    assert check.format_cmd() == 7
    assert len(invoked) == 1
    cmd = invoked[0]
    assert cmd[cmd.index("-m") + 1 : cmd.index("-m") + 4] == ["ruff", "format", "."]
