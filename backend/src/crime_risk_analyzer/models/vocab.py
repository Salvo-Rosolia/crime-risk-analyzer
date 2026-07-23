"""Vocabolario tipizzato del citation layer (confidence + tag).

Punto unico di verita' per i valori canonici attraversati da grounding,
generation e output JSON. Renderli :data:`Literal` trasforma un invariante di
dominio in un vincolo verificato dai tipi (pyright) e dalla validazione Pydantic:
un ``confidence="alto"`` o un casing errato (``"Confermato"``) falliscono invece
di propagarsi silenziosamente.

Casing canonico (``_project.md`` §Confidence/§Citation):
- ``confidence`` -> **minuscolo**: ``verificato`` / ``da_confermare`` / ``ipotesi``.
- ``tag`` -> **maiuscolo**: ``ONTOLOGIA`` / ``CONTESTO`` / ``SPECULATIVO``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: Livello di confidenza qualitativo (mai un punteggio numerico). Casing
#: canonico minuscolo, allineato a ``ConfidenceSummary`` e ai dati demo.
Confidence = Literal["verificato", "da_confermare", "ipotesi"]

#: Tag fonte del citation layer (anti-hallucination). Casing canonico maiuscolo.
Tag = Literal["ONTOLOGIA", "CONTESTO", "SPECULATIVO"]


class ConfidenceSummary(BaseModel):
    """Conteggio dei rischi per livello di confidenza.

    Sostituisce il vecchio ``dict[str, int]``: i tre livelli canonici diventano
    campi tipizzati (default 0, non negativi), cosi' lo shape e' garantito dal
    modello invece che convenzionale.
    """

    verificato: int = Field(default=0, ge=0, description="Rischi verificati.")
    da_confermare: int = Field(default=0, ge=0, description="Rischi da confermare.")
    ipotesi: int = Field(default=0, ge=0, description="Rischi a livello di ipotesi.")
