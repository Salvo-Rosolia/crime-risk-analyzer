"""Validazione delle metriche proxy contro l'annotazione gold umana (#109).

Le metriche testuali di ``eval/metrics.py`` (grounding, hallucination) sono
PROXY deterministici e vanno validati contro il giudizio di un annotatore umano.
Questo modulo costruisce la tabella-accordo proxy-vs-gold da un insieme di
:class:`~crime_risk_analyzer.eval.schema.RunRecord`.

Il gold NON e' prodotto qui: ``RunRecord.annotazione_manuale`` e' popolato
ESTERNAMENTE (dal tesista) con una
:class:`~crime_risk_analyzer.eval.schema.GoldAnnotation`. Il builder consuma
QUALUNQUE gold sia presente e ignora i record non annotati, cosi' la macchina
gira gia' oggi (accordo vuoto ben formato) e si popola man mano che arrivano le
annotazioni umane.

Accordo misurato per ciascuna metrica:
- correlazione di Pearson (il proxy segue il giudizio umano?),
- scarto assoluto medio (bias sistematico anche a correlazione perfetta),
- matrice di confusione su "allucinazione presente" (> soglia): i falsi negativi
  sono i casi in cui il proxy TACE ma l'umano segnala, cioe' il sotto-conteggio
  dell'allucinazione che #109 vuole rendere misurabile.

Esposto come FUNZIONE BUILDER (:func:`build_agreement_report`) + serializzatori
(:func:`to_markdown`/:func:`to_csv`) + scrittura su disco
(:func:`write_agreement_report`), sullo stesso pattern di
``aggregate.write_tables`` e ``city_agnostic_report.build_report`` (nessun
sottocomando CLI).
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from pydantic import BaseModel, Field

from crime_risk_analyzer.eval.aggregate import load_runs
from crime_risk_analyzer.eval.schema import RunRecord

#: Soglia di default per binarizzare "allucinazione presente" nella matrice di
#: confusione: un valore > 0 conta come presente (qualunque frazione non nulla).
_DEFAULT_THRESHOLD = 0.0


class ConfusionMatrix(BaseModel):
    """Matrice 2x2 proxy-vs-gold su "allucinazione presente" (valore > soglia).

    Classe positiva = allucinazione presente. ``false_negative`` (proxy assente,
    gold presente) e' il sotto-conteggio dell'allucinazione: il fallimento che
    #109 vuole rendere visibile.
    """

    true_positive: int = Field(ge=0, description="Proxy presente, gold presente.")
    false_positive: int = Field(ge=0, description="Proxy presente, gold assente.")
    false_negative: int = Field(
        ge=0, description="Proxy assente, gold presente (sotto-conteggio)."
    )
    true_negative: int = Field(ge=0, description="Proxy assente, gold assente.")


class MetricAgreement(BaseModel):
    """Accordo proxy-vs-gold per una singola metrica sui record annotati."""

    metric: str = Field(description="Nome della metrica (grounding/hallucination).")
    pearson: float | None = Field(
        description="Correlazione di Pearson; None se <2 punti o varianza nulla."
    )
    mean_proxy: float = Field(description="Media dei valori proxy sui record annotati.")
    mean_gold: float = Field(description="Media dei valori gold sui record annotati.")
    mean_abs_error: float = Field(
        ge=0.0, description="Scarto assoluto medio |proxy - gold|."
    )


class AgreementRow(BaseModel):
    """Riga di dettaglio per una run annotata (proxy accanto al gold)."""

    run_id: str
    proxy_grounding: float
    gold_grounding: float
    proxy_hallucination: float
    gold_hallucination: float


class AgreementReport(BaseModel):
    """Tabella-accordo proxy-vs-gold (output di :func:`build_agreement_report`)."""

    n_runs_total: int = Field(ge=0, description="Record totali esaminati.")
    n_annotated: int = Field(ge=0, description="Record con annotazione gold.")
    threshold: float = Field(description="Soglia usata per la matrice di confusione.")
    grounding: MetricAgreement
    hallucination: MetricAgreement
    hallucination_confusion: ConfusionMatrix
    rows: list[AgreementRow] = Field(description="Dettaglio per run annotata.")


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Correlazione di Pearson dependency-free; ``None`` se indefinita.

    Indefinita quando i punti sono <2 o quando una delle due serie ha varianza
    nulla (denominatore 0): ritorna ``None`` invece di dividere per zero (es.
    proxy costante su tutti i record annotati).
    """
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    cov = sum(a * b for a, b in zip(dx, dy, strict=True))
    var_x = sum(a * a for a in dx)
    var_y = sum(b * b for b in dy)
    if var_x == 0.0 or var_y == 0.0:
        return None
    return cov / (var_x**0.5 * var_y**0.5)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _metric_agreement(
    metric: str, proxy: list[float], gold: list[float]
) -> MetricAgreement:
    mae = _mean([abs(p - g) for p, g in zip(proxy, gold, strict=True)])
    return MetricAgreement(
        metric=metric,
        pearson=_pearson(proxy, gold),
        mean_proxy=_mean(proxy),
        mean_gold=_mean(gold),
        mean_abs_error=mae,
    )


def _confusion(
    proxy: list[float], gold: list[float], threshold: float
) -> ConfusionMatrix:
    tp = fp = fn = tn = 0
    for p, g in zip(proxy, gold, strict=True):
        p_pos = p > threshold
        g_pos = g > threshold
        if p_pos and g_pos:
            tp += 1
        elif p_pos and not g_pos:
            fp += 1
        elif not p_pos and g_pos:
            fn += 1
        else:
            tn += 1
    return ConfusionMatrix(
        true_positive=tp, false_positive=fp, false_negative=fn, true_negative=tn
    )


def build_agreement_report(
    records: list[RunRecord], *, threshold: float = _DEFAULT_THRESHOLD
) -> AgreementReport:
    """Confronta le metriche proxy con l'annotazione gold sui record annotati.

    Consuma solo i record il cui ``annotazione_manuale`` e' popolato (una
    :class:`~crime_risk_analyzer.eval.schema.GoldAnnotation`); i non annotati
    contribuiscono a ``n_runs_total`` ma non all'accordo. Con zero record
    annotati ritorna un report vuoto ben formato (Pearson ``None``, matrice a
    zero): la macchina e' utilizzabile prima che arrivino le annotazioni umane.
    """
    rows: list[AgreementRow] = []
    for rec in records:
        gold = rec.annotazione_manuale
        if gold is None:
            continue
        rows.append(
            AgreementRow(
                run_id=rec.run_id,
                proxy_grounding=rec.metrics.grounding,
                gold_grounding=gold.grounding,
                proxy_hallucination=rec.metrics.hallucination,
                gold_hallucination=gold.hallucination,
            )
        )

    proxy_g = [row.proxy_grounding for row in rows]
    gold_g = [row.gold_grounding for row in rows]
    proxy_h = [row.proxy_hallucination for row in rows]
    gold_h = [row.gold_hallucination for row in rows]

    return AgreementReport(
        n_runs_total=len(records),
        n_annotated=len(rows),
        threshold=threshold,
        grounding=_metric_agreement("grounding", proxy_g, gold_g),
        hallucination=_metric_agreement("hallucination", proxy_h, gold_h),
        hallucination_confusion=_confusion(proxy_h, gold_h, threshold),
        rows=rows,
    )


_COLUMNS = [
    "run_id",
    "proxy_grounding",
    "gold_grounding",
    "proxy_hallucination",
    "gold_hallucination",
]


def _row_cells(row: AgreementRow) -> list[str]:
    return [
        row.run_id,
        f"{row.proxy_grounding:.3f}",
        f"{row.gold_grounding:.3f}",
        f"{row.proxy_hallucination:.3f}",
        f"{row.gold_hallucination:.3f}",
    ]


def to_csv(report: AgreementReport) -> str:
    """Serializza le righe per-run in CSV (header + una riga per run annotata)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_COLUMNS)
    for row in report.rows:
        writer.writerow(_row_cells(row))
    return buf.getvalue()


def _fmt_pearson(value: float | None) -> str:
    return "n/d" if value is None else f"{value:.3f}"


def _metric_line(agreement: MetricAgreement) -> str:
    return (
        f"- {agreement.metric}: pearson {_fmt_pearson(agreement.pearson)} · "
        f"MAE {agreement.mean_abs_error:.3f} · "
        f"media proxy {agreement.mean_proxy:.3f} / gold {agreement.mean_gold:.3f}"
    )


def to_markdown(report: AgreementReport) -> str:
    """Tabella-accordo in markdown: righe per-run + riepilogo dell'accordo."""
    lines = [
        "| " + " | ".join(_COLUMNS) + " |",
        "| " + " | ".join("---" for _ in _COLUMNS) + " |",
    ]
    for row in report.rows:
        lines.append("| " + " | ".join(_row_cells(row)) + " |")
    cm = report.hallucination_confusion
    lines.extend(
        [
            "",
            f"record: {report.n_runs_total} · annotati: {report.n_annotated} · "
            f"soglia: {report.threshold:.3f}",
            _metric_line(report.grounding),
            _metric_line(report.hallucination),
            (
                "- hallucination confusion (presente = > soglia): "
                f"TP {cm.true_positive} · FP {cm.false_positive} · "
                f"FN {cm.false_negative} (sotto-conteggio) · TN {cm.true_negative}"
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def write_agreement_report(
    results_dir: Path,
    *,
    experiment: str | None = None,
    threshold: float = _DEFAULT_THRESHOLD,
) -> tuple[Path, Path]:
    """Carica i RunRecord, costruisce l'accordo e scrive ``.csv`` + ``.md``.

    Riusa ``aggregate.load_runs`` (stessa sorgente ``results/runs/``), opz.
    filtrata per ``experiment``. Scrive ``results/gold/agreement.{csv,md}`` e
    ritorna i due path ``(csv, md)``. Nessun sottocomando CLI: e' una funzione
    builder testata direttamente (come ``aggregate.write_tables``).
    """
    records = load_runs(results_dir, experiment=experiment)
    report = build_agreement_report(records, threshold=threshold)
    out_dir = results_dir / "gold"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "agreement.csv"
    md_path = out_dir / "agreement.md"
    # newline="": to_csv() emette gia' \r\n via csv.writer; senza questo il
    # text-mode di write_text ritradurrebbe \n->\r\n su Windows (righe spurie).
    # Stesso fix di aggregate.write_tables / city_agnostic_report (#103).
    csv_path.write_text(to_csv(report), encoding="utf-8", newline="")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    return csv_path, md_path
