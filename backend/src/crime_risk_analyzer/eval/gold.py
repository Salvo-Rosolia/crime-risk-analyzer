"""Annotazione gold umana per-rischio (#152).

Sostituisce l'accordo proxy-vs-gold PER-RUN (Pearson su un giudizio umano
d'insieme, deprecato: vedi
docs/superpowers/specs/2026-09-10-gold-per-risk-annotation-design.md)
con l'annotazione PER-SINGOLO-RISCHIO descritta da spec-valutazione.md:
su un campione di rischi *mantenuti* nell'output finale, l'autore verifica
manualmente se la fonte citata regge, ricavando due proporzioni — precisione
del filtro e allucinazioni residue (N≈30-40) — invece di una correlazione.

Il gold NON e' prodotto qui: l'autore compila a mano le colonne
``fonte_verificata``/``note`` del foglio scritto da :func:`write_gold_worksheet`.
Questo modulo isola i rischi da annotare (:func:`collect_kept_risks`), scrive
il foglio (:func:`write_gold_worksheet`) e, a compilazione avvenuta, calcola
il report finale (:func:`build_precision_report`/:func:`write_precision_report`).
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
    """Un rischio mantenuto (citato in narrativa), da verificare manualmente.

    ``fonte_verificata``/``note`` sono compilate ESTERNAMENTE dall'autore:
    restano ``None``/vuote finche' il foglio scritto da
    :func:`write_gold_worksheet` non viene riletto dopo la compilazione.
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
    """Appiattisce in righe annotabili i rischi EFFETTIVAMENTE citati in narrativa.

    ``RunRecord.risk_models`` e' il set grounded COMPLETO, costruito PRIMA
    della generazione LLM (identico fra analyze/baseline/no_ontology_prompt):
    non riflette alcun filtro. "Mantenuto" per la spec significa "citato nel
    blocco [ONTOLOGIA]", non "presente nel set grounded". Filtra quindi su
    ``status == OK`` E hazard presente nel testo di
    :func:`~crime_risk_analyzer.eval.metrics.hazards_cited_in` — controllando
    l'identificatore hazard OPPURE ``hazard_label_it`` OPPURE
    ``hazard_label_en`` (stesso confronto multi-forma di
    ``metrics._anchors``, chiude lo stesso caveat EN/IT di #77): un rischio
    citato in narrativa con l'etichetta italiana non va perso solo perche' il
    testo non contiene l'identificatore inglese bare.
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


#: Nome del foglio di annotazione sotto ``results/gold/``. Costante condivisa:
#: il default di ``--worksheet`` in ``eval/__main__.py`` deve puntare allo
#: STESSO file che ``write_gold_worksheet`` scrive — ripetere la stringa nei
#: due punti lascerebbe ``gold-report`` a leggere un path che non esiste al
#: primo rinomino.
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
    verificata = (
        "" if row.fonte_verificata is None else str(row.fonte_verificata).lower()
    )
    return [
        row.run_id,
        row.citta,
        row.zona,
        row.poi,
        row.hazard,
        row.tag or "",
        row.confidence,
        row.source or "",
        verificata,
        row.note,
    ]


def write_gold_worksheet(
    results_dir: Path, records: list[RunRecord], *, force: bool = False
) -> Path:
    """Scrive ``results/gold/rischi_da_annotare.csv`` (colonne di giudizio vuote).

    Lavora su ``records`` gia' in memoria (il chiamante CLI li carica a monte
    con ``aggregate.load_runs``), come :func:`collect_kept_risks`, per restare
    testabile senza I/O.

    Rifiuta di sovrascrivere un foglio esistente e non vuoto senza ``force``
    (stessa guardia di ``capture``/``compare``): qui il contenuto perso e' il
    lavoro di annotazione MANUALE dell'autore, che nessun re-run puo'
    ricostruire. Un file di dimensione zero (scrittura interrotta) non contiene
    giudizi da proteggere e viene rimpiazzato senza chiedere.
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
    # newline="": csv.writer emette gia' \r\n; senza questo il text-mode di
    # write_text ritradurrebbe \n->\r\n su Windows (righe spurie, #103/#241).
    path.write_text(buf.getvalue(), encoding="utf-8", newline="")
    return path


#: Token accettati nella colonna ``fonte_verificata``, compilata A MANO: chi
#: annota scrive in italiano ("vero", "sì", "x") o in inglese, non solo il
#: ``true``/``false`` che questo modulo serializza. Confronto su valore
#: strippato e minuscolo.
_TRUE_TOKENS = frozenset({"true", "vero", "v", "1", "si", "sì", "s", "x", "yes", "y"})
_FALSE_TOKENS = frozenset({"false", "falso", "f", "0", "no", "n"})


def _parse_fonte_verificata(raw: str, *, run_id: str) -> bool | None:
    """Interpreta una cella ``fonte_verificata`` compilata a mano.

    Fail-loud sui valori fuori vocabolario invece di collassarli a ``False``:
    un "vero" letto come falso gonfierebbe in silenzio
    ``allucinazioni_residue`` — il numero per cui l'intero meccanismo esiste.
    Cella vuota = "nessuno ha ancora guardato" (``None``), non "la fonte non
    regge".
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
    """Rilegge un foglio (eventualmente compilato) da disco."""
    rows: list[KeptRiskRow] = []
    with path.open(encoding="utf-8", newline="") as fh:
        for record in csv.DictReader(fh):
            fonte_verificata = _parse_fonte_verificata(
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
    """Precisione del filtro + allucinazioni residue su un campione annotato."""

    n_totale: int = Field(ge=0, description="Righe totali nel foglio.")
    n_annotati: int = Field(ge=0, description="Righe con fonte_verificata compilata.")
    precisione_filtro: float | None = Field(
        default=None, description="% fonte_verificata=True sugli annotati."
    )
    allucinazioni_residue: float | None = Field(
        default=None, description="% fonte_verificata=False sugli annotati."
    )


def build_precision_report(rows: list[KeptRiskRow]) -> PrecisionReport:
    """Percentuali sui SOLI rischi annotati; ``None`` con zero annotazioni.

    ``None`` (non ``0.0``) quando ``n_annotati == 0``: una percentuale a zero
    affermerebbe "nessuna fonte regge" quando in realta' nessuno ha ancora
    guardato — stesso principio gia' applicato a ``Metrics.quality_vacuous``
    (#240).
    """
    annotati = [r for r in rows if r.fonte_verificata is not None]
    n_annotati = len(annotati)
    if n_annotati == 0:
        return PrecisionReport(n_totale=len(rows), n_annotati=0)
    n_verificati = sum(1 for r in annotati if r.fonte_verificata)
    return PrecisionReport(
        n_totale=len(rows),
        n_annotati=n_annotati,
        precisione_filtro=n_verificati / n_annotati,
        allucinazioni_residue=(n_annotati - n_verificati) / n_annotati,
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
    """Legge il foglio (compilato o no) e scrive
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
