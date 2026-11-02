"""Single runner of the backend quality checks.

Runs in sequence format-check, lint, type-check and tests RUNNING ALL the
steps (it does not stop at the first error), prints a summary and aggregates the outcome
into a single exit code.

Usage:
    uv run python scripts/check.py          # full bundle (verification)
    uv run python scripts/check.py format   # applies `ruff format`

The tools are invoked as modules (`sys.executable -m <tool>`) to avoid the uv
trampoline bug with spaces in the path (the .exe console-scripts fail).
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence

# (label, command) of each check, in execution order.
CHECKS: tuple[tuple[str, list[str]], ...] = (
    ("ruff format --check", [sys.executable, "-m", "ruff", "format", "--check", "."]),
    ("ruff check", [sys.executable, "-m", "ruff", "check", "."]),
    ("pyright", [sys.executable, "-m", "pyright"]),
    ("pytest", [sys.executable, "-m", "pytest"]),
)


def _run(cmd: Sequence[str]) -> int:
    """Runs a command inheriting stdout/stderr; returns its exit code."""
    return subprocess.run(list(cmd)).returncode


def main() -> int:
    """Runs all the checks; returns 0 if and only if they all pass."""
    results: list[tuple[str, int]] = []
    for label, cmd in CHECKS:
        print(f"\n=== {label} ===", flush=True)
        results.append((label, _run(cmd)))

    print("\n=== summary ===", flush=True)
    for label, code in results:
        marker = "[PASS]" if code == 0 else "[FAIL]"
        print(f"{marker} {label}")

    return 0 if all(code == 0 for _, code in results) else 1


def format_cmd() -> int:
    """Applies `ruff format` to the code (`format` subcommand)."""
    return _run([sys.executable, "-m", "ruff", "format", "."])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "format":
        raise SystemExit(format_cmd())
    raise SystemExit(main())
