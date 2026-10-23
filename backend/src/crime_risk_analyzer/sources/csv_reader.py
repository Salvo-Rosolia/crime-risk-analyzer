"""Lettura dei CSV caricati (#415): formato fisso, errori che dicono cosa fare.

Formato: intestazione obbligatoria, virgola come separatore, UTF-8 con o senza
BOM, fine riga LF o CRLF (quello che salva Excel). Un file con ``;`` o tab come
separatore (l'Excel italiano lo usa di default) da' un errore chiaro invece di una
lettura sbagliata. Righe vuote ignorate; ogni riga porta il numero di riga del
file (1 = intestazione) per i messaggi.
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

__all__ = ["MAX_COLONNE", "MAX_RIGHE", "MAX_ERRORI_RIGA", "CsvRow", "read_csv"]

#: Dopo tante righe malformate la lettura si ferma: il resto non aggiunge nulla.
MAX_ERRORI_RIGA = MAX_PROBLEMS_PER_CODE
#: Intestazione piu' larga: nessun file valido ha tante colonne.
MAX_COLONNE = 50
#: Righe di dati per file: oltre, la lettura si ferma (tempo prevedibile).
MAX_RIGHE = 200_000


@dataclass(frozen=True)
class CsvRow:
    """Una riga di dati: ``cells`` ha le colonne note, valori senza spazi ai lati."""

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
    """Righe del CSV, o ``None`` se il file non e' leggibile (errori nel ``report``).

    Segnala tutti i problemi di formato in una volta: colonne mancanti (una per
    colonna), colonne in piu' (avviso, ignorate), righe con un numero sbagliato di
    celle. Con colonne obbligatorie mancanti le righe non si leggono; le righe
    malformate sono segnalate e saltate, le altre vengono restituite cosi' il
    chiamante puo' continuare i controlli sul resto del file.
    """
    try:
        testo = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        report.error(
            "codifica_non_valida",
            file,
            "il file non e' in UTF-8: salvalo come CSV UTF-8",
        )
        return None
    if not testo.strip():
        report.error("file_vuoto", file, "il file e' vuoto")
        return None

    if testo[0] in ("\r", "\n"):
        report.error(
            "intestazione_mancante",
            file,
            "la prima riga e' vuota: l'intestazione deve essere la prima riga",
            line=1,
        )
        return None

    # Stessa tokenizzazione per riconoscere il separatore e per leggere i dati.
    reader = csv.reader(io.StringIO(testo, newline=""))
    try:
        campi = next(reader)
    except csv.Error as exc:
        report.error(
            "intestazione_non_leggibile",
            file,
            f"l'intestazione non e' leggibile come CSV: {str(exc)[:200]}",
            line=1,
        )
        return None
    if len(campi) == 1 and ";" in campi[0]:
        report.error(
            "separatore_non_valido",
            file,
            "il separatore deve essere la virgola, non il punto e virgola (;): "
            "salva il file come CSV con virgola",
            line=1,
        )
        return None
    if len(campi) == 1 and "\t" in campi[0]:
        report.error(
            "separatore_non_valido",
            file,
            "il separatore deve essere la virgola, non la tabulazione",
            line=1,
        )
        return None
    if len(campi) > MAX_COLONNE:
        report.error(
            "troppe_colonne",
            file,
            f"l'intestazione ha {len(campi)} colonne, il massimo e' {MAX_COLONNE}",
            line=1,
        )
        return None
    colonne = [c.strip().lower() for c in campi]
    presenti = set(colonne)

    mancanti = [c for c in required if c not in presenti]
    for nome in mancanti:
        report.error(
            "colonna_mancante",
            file,
            f"manca la colonna obbligatoria {nome!r} "
            f"(intestazione attesa: {', '.join([*required, *optional])})",
            line=1,
        )
    doppie = sorted(c for c, n in Counter(colonne).items() if n > 1)
    for nome in doppie:
        report.error(
            "colonna_duplicata", file, f"la colonna {nome!r} compare piu' volte", line=1
        )
    note = {*required, *optional}
    in_piu = [c for c in presenti if c not in note]
    in_piu.sort(key=colonne.index)
    if in_piu:
        report.warning(
            "colonna_in_piu",
            file,
            f"colonne non previste, ignorate: {', '.join(repr(c) for c in in_piu)}",
            line=1,
        )
    if mancanti or doppie:
        return None

    limite = MAX_RIGHE if max_rows is None else max_rows
    conteggio = 0
    righe: list[CsvRow] = []
    malformate = False
    errori_riga = 0
    try:
        for valori in reader:
            if not any(v.strip() for v in valori):
                continue
            line = reader.line_num
            conteggio += 1
            if conteggio > limite:
                report.error(
                    "troppe_righe",
                    file,
                    f"il file ha piu' di {limite} righe di dati: e' il massimo",
                    line=line,
                )
                return None
            if len(valori) != len(colonne):
                report.error(
                    "riga_malformata",
                    file,
                    f"la riga ha {len(valori)} celle invece di {len(colonne)}",
                    line=line,
                )
                malformate = True
                errori_riga += 1
                if errori_riga >= MAX_ERRORI_RIGA:
                    report.error(
                        "lettura_interrotta",
                        file,
                        f"lettura interrotta dopo {MAX_ERRORI_RIGA} righe "
                        "malformate: correggi il file e ricaricalo",
                        line=line,
                    )
                    return None
                continue
            celle = {c: v.strip() for c, v in zip(colonne, valori, strict=True)}
            righe.append(CsvRow(line=line, cells=celle))
    except csv.Error as exc:
        report.error("csv_illeggibile", file, f"CSV non leggibile: {exc}")
        return None
    if not righe and not malformate:
        report.error("file_senza_righe", file, "il file ha solo l'intestazione")
        return None
    return righe
