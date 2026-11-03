"""Per-risk human gold annotation (#152).

Replaces the PER-RUN proxy-vs-gold agreement (Pearson on an overall human
judgement, deprecated: see
docs/superpowers/specs/2026-09-10-gold-per-risk-annotation-design.md)
with the PER-SINGLE-RISK annotation described by spec-valutazione.md:
on a sample of risks *kept* in the final output, the author checks
manually whether the cited source holds up, obtaining two proportions -- precision
of the filter and residual hallucinations (N~30-40) -- instead of a correlation.

The gold is NOT produced here: the author fills in by hand the columns
``fonte_verificata``/``note`` of the sheet written by :func:`write_gold_worksheet`.
This module isolates the risks to annotate (:func:`collect_kept_risks`), writes
the sheet (:func:`write_gold_worksheet`) and, once it is filled in, computes
the final report (:func:`build_precision_report`/:func:`write_precision_report`).
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from pydantic import BaseModel, Field

from crime_risk_analyzer.eval.metrics import hazards_cited_in
from crime_risk_analyzer.eval.schema import RunRecord, RunStatus
from crime_risk_analyzer.models.vocab import Confidence, Tag


class KeptRiskRow(BaseModel):
    """A kept risk (cited in the narrative), to be checked manually.

    ``fonte_verificata``/``note`` are filled in EXTERNALLY by the author:
    they stay ``None``/empty until the sheet written by
    :func:`write_gold_worksheet` is re-read after being filled in.
    """

    run_id: str
    citta: str
    zona: str
    poi: str
    hazard: str
    tag: Tag | None
    confidence: Confidence
    source: str | None
    fonte_verificata: bool | None = Field(
        default=None, description="Compilato a mano: la fonte regge alla verifica?"
    )
    note: str = Field(default="", description="Note libere dell'annotatore.")


def collect_kept_risks(records: list[RunRecord]) -> list[KeptRiskRow]:
    """Flatten into annotatable rows the risks ACTUALLY cited in the narrative.

    ``RunRecord.risk_models`` is the COMPLETE grounded set, built BEFORE
    the LLM generation (identical across analyze/baseline/no_ontology_prompt):
    it reflects no filter. "Kept" for the spec means "cited in the
    [ONTOLOGIA] block", not "present in the grounded set". So it filters on
    ``status == OK`` AND hazard present in the text of
    :func:`~crime_risk_analyzer.eval.metrics.hazards_cited_in` -- checking
    the hazard identifier OR ``hazard_label_it`` OR
    ``hazard_label_en`` (same multi-form comparison as
    ``metrics._anchors``, closes the same EN/IT caveat as #77): a risk
    cited in the narrative with the Italian label must not be lost just because the
    text does not contain the bare English identifier.
    """
    rows: list[KeptRiskRow] = []
    for record in records:
        if record.status != RunStatus.OK:
            continue
        block = hazards_cited_in(record.narrativa, record.mode)
        for model in record.risk_models:
            for risk in model.risks:
                candidates = [risk.hazard, risk.hazard_label_it, risk.hazard_label_en]
                if not any(c and c.lower() in block for c in candidates):
                    continue
                rows.append(
                    KeptRiskRow(
                        run_id=record.run_id,
                        citta=record.citta,
                        zona=record.zona,
                        poi=model.poi,
                        hazard=risk.hazard,
                        tag=risk.tag,
                        confidence=risk.confidence,
                        source=risk.source,
                    )
                )
    return rows


#: Name of the annotation sheet under ``results/gold/``. Shared constant:
#: the default of ``--worksheet`` in ``eval/__main__.py`` must point to the
#: SAME file that ``write_gold_worksheet`` writes -- repeating the string in the
#: two places would leave ``gold-report`` reading a path that does not exist at the
#: first rename.
WORKSHEET_FILENAME = "rischi_da_annotare.csv"

_WORKSHEET_COLUMNS = [
    "run_id",
    "citta",
    "zona",
    "poi",
    "hazard",
    "tag",
    "confidence",
    "source",
    "fonte_verificata",
    "note",
]


def _worksheet_cells(row: KeptRiskRow) -> list[str]:
    verified = "" if row.fonte_verificata is None else str(row.fonte_verificata).lower()
    return [
        row.run_id,
        row.citta,
        row.zona,
        row.poi,
        row.hazard,
        row.tag or "",
        row.confidence,
        row.source or "",
        verified,
        row.note,
    ]


def write_gold_worksheet(
    results_dir: Path, records: list[RunRecord], *, force: bool = False
) -> Path:
    """Write ``results/gold/rischi_da_annotare.csv`` (empty judgement columns).

    Works on ``records`` already in memory (the CLI caller loads them upstream
    with ``aggregate.load_runs``), like :func:`collect_kept_risks`, to stay
    testable without I/O.

    Refuses to overwrite an existing non-empty sheet without ``force``
    (same guard as ``capture``/``compare``): here the content lost is the
    author's MANUAL annotation work, which no re-run can
    rebuild. A zero-size file (interrupted write) holds no
    judgements to protect and is replaced without asking.
    """
    rows = collect_kept_risks(records)
    out_dir = results_dir / "gold"
    path = out_dir / WORKSHEET_FILENAME
    if not force and path.exists() and path.stat().st_size > 0:
        raise FileExistsError(
            f"il foglio {path} esiste già e potrebbe contenere annotazioni "
            "manuali. Usa --force per sovrascriverlo."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_WORKSHEET_COLUMNS)
    for row in rows:
        writer.writerow(_worksheet_cells(row))
    # newline="": csv.writer already emits \r\n; without this the text mode of
    # write_text would re-translate \n->\r\n on Windows (spurious rows, #103/#241).
    path.write_text(buf.getvalue(), encoding="utf-8", newline="")
    return path


#: Tokens accepted in the ``fonte_verificata`` column, filled in BY HAND: whoever
#: annotates writes in Italian ("vero", "sì", "x") or in English, not only the
#: ``true``/``false`` that this module serializes. Comparison on the
#: stripped, lowercased value.
_TRUE_TOKENS = frozenset({"true", "vero", "v", "1", "si", "sì", "s", "x", "yes", "y"})
_FALSE_TOKENS = frozenset({"false", "falso", "f", "0", "no", "n"})


def _parse_verified_source(raw: str, *, run_id: str) -> bool | None:
    """Interpret a hand-filled ``fonte_verificata`` cell.

    Fail loudly on out-of-vocabulary values instead of collapsing them to ``False``:
    a "vero" read as false would silently inflate
    ``allucinazioni_residue`` -- the number for which the whole mechanism exists.
    Empty cell = "nobody has looked yet" (``None``), not "the source does not
    hold up".
    """
    value = raw.strip().lower()
    if value == "":
        return None
    if value in _TRUE_TOKENS:
        return True
    if value in _FALSE_TOKENS:
        return False
    raise ValueError(
        f"valore fonte_verificata non riconosciuto: {value!r} (run_id={run_id!r}); "
        f"ammessi: {sorted(_TRUE_TOKENS)} / {sorted(_FALSE_TOKENS)} / vuoto"
    )


def load_worksheet(path: Path) -> list[KeptRiskRow]:
    """Re-read a sheet (possibly filled in) from disk."""
    rows: list[KeptRiskRow] = []
    with path.open(encoding="utf-8", newline="") as fh:
        for record in csv.DictReader(fh):
            fonte_verificata = _parse_verified_source(
                record.get("fonte_verificata") or "", run_id=record["run_id"]
            )
            rows.append(
                KeptRiskRow(
                    run_id=record["run_id"],
                    citta=record["citta"],
                    zona=record["zona"],
                    poi=record["poi"],
                    hazard=record["hazard"],
                    tag=record["tag"] or None,  # type: ignore[arg-type]
                    confidence=record["confidence"],  # type: ignore[arg-type]
                    source=record["source"] or None,
                    fonte_verificata=fonte_verificata,
                    note=record.get("note", ""),
                )
            )
    return rows


class PrecisionReport(BaseModel):
    """Filter precision + residual hallucinations on an annotated sample."""

    n_totale: int = Field(ge=0, description="Righe totali nel foglio.")
    n_annotati: int = Field(ge=0, description="Righe con fonte_verificata compilata.")
    precisione_filtro: float | None = Field(
        default=None, description="% fonte_verificata=True sugli annotati."
    )
    allucinazioni_residue: float | None = Field(
        default=None, description="% fonte_verificata=False sugli annotati."
    )


def build_precision_report(rows: list[KeptRiskRow]) -> PrecisionReport:
    """Percentages on the ANNOTATED risks only; ``None`` with zero annotations.

    ``None`` (not ``0.0``) when ``n_annotati == 0``: a percentage at zero
    would claim "no source holds up" when in reality nobody has yet
    looked -- same principle already applied to ``Metrics.quality_vacuous``
    (#240).
    """
    annotated = [r for r in rows if r.fonte_verificata is not None]
    n_annotated = len(annotated)
    if n_annotated == 0:
        return PrecisionReport(n_totale=len(rows), n_annotati=0)
    n_verified = sum(1 for r in annotated if r.fonte_verificata)
    return PrecisionReport(
        n_totale=len(rows),
        n_annotati=n_annotated,
        precisione_filtro=n_verified / n_annotated,
        allucinazioni_residue=(n_annotated - n_verified) / n_annotated,
    )


def _report_markdown(report: PrecisionReport) -> str:
    def pct(value: float | None) -> str:
        return "n/d" if value is None else f"{value:.1%}"

    return (
        f"rischi totali: {report.n_totale} · annotati: {report.n_annotati}\n"
        f"- precisione del filtro: {pct(report.precisione_filtro)}\n"
        f"- allucinazioni residue: {pct(report.allucinazioni_residue)}\n"
    )


def _report_csv(report: PrecisionReport) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["n_totale", "n_annotati", "precisione_filtro", "allucinazioni_residue"]
    )
    writer.writerow(
        [
            report.n_totale,
            report.n_annotati,
            ""
            if report.precisione_filtro is None
            else f"{report.precisione_filtro:.4f}",
            ""
            if report.allucinazioni_residue is None
            else f"{report.allucinazioni_residue:.4f}",
        ]
    )
    return buf.getvalue()


def write_precision_report(
    results_dir: Path, worksheet_path: Path
) -> tuple[Path, Path]:
    """Read the sheet (filled in or not) and write
    ``results/gold/gold_report.{csv,md}``.
    """
    rows = load_worksheet(worksheet_path)
    report = build_precision_report(rows)
    out_dir = results_dir / "gold"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "gold_report.csv"
    md_path = out_dir / "gold_report.md"
    csv_path.write_text(_report_csv(report), encoding="utf-8", newline="")
    md_path.write_text(_report_markdown(report), encoding="utf-8")
    return csv_path, md_path
