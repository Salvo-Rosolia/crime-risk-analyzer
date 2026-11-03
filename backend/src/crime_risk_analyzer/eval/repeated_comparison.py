"""Extended report of the model comparison with K repetitions (#157).

Composes the reuse: fold of the repetitions (repeat.fold_arm) -> mean-record per
zone -> compare.compare_records (tables #33) -> decide_winner (verdict) +
variance table. Writes EXTENDED <stem>.md and <stem>.json, without touching
compare.py. The CSV/MD/JSON tables of #33 stay the stable contract; here
variance + winner are ADDED.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from crime_risk_analyzer.eval.aggregate import load_runs
from crime_risk_analyzer.eval.compare import (
    ISTAT_NO_WINNER_REASON,
    OPERATIONAL_AXES_NOTE,
    VACUOUS_REASON,
    Comparison,
    MetricValues,
    NoUsableOutputError,
    VacuousZone,
    compare_records,
    guard_no_overwrite,
    has_vacuous_quality_axes,
    is_ontology_isolating_pair,
    risk_anchoring_pointer,
    to_json,
    to_markdown,
    vacuity_subject,
    write_no_usable_output_report,
)
from crime_risk_analyzer.eval.repeat import FoldedArm, ZoneVariance, fold_arm
from crime_risk_analyzer.eval.schema import Metrics
from crime_risk_analyzer.eval.winner import (
    AXIS_PRECISION,
    Winner,
    decide_winner,
)

logger = logging.getLogger(__name__)

#: Scope caveat (#157): the hallucination axis of the verdict is the textual proxy.
_SCOPE_NOTE = (
    "> **Nota (#157).** Verdetto sulle MEDIE; la ±std e' riportata ma non "
    "decide. L'asse `hallucination` e' il *proxy testuale* gia' in `Metrics`: "
    "il *tasso di intervento del filtro* e le *allucinazioni residue* (spec §2) "
    "sono deliverable separati, non inclusi qui."
)


def _fmt(axis: str, value: float) -> str:
    return f"{value:.{AXIS_PRECISION[axis]}f}"


def _k_of(a: FoldedArm, b: FoldedArm) -> int:
    """K = maximum number of repetitions per zone (valid + discarded)."""
    return max(
        (v.n_reps + v.n_dropped for v in (*a.variances, *b.variances)),
        default=0,
    )


def _k_range(a: FoldedArm, b: FoldedArm) -> tuple[int, int]:
    """(min, max) of total repetitions (valid + discarded) across zones/arms.

    ``min != max`` -> inhomogeneous K: arms with different --repeat or partial runs.
    """
    ks = [v.n_reps + v.n_dropped for v in (*a.variances, *b.variances)]
    return (min(ks), max(ks)) if ks else (0, 0)


#: Typed metric->value getters for the means (``Metrics``, as in
#: ``ZoneComparison.a``/``b``): same axis->value mapping as compare.py.
_GETTERS: dict[str, Callable[[Metrics], float]] = {
    "grounding": lambda mt: mt.grounding,
    "hallucination": lambda mt: mt.hallucination,
    "latency_ms": lambda mt: float(mt.latency_ms),
    "cost_usd": lambda mt: mt.cost_usd,
}

#: Typed metric->value getters for the standard deviation (``MetricValues``,
#: as in ``ZoneVariance.std``): same axis->value mapping, different type
#: of the input (std is already float everywhere, including ``latency_ms``).
_STD_GETTERS: dict[str, Callable[[MetricValues], float]] = {
    "grounding": lambda s: s.grounding,
    "hallucination": lambda s: s.hallucination,
    "latency_ms": lambda s: s.latency_ms,
    "cost_usd": lambda s: s.cost_usd,
}


def variance_markdown(
    comparison: Comparison,
    folded_a: FoldedArm,
    folded_b: FoldedArm,
    k: int,
    *,
    k_hi: int | None = None,
) -> str:
    """`mean ± std` table per zone/metric on the two arms (K repetitions).

    ``k_hi`` (Task 3, #165.2): if set and different from ``k``, the header
    shows the range ``K={k}..{k_hi}`` instead of the single maximum ``K``.
    """
    std_a: dict[tuple[str, str], ZoneVariance] = {
        (v.citta, v.zona): v for v in folded_a.variances
    }
    std_b: dict[tuple[str, str], ZoneVariance] = {
        (v.citta, v.zona): v for v in folded_b.variances
    }
    metrics = ("grounding", "hallucination", "latency_ms", "cost_usd")
    n_col_a = f"n_{comparison.label_a}"
    n_col_b = f"n_{comparison.label_b}"
    nfb_col_a = f"n_fallback_{comparison.label_a}"
    nfb_col_b = f"n_fallback_{comparison.label_b}"
    cols = ["citta", "zona"]
    for m in metrics:
        cols.extend([f"{m}_{comparison.label_a}", f"{m}_{comparison.label_b}"])
    cols.extend([n_col_a, n_col_b, nfb_col_a, nfb_col_b])
    k_label = f"{k}" if k_hi is None or k_hi == k else f"{k}..{k_hi}"
    lines = [
        f"### Varianza su K={k_label} ripetizioni (media ± std)",
        "",
        f"> Colonne {n_col_a}/{n_col_b} = ripetizioni valide/totali per zona; "
        f"{nfb_col_a}/{nfb_col_b} = di cui in FALLBACK (escluse da media e std, "
        "come le ERROR).",
        "",
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for z in comparison.zones:
        key = (z.citta, z.zona)
        cells = [z.citta, z.zona]
        va = std_a[key]
        vb = std_b[key]
        for m in metrics:
            mean_a = _GETTERS[m](z.a)
            mean_b = _GETTERS[m](z.b)
            sa = _STD_GETTERS[m](va.std)
            sb = _STD_GETTERS[m](vb.std)
            cells.append(
                "n/d" if va.n_reps < 2 else f"{_fmt(m, mean_a)} ± {_fmt(m, sa)}"
            )
            cells.append(
                "n/d" if vb.n_reps < 2 else f"{_fmt(m, mean_b)} ± {_fmt(m, sb)}"
            )
        cells.append(f"{va.n_reps}/{va.n_reps + va.n_dropped}")
        cells.append(f"{vb.n_reps}/{vb.n_reps + vb.n_dropped}")
        cells.append(str(va.n_fallback))
        cells.append(str(vb.n_fallback))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _n_reps_range(folded: FoldedArm) -> tuple[int, int]:
    """Min/max valid repetitions (n_reps) among the arm's zones (0,0 if empty)."""
    reps = [v.n_reps for v in folded.variances]
    return (min(reps), max(reps)) if reps else (0, 0)


def winner_markdown(
    winner: Winner,
    k: int,
    *,
    folded_a: FoldedArm | None = None,
    folded_b: FoldedArm | None = None,
    k_hi: int | None = None,
) -> str:
    """Outcome section of the proxy criterion: caveat, exploratory verdict, chain.

    The label is deliberately *exploratory* (E, #164): the outcome is on the textual
    PROXY, not on the 'true' metric section 2. The ``_SCOPE_NOTE`` PRECEDES the verdict.
    If ``folded_a``/``folded_b`` are supplied, below the verdict the sampling
    basis is printed (n_reps/range, F #164). ``k_hi`` (Task 3, #165.2): if
    set and different from ``k``, the header shows the range ``K={k}..{k_hi}``.

    Without a winner there are two different sentences, because they are two different
    facts: the tie on all axes (#157) and the verdict not decidable because the
    tie-break on speed/cost is excluded (#236, ``Winner.no_winner_reason``).
    """
    k_label = f"{k}" if k_hi is None or k_hi == k else f"{k}..{k_hi}"
    lines = [f"### Esito del criterio proxy (esplorativo, K={k_label})", ""]
    lines.append(_SCOPE_NOTE)
    lines.append("")
    if winner.winner is None and winner.no_winner_reason:
        # Operational tie-break excluded (#236): the tie on quality is not the
        # four-axis tie, and saying it with the same sentence would confuse two
        # different facts. The reason comes from the verdict, it is not rewritten here.
        lines.append(
            f"**Nessun braccio prevale sul proxy.** {winner.no_winner_reason} "
            f"(`{winner.label_a}` vs `{winner.label_b}`)."
        )
    elif winner.winner is None:
        lines.append(
            f"**Nessun modello prevale sul proxy.** `{winner.label_a}` e "
            f"`{winner.label_b}` sono pari su tutti e 4 gli assi alla precisione "
            "di stampa."
        )
    else:
        dec = winner.deciding_axis
        assert dec is not None  # winner!=None -> deciding_axis set
        last = winner.chain[-1]
        lines.append(
            f"**Su questa run `{winner.winner}` ha scorato meglio sul criterio "
            f"proxy (esplorativo)** — asse decisivo `{dec}` "
            f"({_fmt(dec, last.value_a)} vs {_fmt(dec, last.value_b)})."
        )
    if folded_a is not None and folded_b is not None:
        a_lo, a_hi = _n_reps_range(folded_a)
        b_lo, b_hi = _n_reps_range(folded_b)
        lines.append("")
        lines.append(
            f"> Base: K={k_label} ripetizioni; n_reps validi per zona — "
            f"`{winner.label_a}`: {a_lo}-{a_hi}, `{winner.label_b}`: {b_lo}-{b_hi}. "
            "Verdetto esplorativo: std e range NON entrano nella decisione."
        )
    lines.append("")
    lines.append("Catena dei confronti (parità = a precisione di stampa):")
    lines.append(f"| asse | {winner.label_a} | {winner.label_b} | esito |")
    lines.append("| --- | --- | --- | --- |")
    for c in winner.chain:
        if c.outcome == "tie":
            outcome = "pari"
        else:
            outcome = winner.label_a if c.outcome == "a" else winner.label_b
        lines.append(
            f"| {c.axis} | {_fmt(c.axis, c.value_a)} | "
            f"{_fmt(c.axis, c.value_b)} | {outcome} |"
        )
    return "\n".join(lines) + "\n"


def verdict_na_markdown(
    vacuous_arms: list[str], vacuous_zones: list[VacuousZone], k_label: str
) -> str:
    """ "Withheld verdict" section: the text is missing, the axes do not hold.

    Replaces :func:`winner_markdown` when vacuity touches a whole arm
    or even just one zone (#231): same heading (stable report
    structure), but in place of the verdict the reason why on these axes none
    can be issued -- in neither direction. A single vacuous zone
    is enough: it enters the mean that the lexicographic criterion compares.
    """
    return (
        f"### Esito del criterio proxy (esplorativo, K={k_label})\n"
        "\n"
        f"> **NON APPLICABILE.** {vacuity_subject(vacuous_arms, vacuous_zones)}: "
        f"{VACUOUS_REASON}. Quei valori entrano nella media che il criterio "
        "confronta, quindi dichiarare un vincitore premierebbe il silenzio: il "
        "verdetto è **trattenuto**. Il criterio lessicografico (#157) è definito "
        "per il confronto tra modelli che generano ENTRAMBI: questo report non "
        "calcola né dichiara un esito, nemmeno sui soli assi operativi — "
        f"{OPERATIONAL_AXES_NOTE}; la qualità dell'interpretazione è materia di "
        "annotazione umana (#152).\n"
    )


def istat_no_winner_markdown(k_label: str) -> str:
    """Outcome section of the ontology vs ontology + ISTAT pair (#345, D12).

    The verdict is withheld by design, not by vacuity: both arms
    may have written the narrative, so the vacuity text (with its
    list of mute zones) would be false. Same heading as the other sections.
    """
    return (
        f"### Esito del criterio proxy (esplorativo, K={k_label})\n"
        "\n"
        f"> **NESSUN VINCITORE AUTOMATICO.** {ISTAT_NO_WINNER_REASON}.\n"
    )


def build_repeated_report(
    results_dir: Path,
    experiment_a: str,
    experiment_b: str,
    *,
    label_a: str | None = None,
    label_b: str | None = None,
    stem: str | None = None,
    force: bool = False,
) -> tuple[Path, Path]:
    """Load the two experiments, fold the repetitions, compare and write the report.

    Writes ``<stem>.md`` (tables #33 + variance + winner) and ``<stem>.json``
    (comparison #33 + ``winner`` and ``variance`` objects). Returns the two paths.
    If a target file exists and ``force`` is ``False`` raises
    :class:`FileExistsError` (anti-overwrite guard, #165).

    If the narrative is missing -- an arm mute in every run, or even a single zone on
    which an arm is silent (#231) -- the verdict
    is WITHHELD: ``winner`` is ``None`` in the JSON, ``quality_verdict.applicable``
    is ``False`` and the Markdown justifies the abstention in place of the winner. The
    tables (including the operational ones) stay unchanged.

    If after folding the repetitions no usable zone remains
    (every arm in ERROR/FALLBACK on every zone, #239) it still writes a
    report -- Markdown/JSON of the excluded zones, no verdict -- and re-raises
    :class:`~crime_risk_analyzer.eval.compare.NoUsableOutputError`. The
    anti-overwrite guard (``FileExistsError``) propagates unchanged; another
    write failure (``OSError``: disk full, permissions) is only logged,
    and ``NoUsableOutputError`` is still re-raised -- never the ``OSError`` -- so
    the CLI caller exits with a clean exit code instead of a traceback (#239).
    """
    la = label_a or experiment_a
    lb = label_b or experiment_b
    runs_a = load_runs(results_dir, experiment=experiment_a)
    runs_b = load_runs(results_dir, experiment=experiment_b)
    folded_a = fold_arm(runs_a)
    folded_b = fold_arm(runs_b)
    resolved = stem or f"{experiment_a}_vs_{experiment_b}_repeated"
    try:
        # #359: the risk anchoring is computed on the repetitions, not on the
        # mean-record (which carries neither the narrative of each nor the risk_models).
        comparison = compare_records(
            folded_a.mean_records,
            folded_b.mean_records,
            label_a=la,
            label_b=lb,
            anchoring_records=(runs_a, runs_b),
        )
    except NoUsableOutputError as exc:
        try:
            write_no_usable_output_report(results_dir, exc, resolved, force=force)
        except FileExistsError:
            raise
        except OSError:
            logger.exception(
                "impossibile scrivere il report di nessun-output-utilizzabile "
                "per '%s' in %s",
                resolved,
                results_dir,
            )
        raise exc
    # No verdict if the text is missing, at arm level OR single zone
    # (#231): it would reward silence. Vacuity comes from the mean-records, which
    # keep the AVAILABILITY of narrative (repeat._representative_narrative),
    # not an average of texts (which does not exist). `quality_verdict` has already been
    # computed once inside compare_records (#238): it is not recomputed here.
    withheld = not comparison.quality_verdict.applicable
    # On this pair the ablated arm has a structurally shorter prompt,
    # so lower latency and cost are not a merit (#236): excluding them
    # from the tie-break, if quality ties the verdict stays declaredly
    # not decidable instead of rewarding the shorter prompt. The predicate is the
    # same as compare.py, not a second recognition of the pair.
    winner = (
        None
        if withheld
        else decide_winner(
            comparison.mean_a,
            comparison.mean_b,
            label_a=la,
            label_b=lb,
            operational_tiebreak=not is_ontology_isolating_pair(
                folded_a.mean_records, folded_b.mean_records
            ),
        )
    )
    k_lo, k_hi = _k_range(folded_a, folded_b)
    k = _k_of(folded_a, folded_b)  # max, for the JSON payload (stable contract)
    warning = (
        f"> ⚠️ K disomogeneo tra zone/bracci (K={k_lo}..{k_hi}): il verdetto "
        "fa la media di zone con basi campionarie diverse.\n\n"
        if k_lo != k_hi
        else ""
    )
    k_label = f"{k_lo}" if k_hi == k_lo else f"{k_lo}..{k_hi}"
    if winner is not None:
        verdict_section = winner_markdown(
            winner, k_lo, folded_a=folded_a, folded_b=folded_b, k_hi=k_hi
        )
    elif has_vacuous_quality_axes(comparison.vacuous_arms, comparison.vacuous_zones):
        verdict_section = verdict_na_markdown(
            comparison.vacuous_arms, comparison.vacuous_zones, k_label
        )
    else:
        # Withheld without vacuity: the only other reason is the ISTAT pair
        # (compare._quality_verdict, D12), and the text must say that.
        verdict_section = istat_no_winner_markdown(k_label)
    # #359: the pointer to the risk-anchoring section sits next to the
    # verdict, not above the table; the verdict does not use those measures.
    pointer = risk_anchoring_pointer(comparison)
    if pointer:
        verdict_section = verdict_section.rstrip("\n") + "\n\n" + pointer + "\n"
    md = (
        "\n".join(
            [
                to_markdown(comparison, anchoring_pointer=False).rstrip("\n"),
                "",
                variance_markdown(
                    comparison, folded_a, folded_b, k_lo, k_hi=k_hi
                ).rstrip("\n"),
                "",
                warning + verdict_section.rstrip("\n"),
            ]
        )
        + "\n"
    )
    comparison_json = json.loads(to_json(comparison))
    # `quality_verdict` lives ONLY at the top level of the payload (sibling key
    # below): it is the very same position in which a reader of `compare`
    # finds it (which has no "comparison" wrapper), not two
    # byte-identical copies at two different depths in the same file (#238 --
    # review finding: before this pop, model_dump/to_json already included
    # the field in here, because it is a real field of Comparison).
    comparison_json.pop("quality_verdict", None)
    payload = {
        "comparison": comparison_json,
        "winner": winner.model_dump() if winner is not None else None,
        # Same field of Comparison written by write_comparison (#238): no
        # hand-rebuilt dictionary that could diverge.
        "quality_verdict": comparison.quality_verdict.model_dump(),
        "variance": {
            "k": k,
            "label_a": la,
            "label_b": lb,
            "arm_a": [v.model_dump() for v in folded_a.variances],
            "arm_b": [v.model_dump() for v in folded_b.variances],
        },
    }
    md_path = results_dir / f"{resolved}.md"
    json_path = results_dir / f"{resolved}.json"
    guard_no_overwrite([md_path, json_path], force)
    md_path.write_text(md, encoding="utf-8")
    # ensure_ascii=False: consistent with to_json/model_dump_json (used for
    # "comparison" below), which never escapes non-ASCII characters --
    # without it, the very same text (e.g. "quality_verdict.reason", #238)
    # would end up with a different encoding depending on which of the two commands
    # (compare vs compare-repeated) wrote the file.
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return md_path, json_path
