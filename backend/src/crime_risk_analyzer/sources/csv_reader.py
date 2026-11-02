"""Reading of the uploaded CSVs (#415): fixed format, errors that say what to do.

Format: mandatory header, comma as separator, UTF-8 with or without
BOM, LF or CRLF line ending (what Excel saves). A file with ``;`` or tab as
separator (Italian Excel uses it by default) gives a clear error instead of a
wrong reading. Empty rows ignored; each row carries the line number of the
file (1 = header) for the messages.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from crime_risk_analyzer.sources.report import (
    MAX_PROBLEMS_PER_CODE,
    FileName,
    ValidationReport,
)

__all__ = ["MAX_COLUMNS", "MAX_ROWS", "MAX_ROW_ERRORS", "CsvRow", "read_csv"]

#: After so many malformed rows the reading stops: the rest adds nothing.
MAX_ROW_ERRORS = MAX_PROBLEMS_PER_CODE
#: Wider header: no valid file has that many columns.
MAX_COLUMNS = 50
#: Data rows per file: beyond it, the reading stops (predictable time).
MAX_ROWS = 200_000


@dataclass(frozen=True)
class CsvRow:
    """A data row: ``cells`` has the known columns, values without edge spaces."""

    line: int
    cells: dict[str, str]


def read_csv(
    content: bytes,
    file: FileName,
    *,
    required: Sequence[str],
    optional: Sequence[str] = (),
    report: ValidationReport,
    max_rows: int | None = None,
) -> list[CsvRow] | None:
    """CSV rows, or ``None`` if the file is not readable (errors in the ``report``).

    It reports all the format problems at once: missing columns (one per
    column), extra columns (warning, ignored), rows with a wrong number of
    cells. With mandatory columns missing the rows are not read; the malformed
    rows are reported and skipped, the others are returned so the
    caller can continue the checks on the rest of the file.
    """
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        report.error(
            "codifica_non_valida",
            file,
            "il file non e' in UTF-8: salvalo come CSV UTF-8",
        )
        return None
    if not text.strip():
        report.error("file_vuoto", file, "il file e' vuoto")
        return None

    if text[0] in ("\r", "\n"):
        report.error(
            "intestazione_mancante",
            file,
            "la prima riga e' vuota: l'intestazione deve essere la prima riga",
            line=1,
        )
        return None

    # Same tokenisation to recognise the separator and to read the data.
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        fields = next(reader)
    except csv.Error as exc:
        report.error(
            "intestazione_non_leggibile",
            file,
            f"l'intestazione non e' leggibile come CSV: {str(exc)[:200]}",
            line=1,
        )
        return None
    if len(fields) == 1 and ";" in fields[0]:
        report.error(
            "separatore_non_valido",
            file,
            "il separatore deve essere la virgola, non il punto e virgola (;): "
            "salva il file come CSV con virgola",
            line=1,
        )
        return None
    if len(fields) == 1 and "\t" in fields[0]:
        report.error(
            "separatore_non_valido",
            file,
            "il separatore deve essere la virgola, non la tabulazione",
            line=1,
        )
        return None
    if len(fields) > MAX_COLUMNS:
        report.error(
            "troppe_colonne",
            file,
            f"l'intestazione ha {len(fields)} colonne, il massimo e' {MAX_COLUMNS}",
            line=1,
        )
        return None
    columns = [c.strip().lower() for c in fields]
    present = set(columns)

    missing = [c for c in required if c not in present]
    for name in missing:
        report.error(
            "colonna_mancante",
            file,
            f"manca la colonna obbligatoria {name!r} "
            f"(intestazione attesa: {', '.join([*required, *optional])})",
            line=1,
        )
    duplicates = sorted(c for c, n in Counter(columns).items() if n > 1)
    for name in duplicates:
        report.error(
            "colonna_duplicata", file, f"la colonna {name!r} compare piu' volte", line=1
        )
    known = {*required, *optional}
    extra = [c for c in present if c not in known]
    extra.sort(key=columns.index)
    if extra:
        report.warning(
            "colonna_in_piu",
            file,
            f"colonne non previste, ignorate: {', '.join(repr(c) for c in extra)}",
            line=1,
        )
    if missing or duplicates:
        return None

    limit = MAX_ROWS if max_rows is None else max_rows
    count = 0
    rows: list[CsvRow] = []
    malformed = False
    row_error_count = 0
    try:
        for values in reader:
            if not any(v.strip() for v in values):
                continue
            line = reader.line_num
            count += 1
            if count > limit:
                report.error(
                    "troppe_righe",
                    file,
                    f"il file ha piu' di {limit} righe di dati: e' il massimo",
                    line=line,
                )
                return None
            if len(values) != len(columns):
                report.error(
                    "riga_malformata",
                    file,
                    f"la riga ha {len(values)} celle invece di {len(columns)}",
                    line=line,
                )
                malformed = True
                row_error_count += 1
                if row_error_count >= MAX_ROW_ERRORS:
                    report.error(
                        "lettura_interrotta",
                        file,
                        f"lettura interrotta dopo {MAX_ROW_ERRORS} righe "
                        "malformate: correggi il file e ricaricalo",
                        line=line,
                    )
                    return None
                continue
            row_cells = {c: v.strip() for c, v in zip(columns, values, strict=True)}
            rows.append(CsvRow(line=line, cells=row_cells))
    except csv.Error as exc:
        report.error("csv_illeggibile", file, f"CSV non leggibile: {exc}")
        return None
    if not rows and not malformed:
        report.error("file_senza_righe", file, "il file ha solo l'intestazione")
        return None
    return rows
