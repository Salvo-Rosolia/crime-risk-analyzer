"""Limiti e regole di sicurezza dei file caricati (#415, "regole restrittive").

Etichette e nomi finiscono nel prompt del modello: per questo accettano solo
lettere, cifre, spazi e punteggiatura semplice, con una lunghezza massima. Una
riga a capo, una parentesi angolare o un backtick non passano, quindi un file non
puo' portare nel prompt un blocco di testo che sembri un'istruzione strutturata.
Il controllo NON capisce il significato di una frase: un'etichetta fatta di sole
parole ammesse passa anche se suona come un ordine.
"""

from __future__ import annotations

import re

__all__ = [
    "MAX_BYTES_CSV",
    "MAX_BYTES_GEOJSON",
    "MAX_BYTES_ONTOLOGIA",
    "MAX_BYTES_RICHIESTA",
    "MAX_FILE_MULTIPART",
    "MAX_CAMPI_MULTIPART",
    "MAX_PARTE_CAMPO",
    "MAX_LUNGHEZZA_NOTA",
    "MAX_LUNGHEZZA_TESTO",
    "controlla_nota",
    "controlla_testo",
]

MAX_BYTES_ONTOLOGIA = 20 * 1024 * 1024
MAX_BYTES_GEOJSON = 10 * 1024 * 1024
MAX_BYTES_CSV = 5 * 1024 * 1024
#: Tetto del corpo di ``POST /sources`` (``Content-Length``), controllato prima di
#: leggerlo: somma dei tetti dei file piu' 1 MB per intestazioni dei campi e form.
MAX_BYTES_RICHIESTA = (
    MAX_BYTES_ONTOLOGIA + MAX_BYTES_GEOJSON + 3 * MAX_BYTES_CSV + 1024 * 1024
)
#: Limiti del multipart (Starlette ``request.form``): 5 file (ontologia, 3 CSV,
#: confini), pochi campi di testo (vocabolario + le proprieta' di vulnerabilita').
MAX_FILE_MULTIPART = 5
MAX_CAMPI_MULTIPART = 20
#: Dimensione massima di un campo di testo (non dei file).
MAX_PARTE_CAMPO = 64 * 1024

MAX_LUNGHEZZA_TESTO = 120
#: Le note della tabella hazard-voce non entrano nel prompt: solo lunghezza e
#: caratteri di controllo.
MAX_LUNGHEZZA_NOTA = 500

#: Lettere Unicode, cifre, ``_``, spazio e ``. , ' ’ ( ) / - : ; &``.
_TESTO_AMMESSO = re.compile(r"[\w .,'’()/\-:;&]+")
_CONTROLLO = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")


def controlla_testo(testo: str) -> str | None:
    """Motivo per cui ``testo`` non e' ammesso come etichetta o nome, o ``None``."""
    if not testo.strip():
        return "il testo e' vuoto"
    if len(testo) > MAX_LUNGHEZZA_TESTO:
        return f"il testo supera {MAX_LUNGHEZZA_TESTO} caratteri ({len(testo)})"
    if _TESTO_AMMESSO.fullmatch(testo) is None:
        return (
            "il testo contiene caratteri non ammessi: sono ammessi solo lettere, "
            "cifre, spazi e . , ' ( ) / - : ; &"
        )
    return None


def controlla_nota(nota: str) -> str | None:
    """Motivo per cui ``nota`` non e' ammessa, o ``None`` (testo libero, corto)."""
    if len(nota) > MAX_LUNGHEZZA_NOTA:
        return f"la nota supera {MAX_LUNGHEZZA_NOTA} caratteri ({len(nota)})"
    if _CONTROLLO.search(nota):
        return "la nota contiene caratteri di controllo"
    return None
