"""Report esteso del confronto modelli con K ripetizioni (#157).

Compone il riuso: fold delle ripetizioni (repeat.fold_arm) → record-media per
zona → compare.compare_records (tabelle #33) → decide_winner (verdetto) +
tabella varianza. Scrive <stem>.md e <stem>.json ESTESI, senza toccare
compare.py. Le tabelle CSV/MD/JSON di #33 restano il contratto stabile; qui si
AGGIUNGE varianza + vincitore.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from crime_risk_analyzer.eval.aggregate import load_runs
from crime_risk_analyzer.eval.compare import (
    Comparison,
    MetricValues,
    compare_records,
    to_json,
    to_markdown,
)
from crime_risk_analyzer.eval.repeat import FoldedArm, ZoneVariance, fold_arm
from crime_risk_analyzer.eval.schema import Metrics
from crime_risk_analyzer.eval.winner import (
    AXIS_PRECISION,
    Winner,
    decide_winner,
)

#: Caveat di scope (#157): l'asse allucinazione del verdetto e' il proxy testuale.
_SCOPE_NOTE = (
    "> **Nota (#157).** Verdetto sulle MEDIE; la ±std e' riportata ma non "
    "decide. L'asse `hallucination` e' il *proxy testuale* gia' in `Metrics`: "
    "il *tasso di intervento del filtro* e le *allucinazioni residue* (spec §2) "
    "sono deliverable separati, non inclusi qui."
)


def _fmt(axis: str, value: float) -> str:
    return f"{value:.{AXIS_PRECISION[axis]}f}"


def _k_of(a: FoldedArm, b: FoldedArm) -> int:
    """K = massimo numero di ripetizioni per zona (valide + scartate)."""
    return max(
        (v.n_reps + v.n_dropped for v in (*a.variances, *b.variances)),
        default=0,
    )


#: Getter tipizzati metrica→valore per le medie (``Metrics``, come in
#: ``ZoneComparison.a``/``b``): stessa mappatura asse→valore di compare.py.
_GETTERS: dict[str, Callable[[Metrics], float]] = {
    "grounding": lambda mt: mt.grounding,
    "hallucination": lambda mt: mt.hallucination,
    "latency_ms": lambda mt: float(mt.latency_ms),
    "cost_usd": lambda mt: mt.cost_usd,
}

#: Getter tipizzati metrica→valore per la deviazione standard (``MetricValues``,
#: come in ``ZoneVariance.std``): stessa mappatura asse→valore, tipo diverso
#: dell'input (std e' gia' float ovunque, incluso ``latency_ms``).
_STD_GETTERS: dict[str, Callable[[MetricValues], float]] = {
    "grounding": lambda s: s.grounding,
    "hallucination": lambda s: s.hallucination,
    "latency_ms": lambda s: s.latency_ms,
    "cost_usd": lambda s: s.cost_usd,
}


def variance_markdown(
    comparison: Comparison, folded_a: FoldedArm, folded_b: FoldedArm, k: int
) -> str:
    """Tabella `media ± std` per zona/metrica sui due bracci (K ripetizioni)."""
    std_a: dict[tuple[str, str], ZoneVariance] = {
        (v.citta, v.zona): v for v in folded_a.variances
    }
    std_b: dict[tuple[str, str], ZoneVariance] = {
        (v.citta, v.zona): v for v in folded_b.variances
    }
    metrics = ("grounding", "hallucination", "latency_ms", "cost_usd")
    n_col_a = f"n_{comparison.label_a}"
    n_col_b = f"n_{comparison.label_b}"
    cols = ["citta", "zona"]
    for m in metrics:
        cols.extend([f"{m}_{comparison.label_a}", f"{m}_{comparison.label_b}"])
    cols.extend([n_col_a, n_col_b])
    lines = [
        f"### Varianza su K={k} ripetizioni (media ± std)",
        "",
        f"> Colonne {n_col_a}/{n_col_b} = ripetizioni valide/totali per zona "
        "(le run in ERROR sono escluse da media e std).",
        "",
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for z in comparison.zones:
        key = (z.citta, z.zona)
        cells = [z.citta, z.zona]
        for m in metrics:
            mean_a = _GETTERS[m](z.a)
            mean_b = _GETTERS[m](z.b)
            sa = _STD_GETTERS[m](std_a[key].std)
            sb = _STD_GETTERS[m](std_b[key].std)
            cells.append(f"{_fmt(m, mean_a)} ± {_fmt(m, sa)}")
            cells.append(f"{_fmt(m, mean_b)} ± {_fmt(m, sb)}")
        va = std_a[key]
        vb = std_b[key]
        cells.append(f"{va.n_reps}/{va.n_reps + va.n_dropped}")
        cells.append(f"{vb.n_reps}/{vb.n_reps + vb.n_dropped}")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def winner_markdown(winner: Winner, k: int) -> str:
    """Sezione vincitore: verdetto + catena dei confronti + caveat di scope."""
    lines = [f"### Vincitore (criterio lessicografico, K={k})", ""]
    if winner.winner is None:
        lines.append(
            f"**Pareggio.** `{winner.label_a}` e `{winner.label_b}` sono pari su "
            "tutti e 4 gli assi alla precisione di stampa."
        )
    else:
        dec = winner.deciding_axis
        assert dec is not None  # winner!=None → deciding_axis valorizzato
        last = winner.chain[-1]
        lines.append(
            f"**Vincitore: `{winner.winner}`** — deciso su `{dec}` "
            f"({_fmt(dec, last.value_a)} vs {_fmt(dec, last.value_b)})."
        )
    lines.append("")
    lines.append("Catena dei confronti (parità = a precisione di stampa):")
    lines.append(f"| asse | {winner.label_a} | {winner.label_b} | esito |")
    lines.append("| --- | --- | --- | --- |")
    for c in winner.chain:
        if c.outcome == "tie":
            esito = "pari"
        else:
            esito = winner.label_a if c.outcome == "a" else winner.label_b
        lines.append(
            f"| {c.axis} | {_fmt(c.axis, c.value_a)} | "
            f"{_fmt(c.axis, c.value_b)} | {esito} |"
        )
    lines.append("")
    lines.append(_SCOPE_NOTE)
    return "\n".join(lines) + "\n"


def build_repeated_report(
    results_dir: Path,
    experiment_a: str,
    experiment_b: str,
    *,
    label_a: str | None = None,
    label_b: str | None = None,
    stem: str | None = None,
) -> tuple[Path, Path]:
    """Carica i due esperimenti, ripiega le ripetizioni, confronta e scrive report.

    Scrive ``<stem>.md`` (tabelle #33 + varianza + vincitore) e ``<stem>.json``
    (comparison #33 + oggetti ``winner`` e ``variance``). Ritorna i due path.
    """
    la = label_a or experiment_a
    lb = label_b or experiment_b
    folded_a = fold_arm(load_runs(results_dir, experiment=experiment_a))
    folded_b = fold_arm(load_runs(results_dir, experiment=experiment_b))
    comparison = compare_records(
        folded_a.mean_records, folded_b.mean_records, label_a=la, label_b=lb
    )
    winner = decide_winner(comparison.mean_a, comparison.mean_b, label_a=la, label_b=lb)
    k = _k_of(folded_a, folded_b)
    md = (
        "\n".join(
            [
                to_markdown(comparison).rstrip("\n"),
                "",
                variance_markdown(comparison, folded_a, folded_b, k).rstrip("\n"),
                "",
                winner_markdown(winner, k).rstrip("\n"),
            ]
        )
        + "\n"
    )
    payload = {
        "comparison": json.loads(to_json(comparison)),
        "winner": winner.model_dump(),
        "variance": {
            "k": k,
            "label_a": la,
            "label_b": lb,
            "arm_a": [v.model_dump() for v in folded_a.variances],
            "arm_b": [v.model_dump() for v in folded_b.variances],
        },
    }
    resolved = stem or f"{experiment_a}_vs_{experiment_b}_repeated"
    md_path = results_dir / f"{resolved}.md"
    json_path = results_dir / f"{resolved}.json"
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return md_path, json_path
