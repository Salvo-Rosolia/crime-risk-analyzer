"""OWL vocabulary of an ontology: namespace and names of the five properties (#415).

The pattern stays the OWL restriction one (``rdfs:subClassOf`` + ``owl:Restriction``
+ ``owl:onProperty`` + ``owl:someValuesFrom``); only the namespace and the names
of the properties linking a POI to its risks change. The default keeps the TERMINUS
values read from ``sparql_module/query_executor.py``.

The values end up in IRIs and queries: :meth:`OntologyVocabulary.problems` checks
them BEFORE using them (no unvalidated concatenation).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from crime_risk_analyzer.ontology_namespaces import TERMINUS_IRI

__all__ = ["TERMINUS_VOCABULARY", "OntologyVocabulary"]

_NAMESPACE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:[^\s<>\"{}|\\^`]+[#/]")
_PROPERTIES = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]*")


@dataclass(frozen=True)
class OntologyVocabulary:
    """Namespace and (local) names of the risk properties of the ontology."""

    namespace: str
    hazard: str
    critical_event: str
    performer: str
    vulnerability: tuple[str, ...]

    @property
    def properties(self) -> tuple[str, ...]:
        """Names of all the properties: hazard, event, vulnerability, stakeholder."""
        return (
            self.hazard,
            self.critical_event,
            *self.vulnerability,
            self.performer,
        )

    def problems(self) -> list[str]:
        """Reasons why the vocabulary is unusable (empty if valid)."""
        reasons: list[str] = []
        if _NAMESPACE.fullmatch(self.namespace) is None:
            reasons.append(
                f"namespace {self.namespace!r} non valido: serve un IRI assoluto "
                "che finisce con # o /"
            )
        if not self.vulnerability:
            reasons.append("serve almeno una proprieta' di vulnerabilita'")
        for name in self.properties:
            if _PROPERTIES.fullmatch(name) is None:
                reasons.append(
                    f"nome di proprieta' {name!r} non valido: solo lettere, cifre, "
                    "_ . -"
                )
        return reasons


#: TERMINUS values (dynamic sources spec, "the default keeps the TERMINUS values").
TERMINUS_VOCABULARY = OntologyVocabulary(
    namespace=f"{TERMINUS_IRI}#",
    hazard="havingHazard",
    critical_event="havingCriticalEvent",
    performer="havingPerformer",
    vulnerability=("isVulnerableTo", "havingVulnerability"),
)
