"""Reading of the uploaded CSVs (#415): fixed format, errors that say what to do.

Format: mandatory header, comma or semicolon as separator (Italian Excel uses
the semicolon by default), UTF-8 with or without BOM, LF or CRLF line ending
(what Excel saves). A tab separator or a header mixing both separators gives a
clear error instead of a wrong reading. Empty rows ignored; each row carries
the line number of the file (1 = header) for the messages.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from crime_risk_analyzer.sources.report import (
    MAX_PROBLEMS_PER_CODE,
    FileName,
    ValidationReport,
)

__all__ = [
    "MAX_COLUMNS",
    "MAX_ROWS",
    "MAX_ROW_ERRORS",
    "CsvRow",
    "CsvTable",
    "read_csv",
    "read_csv_table",
]

#: After so many malformed rows the reading stops: the rest adds nothing.
MAX_ROW_ERRORS = MAX_PROBLEMS_PER_CODE
#: Wider header: no valid file has that many columns.
MAX_COLUMNS = 50
#: Data rows per file: beyond it, the reading stops (predictable time).
MAX_ROWS = 200_000
#: The ``sep=;`` first line that Excel can add to say which separator the file has.
_EXCEL_SEP_HINT = re.compile(r"sep=.?", re.IGNORECASE)
_LINE_END = re.compile(r"[\r\n]")
_TAB_ERROR = (
    "il separatore deve essere la virgola o il punto e virgola, non la tabulazione"
)
_AMBIGUOUS_ERROR = (
    "l'intestazione contiene sia la virgola sia il punto e virgola come "
    "separatori: usa un solo separatore (virgola o punto e virgola)"
)


@dataclass(frozen=True)
class CsvRow:
    """A data row: ``cells`` has the known columns, values without edge spaces."""

    line: int
    cells: dict[str, str]


@dataclass(frozen=True)
class CsvTable:
    """The rows of a file and the separator its header uses (``,`` or ``;``)."""

    rows: list[CsvRow]
    delimiter: str


def read_csv(
    content: bytes,
    file: FileName,
    *,
    required: Sequence[str],
    optional: Sequence[str] = (),
    report: ValidationReport,
    max_rows: int | None = None,
) -> list[CsvRow] | None:
    """Rows of :func:`read_csv_table`, or ``None`` if the file is not readable."""
    table = read_csv_table(
        content,
        file,
        required=required,
        optional=optional,
        report=report,
        max_rows=max_rows,
    )
    return None if table is None else table.rows


def read_csv_table(
    content: bytes,
    file: FileName,
    *,
    required: Sequence[str],
    optional: Sequence[str] = (),
    report: ValidationReport,
    max_rows: int | None = None,
) -> CsvTable | None:
    """The rows and the separator, or ``None`` if the file is not readable.

    This is a tokeniser: the cells are the raw text of the file (edge spaces
    stripped); the grammar of each value, decimal comma included, is up to the
    caller, who knows the chosen ``delimiter``.

    The separator (``,`` or ``;``) is the one whose tokenisation of the header
    contains all the ``required`` columns (the comma if both do). If neither
    does and both split the header, the file is ambiguous (``separatore_ambiguo``).
    A separator inside an extra column name therefore does not matter. A data
    row with a different separator than the header has the wrong number of
    cells and is reported as malformed.

    It reports all the format problems at once: missing columns (one per
    column), extra columns (warning, ignored; empty names, like the trailing
    delimiters Excel adds, are ignored silently), rows with a wrong number of
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

    # The separator is chosen on the header line alone, so that the verdict does
    # not depend on what follows (an unterminated quote must not swallow rows).
    header_line = text[: _first_line_end(text)]
    try:
        choice = _choose_separator(header_line, required, {*required, *optional})
    except csv.Error as exc:
        report.error(
            "intestazione_non_leggibile",
            file,
            f"l'intestazione non e' leggibile come CSV: {str(exc)[:200]}",
            line=1,
        )
        return None
    if isinstance(choice, _SeparatorProblem):
        report.error(choice.code, file, choice.message, line=1)
        return None
    delimiter, fields = choice
    if len(fields) > MAX_COLUMNS:
        report.error(
            "troppe_colonne",
            file,
            f"l'intestazione ha {len(fields)} colonne, il massimo e' {MAX_COLUMNS}",
            line=1,
        )
        return None
    # The data start right after the header line: the header is not tokenised twice.
    stream = io.StringIO(text, newline="")
    stream.seek(len(header_line))
    reader = csv.reader(stream, delimiter=delimiter)
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
    # Empty names (the trailing delimiters Excel adds) are ignored columns.
    duplicates = sorted(c for c, n in Counter(columns).items() if n > 1 and c)
    for name in duplicates:
        report.error(
            "colonna_duplicata", file, f"la colonna {name!r} compare piu' volte", line=1
        )
    known = {*required, *optional}
    extra = [c for c in present if c and c not in known]
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
                # A row written with the other separator has one of them between
                # each pair of columns, wherever the tokeniser put the cells.
                other = ";" if delimiter == "," else ","
                other_count = sum(v.count(other) for v in values)
                hint = (
                    f": usa lo stesso separatore ({delimiter!r}) dell'intestazione"
                    if other_count > 0 and other_count >= len(columns) - 1
                    else ""
                )
                report.error(
                    "riga_malformata",
                    file,
                    f"la riga ha {len(values)} celle invece di {len(columns)}{hint}",
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
    return CsvTable(rows=rows, delimiter=delimiter)


@dataclass(frozen=True)
class _SeparatorProblem:
    code: Literal["separatore_ambiguo", "separatore_non_valido"]
    message: str


def _tokenise(header_line: str, delimiter: str) -> list[str]:
    """The cells of the header line; ``csv.Error`` if it is not readable."""
    return next(csv.reader([header_line], delimiter=delimiter))


def _has_columns(fields: list[str], required: Sequence[str]) -> bool:
    """``True`` if the cells name all the ``required`` columns (not too many)."""
    if len(fields) > MAX_COLUMNS:
        return False
    names = {c.strip().lower() for c in fields}
    return all(name in names for name in required)


def _tab_separated(candidates: Sequence[list[str]], known: set[str]) -> bool:
    """``True`` if a header cell looks like columns glued by tabs."""
    for fields in candidates:
        if len(fields) > MAX_COLUMNS:
            continue
        for cell in fields:
            if "\t" in cell and (
                len(fields) == 1
                or any(part.strip().lower() in known for part in cell.split("\t"))
            ):
                return True
    return False


def _choose_separator(
    header_line: str, required: Sequence[str], known: set[str]
) -> tuple[str, list[str]] | _SeparatorProblem:
    """The separator and the header cells, or what is wrong with the header.

    The comma wins if its tokenisation has all the required columns (also on
    a tie); then the semicolon. If neither does, it is a tab or an Excel
    ``sep=`` line, or a header mixing both separators, or the file is left to
    the missing-column report. The semicolon pass runs only if the line has a
    ``;`` and a comma pass of a sane width: hostile input does not burn CPU.

    Raises:
        csv.Error: the header is not readable as CSV.
    """
    if _EXCEL_SEP_HINT.fullmatch(header_line.strip()) is not None:
        return _SeparatorProblem(
            "separatore_non_valido",
            f"la prima riga {header_line.strip()!r} e' il suggerimento di Excel "
            "sul separatore: rimuovila, l'intestazione deve essere la prima riga",
        )
    comma_fields = _tokenise(header_line, ",")
    if (
        ";" not in header_line
        or len(comma_fields) > MAX_COLUMNS
        or _has_columns(comma_fields, required)
    ):
        if not _has_columns(comma_fields, required) and _tab_separated(
            [comma_fields], known
        ):
            return _SeparatorProblem("separatore_non_valido", _TAB_ERROR)
        return ",", comma_fields
    try:
        semicolon_fields = _tokenise(header_line, ";")
    except csv.Error:
        # The comma tokenisation worked, but a ';' cell is over the csv field
        # limit: that is no ';' header, the comma stands.
        return ",", comma_fields
    if _has_columns(semicolon_fields, required):
        return ";", semicolon_fields
    if _tab_separated([comma_fields, semicolon_fields], known):
        return _SeparatorProblem("separatore_non_valido", _TAB_ERROR)
    if len(comma_fields) > 1 and len(semicolon_fields) > 1:
        return _SeparatorProblem("separatore_ambiguo", _AMBIGUOUS_ERROR)
    if len(semicolon_fields) > 1:
        return ";", semicolon_fields
    return ",", comma_fields


def _first_line_end(text: str) -> int:
    """Index of the end of the first line (CR, LF or end of text)."""
    match = _LINE_END.search(text)
    return len(text) if match is None else match.start()
