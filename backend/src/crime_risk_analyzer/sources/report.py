"""Esito del controllo dei file delle fonti (#415).

Il controllo non si ferma al primo problema: raccoglie tutto in un
:class:`ValidationReport`, cosi' chi carica i file corregge in un solo giro.
Gli ``errors`` bloccano l'attivazione del set; i ``warnings`` no.

``Problem.file`` e' uno dei nomi dei campi di caricamento (:data:`FILE_NAMES`),
cosi' l'interfaccia puo' agganciare ogni messaggio al suo slot. ``line`` e' il
numero di riga del file (1 = intestazione) per i CSV, ``None`` altrove.
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


#: Tetti del report: un file rotto non deve produrre milioni di messaggi. Oltre
#: il tetto (per file, o per codice dentro un file) i problemi non si elencano:
#: resta una sola riga ``altri_problemi`` per file con il conteggio reale.
MAX_PROBLEMS_PER_FILE = 100
MAX_PROBLEMS_PER_CODE = 50
CODE_OTHER_PROBLEMS = "altri_problemi"


class Problem(BaseModel):
    """Un problema trovato in un file: ``code`` stabile, ``message`` in italiano."""

    model_config = ConfigDict(frozen=True)

    code: str
    file: FileName
    message: str
    line: int | None = None


class ValidationReport(BaseModel):
    """Tutti i problemi di un caricamento, divisi in bloccanti e avvisi."""

    errors: list[Problem] = Field(default_factory=lambda: [])
    warnings: list[Problem] = Field(default_factory=lambda: [])
    _conteggi: dict[tuple[str, FileName, str], int] = PrivateAttr(
        default_factory=lambda: {}
    )
    _per_file: dict[tuple[str, FileName], int] = PrivateAttr(default_factory=lambda: {})
    _omessi: dict[tuple[str, FileName], int] = PrivateAttr(default_factory=lambda: {})

    @property
    def ok(self) -> bool:
        """``True`` se non ci sono problemi bloccanti (gli avvisi non contano)."""
        return not self.errors

    def error(
        self, code: str, file: FileName, message: str, line: int | None = None
    ) -> None:
        self._aggiungi("errors", self.errors, code, file, message, line)

    def warning(
        self, code: str, file: FileName, message: str, line: int | None = None
    ) -> None:
        self._aggiungi("warnings", self.warnings, code, file, message, line)

    def _aggiungi(
        self,
        tipo: str,
        elenco: list[Problem],
        code: str,
        file: FileName,
        message: str,
        line: int | None,
    ) -> None:
        """Aggiunge il problema, o lo conta nella riga ``altri_problemi`` del file."""
        per_codice = self._conteggi.get((tipo, file, code), 0)
        per_file = self._per_file.get((tipo, file), 0)
        self._conteggi[(tipo, file, code)] = per_codice + 1
        self._per_file[(tipo, file)] = per_file + 1
        if per_file < MAX_PROBLEMS_PER_FILE and per_codice < MAX_PROBLEMS_PER_CODE:
            elenco.append(Problem(code=code, file=file, message=message, line=line))
            return
        omessi = self._omessi.get((tipo, file), 0) + 1
        self._omessi[(tipo, file)] = omessi
        riepilogo = Problem(
            code=CODE_OTHER_PROBLEMS,
            file=file,
            message=f"e altri {omessi} problemi non elencati in questo file",
        )
        for indice, p in enumerate(elenco):
            if p.code == CODE_OTHER_PROBLEMS and p.file == file:
                elenco[indice] = riepilogo
                return
        elenco.append(riepilogo)


class SourceValidationError(Exception):
    """Il caricamento e' stato rifiutato: ``report`` ha tutti i problemi."""

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        dettaglio = "; ".join(f"[{p.file}] {p.message}" for p in report.errors)
        super().__init__(f"fonti non valide: {dettaglio}")
