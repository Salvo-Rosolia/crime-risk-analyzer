"""Confronto a due bracci di esperimenti di valutazione (#32).

Primitiva GENERICA: dati i ``RunRecord`` di DUE esperimenti (braccio A e braccio
B), li unisce per ``(citta, zona)`` e calcola il DELTA (A - B) delle quattro
metriche — ``grounding``, ``hallucination``, ``latency_ms``, ``cost_usd`` —
producendo una tabella per-zona più una riga aggregata (media), serializzabile
in CSV e Markdown.

Le run in ERROR (metriche azzerate dall'harness) NON entrano in delta/medie: le
zone corrispondenti sono escluse dall'aggregato e riportate esplicitamente in
una sezione dedicata (nulla è scartato o mediato in silenzio). ``OK`` e
``FALLBACK`` (metriche reali) restano incluse.

Non è cablata su analyze/baseline: i bracci sono etichettati liberamente
(``label_a``/``label_b``). L'ablation (#32) confronta ``analyze`` vs
``baseline``; #33 riuserà la stessa primitiva per ``claude`` vs ``groq``.

Riusa lo stile e l'helper ``load_runs`` di :mod:`aggregate` senza modificarlo.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from crime_risk_analyzer.eval.aggregate import load_runs
from crime_risk_analyzer.eval.schema import Metrics, RunRecord, RunStatus

#: Etichetta della riga aggregata nelle tabelle.
_MEAN_LABEL = "MEDIA"


class MetricValues(BaseModel):
    """Quattro metriche come float, per medie e delta.

    A differenza di :class:`~crime_risk_analyzer.eval.schema.Metrics` non impone
    ``[0,1]``: un delta (A - B) può essere negativo, e ``latency_ms`` medio è un
    float.
    """

    grounding: float
    hallucination: float
    latency_ms: float
    cost_usd: float


class ZoneComparison(BaseModel):
    """Confronto di una singola zona ``(citta, zona)`` tra i due bracci."""

    citta: str
    zona: str
    a: Metrics
    b: Metrics
    delta: MetricValues


class FailedZone(BaseModel):
    """Zona esclusa dall'aggregato perché almeno un braccio è in ``ERROR``.

    Riporta lo status di ENTRAMBI i bracci così l'esclusione è tracciabile
    (quale braccio è fallito), non silenziosa.
    """

    citta: str
    zona: str
    status_a: str
    status_b: str


class Comparison(BaseModel):
    """Esito del confronto: zone comparate + aggregato + zone escluse (ERROR)."""

    label_a: str
    label_b: str
    zones: list[ZoneComparison]
    mean_a: MetricValues
    mean_b: MetricValues
    mean_delta: MetricValues
    #: Zone escluse dall'aggregato (un braccio in ERROR); vuota se nessuna.
    #: Sempre valorizzata da :func:`compare_records`.
    failed: list[FailedZone]


@dataclass(frozen=True)
class _MetricSpec:
    """Fonte unica per colonne e formattazione di una metrica (evita drift m2)."""

    name: str
    value_fmt: str
    delta_fmt: str
    get: Callable[[MetricValues], float]


#: Ordine e formato delle 4 metriche. Guida SIA le intestazioni SIA le righe:
#: aggiungere una metrica qui aggiorna header e celle in modo coerente.
_METRIC_SPECS: tuple[_MetricSpec, ...] = (
    _MetricSpec("grounding", "{:.3f}", "{:+.3f}", lambda m: m.grounding),
    _MetricSpec("hallucination", "{:.3f}", "{:+.3f}", lambda m: m.hallucination),
    _MetricSpec("latency_ms", "{:.0f}", "{:+.0f}", lambda m: m.latency_ms),
    _MetricSpec("cost_usd", "{:.6f}", "{:+.6f}", lambda m: m.cost_usd),
)


def _to_values(m: Metrics) -> MetricValues:
    """Proietta una :class:`Metrics` (latency int) in :class:`MetricValues`."""
    return MetricValues(
        grounding=m.grounding,
        hallucination=m.hallucination,
        latency_ms=float(m.latency_ms),
        cost_usd=m.cost_usd,
    )


def _delta(a: Metrics, b: Metrics) -> MetricValues:
    """Delta per-metrica A - B (può essere negativo)."""
    return MetricValues(
        grounding=a.grounding - b.grounding,
        hallucination=a.hallucination - b.hallucination,
        latency_ms=float(a.latency_ms - b.latency_ms),
        cost_usd=a.cost_usd - b.cost_usd,
    )


def _mean(values: list[MetricValues]) -> MetricValues:
    """Media per-metrica su una lista non vuota di :class:`MetricValues`."""
    n = len(values)
    return MetricValues(
        grounding=float(sum(v.grounding for v in values) / n),
        hallucination=float(sum(v.hallucination for v in values) / n),
        latency_ms=float(sum(v.latency_ms for v in values) / n),
        cost_usd=float(sum(v.cost_usd for v in values) / n),
    )


def _index_by_zone(records: list[RunRecord]) -> dict[tuple[str, str], RunRecord]:
    """Indicizza i record per ``(citta, zona)``; errore su chiave duplicata."""
    index: dict[tuple[str, str], RunRecord] = {}
    for rec in records:
        key = (rec.citta, rec.zona)
        if key in index:
            raise ValueError(
                f"record duplicato per (citta, zona)={key} nel braccio "
                f"'{rec.experiment}': un braccio deve avere una run per zona"
            )
        index[key] = rec
    return index


def compare_records(
    arm_a: list[RunRecord],
    arm_b: list[RunRecord],
    *,
    label_a: str,
    label_b: str,
) -> Comparison:
    """Unisce due bracci per ``(citta, zona)`` e calcola i delta A - B.

    Le zone in cui un braccio è in ``ERROR`` (metriche azzerate) sono escluse da
    zone comparate e medie, e raccolte in ``Comparison.failed``. ``OK`` e
    ``FALLBACK`` restano inclusi.

    Solleva :class:`ValueError` se: un braccio ha record duplicati per una zona;
    i due bracci coprono zone diverse (iso-input violato); una zona appaiata ha
    ``snapshot_id`` divergente tra i bracci (iso-input a livello di record); non
    resta alcuna zona valida da confrontare.
    """
    index_a = _index_by_zone(arm_a)
    index_b = _index_by_zone(arm_b)
    keys_a = set(index_a)
    keys_b = set(index_b)
    if keys_a != keys_b:
        only_a = sorted(keys_a - keys_b)
        only_b = sorted(keys_b - keys_a)
        raise ValueError(
            "le zone dei due bracci non coincidono (confronto iso-input "
            f"violato): solo in A={only_a}, solo in B={only_b}"
        )
    if not keys_a:
        raise ValueError("nessuna zona da confrontare: entrambi i bracci sono vuoti")
    zones: list[ZoneComparison] = []
    failed: list[FailedZone] = []
    for key in sorted(keys_a):
        rec_a = index_a[key]
        rec_b = index_b[key]
        # Iso-input a livello di record: la stessa (citta, zona) deve citare lo
        # stesso snapshot_id in entrambi i bracci. Difesa-in-profondità (record
        # manomessi a mano, o un futuro snapshot_id derivato dal contenuto POI).
        # NON intercetta un --force: quello sovrascrive il file snapshot ma lascia
        # l'id invariato (derivato solo da (citta, zona)), quindi una divergenza
        # di CONTENUTO tra i bracci non emergerebbe qui.
        sid_a = rec_a.provenance.snapshot_id
        sid_b = rec_b.provenance.snapshot_id
        if sid_a != sid_b:
            raise ValueError(
                f"snapshot_id divergente per (citta, zona)={key}: "
                f"A={sid_a!r} B={sid_b!r} (confronto iso-input violato)"
            )
        # Un record in ERROR ha metriche azzerate (harness): escluderlo, non
        # mediarlo. Riportato esplicitamente tra le zone fallite.
        if RunStatus.ERROR in (rec_a.status, rec_b.status):
            failed.append(
                FailedZone(
                    citta=rec_a.citta,
                    zona=rec_a.zona,
                    status_a=rec_a.status.value,
                    status_b=rec_b.status.value,
                )
            )
            continue
        zones.append(
            ZoneComparison(
                citta=rec_a.citta,
                zona=rec_a.zona,
                a=rec_a.metrics,
                b=rec_b.metrics,
                delta=_delta(rec_a.metrics, rec_b.metrics),
            )
        )
    if not zones:
        raise ValueError(
            "nessuna zona valida da confrontare (tutte in ERROR): "
            f"{[(f.citta, f.zona) for f in failed]}"
        )
    return Comparison(
        label_a=label_a,
        label_b=label_b,
        zones=zones,
        mean_a=_mean([_to_values(z.a) for z in zones]),
        mean_b=_mean([_to_values(z.b) for z in zones]),
        mean_delta=_mean([z.delta for z in zones]),
        failed=failed,
    )


def _columns(label_a: str, label_b: str) -> list[str]:
    """Intestazioni: per ogni metrica, valore A, valore B, delta."""
    cols = ["citta", "zona"]
    for spec in _METRIC_SPECS:
        cols.extend(
            [f"{spec.name}_{label_a}", f"{spec.name}_{label_b}", f"{spec.name}_delta"]
        )
    return cols


def _failed_columns(label_a: str, label_b: str) -> list[str]:
    """Intestazioni della sezione zone escluse (status per braccio)."""
    return ["citta", "zona", f"status_{label_a}", f"status_{label_b}"]


def _failed_row(failed: FailedZone) -> list[str]:
    """Riga di una zona esclusa; allineata a :func:`_failed_columns`."""
    return [failed.citta, failed.zona, failed.status_a, failed.status_b]


def _fmt_row(
    citta: str, zona: str, a: MetricValues, b: MetricValues, d: MetricValues
) -> list[str]:
    """Una riga formattata; i delta portano il segno esplicito (+/-).

    Derivata da :data:`_METRIC_SPECS` come :func:`_columns`: header e righe non
    possono disallinearsi (una sola fonte di verità).
    """
    cells = [citta, zona]
    for spec in _METRIC_SPECS:
        cells.append(spec.value_fmt.format(spec.get(a)))
        cells.append(spec.value_fmt.format(spec.get(b)))
        cells.append(spec.delta_fmt.format(spec.get(d)))
    return cells


def _rows(comparison: Comparison) -> list[list[str]]:
    """Righe per-zona (solo zone valide) seguite dalla riga aggregata (media)."""
    rows = [
        _fmt_row(z.citta, z.zona, _to_values(z.a), _to_values(z.b), z.delta)
        for z in comparison.zones
    ]
    rows.append(
        _fmt_row(
            _MEAN_LABEL,
            "",
            comparison.mean_a,
            comparison.mean_b,
            comparison.mean_delta,
        )
    )
    return rows


def to_csv(comparison: Comparison) -> str:
    """Serializza il confronto in CSV: tabella RETTANGOLARE (zone valide + MEDIA).

    Le zone escluse (un braccio in ERROR) NON entrano nel CSV, che resta una
    tabella uniforme caricabile da pandas/``csv.reader`` senza righe ragged; sono
    riportate nel report Markdown (:func:`to_markdown`) e restano accessibili in
    ``Comparison.failed``: nessun fallimento sparisce in silenzio.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_columns(comparison.label_a, comparison.label_b))
    for row in _rows(comparison):
        writer.writerow(row)
    return buf.getvalue()


def to_markdown(comparison: Comparison) -> str:
    """Serializza il confronto in tabella markdown (+ sezione zone escluse)."""
    cols = _columns(comparison.label_a, comparison.label_b)
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for row in _rows(comparison):
        lines.append("| " + " | ".join(row) + " |")
    if comparison.failed:
        fcols = _failed_columns(comparison.label_a, comparison.label_b)
        lines.append("")
        lines.append("### Zone escluse dal confronto (run in errore)")
        lines.append("| " + " | ".join(fcols) + " |")
        lines.append("| " + " | ".join("---" for _ in fcols) + " |")
        for fz in comparison.failed:
            lines.append("| " + " | ".join(_failed_row(fz)) + " |")
    return "\n".join(lines) + "\n"


def write_comparison(
    results_dir: Path, comparison: Comparison, stem: str
) -> tuple[Path, Path]:
    """Scrive ``results/<stem>.csv`` e ``.md`` dal confronto."""
    csv_path = results_dir / f"{stem}.csv"
    md_path = results_dir / f"{stem}.md"
    # newline="": to_csv() emette gia' \r\n via csv.writer; senza questo, il
    # text-mode di write_text ritradurrebbe \n->\r\n su Windows (righe spurie).
    # Stesso accorgimento del fix #103 in aggregate.write_tables (qui replicato
    # sul file nuovo, NON ri-applicato ad aggregate.py).
    csv_path.write_text(to_csv(comparison), encoding="utf-8", newline="")
    md_path.write_text(to_markdown(comparison), encoding="utf-8")
    return csv_path, md_path


def compare_experiments(
    results_dir: Path,
    experiment_a: str,
    experiment_b: str,
    *,
    label_a: str | None = None,
    label_b: str | None = None,
    stem: str | None = None,
) -> tuple[Path, Path]:
    """Carica i record dei due esperimenti da disco, confronta e scrive le tabelle.

    ``label_a``/``label_b`` default al nome dell'esperimento; ``stem`` default a
    ``<experiment_a>_vs_<experiment_b>``.
    """
    arm_a = load_runs(results_dir, experiment=experiment_a)
    arm_b = load_runs(results_dir, experiment=experiment_b)
    comparison = compare_records(
        arm_a,
        arm_b,
        label_a=label_a or experiment_a,
        label_b=label_b or experiment_b,
    )
    resolved_stem = stem or f"{experiment_a}_vs_{experiment_b}"
    return write_comparison(results_dir, comparison, resolved_stem)
