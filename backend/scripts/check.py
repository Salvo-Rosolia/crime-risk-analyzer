"""Runner unico dei controlli di qualità del backend.

Esegue in sequenza format-check, lint, type-check e test ESEGUENDO TUTTI gli
step (non si ferma al primo errore), stampa un riepilogo e aggrega l'esito in
un solo exit code.

Uso:
    uv run python scripts/check.py          # bundle completo (verifica)
    uv run python scripts/check.py format   # applica `ruff format`

I tool sono invocati come moduli (`sys.executable -m <tool>`) per evitare il bug
del trampoline uv con gli spazi nel path (i console-script .exe falliscono).
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence

# (etichetta, comando) di ogni controllo, nell'ordine di esecuzione.
CHECKS: tuple[tuple[str, list[str]], ...] = (
    ("ruff format --check", [sys.executable, "-m", "ruff", "format", "--check", "."]),
    ("ruff check", [sys.executable, "-m", "ruff", "check", "."]),
    ("pyright", [sys.executable, "-m", "pyright"]),
    ("pytest", [sys.executable, "-m", "pytest"]),
)


def _run(cmd: Sequence[str]) -> int:
    """Esegue un comando ereditando stdout/stderr; ritorna il suo exit code."""
    return subprocess.run(list(cmd)).returncode


def main() -> int:
    """Esegue tutti i controlli; ritorna 0 se e solo se passano tutti."""
    results: list[tuple[str, int]] = []
    for label, cmd in CHECKS:
        print(f"\n=== {label} ===", flush=True)
        results.append((label, _run(cmd)))

    print("\n=== riepilogo ===", flush=True)
    for label, code in results:
        marker = "[PASS]" if code == 0 else "[FAIL]"
        print(f"{marker} {label}")

    return 0 if all(code == 0 for _, code in results) else 1


def format_cmd() -> int:
    """Applica `ruff format` al codice (sottocomando `format`)."""
    return _run([sys.executable, "-m", "ruff", "format", "."])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "format":
        raise SystemExit(format_cmd())
    raise SystemExit(main())
