"""Vocabolario OWL di un'ontologia: namespace e nomi delle cinque proprieta' (#415).

Il pattern resta quello a restrizioni OWL (``rdfs:subClassOf`` + ``owl:Restriction``
+ ``owl:onProperty`` + ``owl:someValuesFrom``); cambiano solo namespace e nomi
delle proprieta' che legano un POI ai suoi rischi. Il default conserva i valori
TERMINUS letti da ``sparql_module/query_executor.py``.

I valori finiscono in IRI e query: :meth:`OntologyVocabulary.problems` li
controlla PRIMA di usarli (nessuna concatenazione non validata).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from crime_risk_analyzer.ontology_namespaces import TERMINUS_IRI

__all__ = ["TERMINUS_VOCABULARY", "OntologyVocabulary"]

_NAMESPACE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:[^\s<>\"{}|\\^`]+[#/]")
_PROPRIETA = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]*")


@dataclass(frozen=True)
class OntologyVocabulary:
    """Namespace e nomi (locali) delle proprieta' di rischio dell'ontologia."""

    namespace: str
    hazard: str
    critical_event: str
    performer: str
    vulnerability: tuple[str, ...]

    @property
    def properties(self) -> tuple[str, ...]:
        """Nomi di tutte le proprieta': hazard, evento, vulnerabilita', stakeholder."""
        return (
            self.hazard,
            self.critical_event,
            *self.vulnerability,
            self.performer,
        )

    def problems(self) -> list[str]:
        """Motivi per cui il vocabolario non e' utilizzabile (vuota se valido)."""
        motivi: list[str] = []
        if _NAMESPACE.fullmatch(self.namespace) is None:
            motivi.append(
                f"namespace {self.namespace!r} non valido: serve un IRI assoluto "
                "che finisce con # o /"
            )
        if not self.vulnerability:
            motivi.append("serve almeno una proprieta' di vulnerabilita'")
        for nome in self.properties:
            if _PROPRIETA.fullmatch(nome) is None:
                motivi.append(
                    f"nome di proprieta' {nome!r} non valido: solo lettere, cifre, "
                    "_ . -"
                )
        return motivi


#: Valori TERMINUS (spec fonti dinamiche, "il default conserva i valori TERMINUS").
TERMINUS_VOCABULARY = OntologyVocabulary(
    namespace=f"{TERMINUS_IRI}#",
    hazard="havingHazard",
    critical_event="havingCriticalEvent",
    performer="havingPerformer",
    vulnerability=("isVulnerableTo", "havingVulnerability"),
)
