"""Tests for the single quality-checks runner (scripts/check.py)."""

import pytest
from scripts import check


class _FakeCompleted:
    """Minimal stub of subprocess.CompletedProcess: exposes only returncode."""

    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def test_check_all_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """If every step returns 0, main() returns 0."""

    def fake_run(*a: object, **k: object) -> _FakeCompleted:
        return _FakeCompleted(0)

    monkeypatch.setattr(check.subprocess, "run", fake_run)

    assert check.main() == 0


def test_check_reports_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """If a step fails, main() returns 1 and that step is marked FAIL."""
    calls = {"n": 0}

    def fake_run(*a: object, **k: object) -> _FakeCompleted:
        calls["n"] += 1
        # Make only the third step of the sequence (pyright) fail.
        return _FakeCompleted(1 if calls["n"] == 3 else 0)

    monkeypatch.setattr(check.subprocess, "run", fake_run)

    assert check.main() == 1
    out = capsys.readouterr().out
    assert "[FAIL] pyright" in out


def test_check_runs_all_steps_in_declared_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() runs ALL the checks, in the order of ``CHECKS``, as modules
    (``python -m <tool>``): format-check -> lint -> type-check -> test."""
    invoked: list[list[str]] = []

    def fake_run(cmd: list[str], *a: object, **k: object) -> _FakeCompleted:
        invoked.append(list(cmd))
        return _FakeCompleted(0)

    monkeypatch.setattr(check.subprocess, "run", fake_run)

    check.main()

    assert invoked == [list(cmd) for _label, cmd in check.CHECKS]
    # Expected invariant surface: the four tools in the right order, via -m.
    tools = [cmd[cmd.index("-m") + 1] for cmd in invoked]
    assert tools == ["ruff", "ruff", "pyright", "pytest"]


def test_check_runs_all_steps_even_when_first_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invariant 'does not stop at the first error' (docstring of the script): even
    if the first step fails, all the steps are still executed."""
    calls = {"n": 0}

    def fake_run(*a: object, **k: object) -> _FakeCompleted:
        calls["n"] += 1
        # Only the first step fails (format --check).
        return _FakeCompleted(1 if calls["n"] == 1 else 0)

    monkeypatch.setattr(check.subprocess, "run", fake_run)

    assert check.main() == 1
    assert calls["n"] == len(check.CHECKS)  # all the steps executed, not just the 1st


def test_format_cmd_invokes_ruff_format_and_returns_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``format`` subcommand launches ``ruff format .`` (via -m) and propagates
    the process returncode."""
    invoked: list[list[str]] = []

    def fake_run(cmd: list[str], *a: object, **k: object) -> _FakeCompleted:
        invoked.append(list(cmd))
        return _FakeCompleted(7)

    monkeypatch.setattr(check.subprocess, "run", fake_run)

    assert check.format_cmd() == 7
    assert len(invoked) == 1
    cmd = invoked[0]
    assert cmd[cmd.index("-m") + 1 : cmd.index("-m") + 4] == ["ruff", "format", "."]
