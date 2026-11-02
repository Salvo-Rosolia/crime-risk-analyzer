"""Outcome of the check of the source files (#415).

The check does not stop at the first problem: it collects everything in a
:class:`ValidationReport`, so whoever uploads the files fixes them in one go.
The ``errors`` block the activation of the set; the ``warnings`` do not.

``Problem.file`` is one of the names of the upload fields (:data:`FILE_NAMES`),
so the interface can attach each message to its slot. ``line`` is the
line number of the file (1 = header) for the CSVs, ``None`` elsewhere.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

__all__ = [
    "CODE_OTHER_PROBLEMS",
    "FILE_NAMES",
    "MAX_PROBLEMS_PER_CODE",
    "MAX_PROBLEMS_PER_FILE",
    "FileName",
    "Problem",
    "SourceValidationError",
    "ValidationReport",
]

FileName = Literal["ontology", "osm_table", "data", "hazard_table", "boundaries"]
FILE_NAMES: tuple[FileName, ...] = (
    "ontology",
    "osm_table",
    "data",
    "hazard_table",
    "boundaries",
)


#: Report caps: a broken file must not produce millions of messages. Beyond
#: the cap (per file, or per code inside a file) the problems are not listed:
#: a single ``altri_problemi`` line per file remains with the real count.
MAX_PROBLEMS_PER_FILE = 100
MAX_PROBLEMS_PER_CODE = 50
CODE_OTHER_PROBLEMS = "altri_problemi"


class Problem(BaseModel):
    """A problem found in a file: stable ``code``, ``message`` in Italian."""

    model_config = ConfigDict(frozen=True)

    code: str
    file: FileName
    message: str
    line: int | None = None


class ValidationReport(BaseModel):
    """All the problems of an upload, divided into blocking and warnings."""

    errors: list[Problem] = Field(default_factory=lambda: [])
    warnings: list[Problem] = Field(default_factory=lambda: [])
    _counts: dict[tuple[str, FileName, str], int] = PrivateAttr(
        default_factory=lambda: {}
    )
    _per_file: dict[tuple[str, FileName], int] = PrivateAttr(default_factory=lambda: {})
    _omitted: dict[tuple[str, FileName], int] = PrivateAttr(default_factory=lambda: {})

    @property
    def ok(self) -> bool:
        """``True`` if there are no blocking problems (warnings do not count)."""
        return not self.errors

    def error(
        self, code: str, file: FileName, message: str, line: int | None = None
    ) -> None:
        self._add("errors", self.errors, code, file, message, line)

    def warning(
        self, code: str, file: FileName, message: str, line: int | None = None
    ) -> None:
        self._add("warnings", self.warnings, code, file, message, line)

    def _add(
        self,
        kind: str,
        items: list[Problem],
        code: str,
        file: FileName,
        message: str,
        line: int | None,
    ) -> None:
        """Adds the problem, or counts it in the ``altri_problemi`` line of the file."""
        per_code = self._counts.get((kind, file, code), 0)
        per_file = self._per_file.get((kind, file), 0)
        self._counts[(kind, file, code)] = per_code + 1
        self._per_file[(kind, file)] = per_file + 1
        if per_file < MAX_PROBLEMS_PER_FILE and per_code < MAX_PROBLEMS_PER_CODE:
            items.append(Problem(code=code, file=file, message=message, line=line))
            return
        omitted = self._omitted.get((kind, file), 0) + 1
        self._omitted[(kind, file)] = omitted
        summary = Problem(
            code=CODE_OTHER_PROBLEMS,
            file=file,
            message=f"e altri {omitted} problemi non elencati in questo file",
        )
        for index, p in enumerate(items):
            if p.code == CODE_OTHER_PROBLEMS and p.file == file:
                items[index] = summary
                return
        items.append(summary)


class SourceValidationError(Exception):
    """The upload was rejected: ``report`` has all the problems."""

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        detail = "; ".join(f"[{p.file}] {p.message}" for p in report.errors)
        super().__init__(f"fonti non valide: {detail}")
