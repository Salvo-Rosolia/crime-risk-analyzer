"""Profilo di rischio per POI estratto dall'ontologia (#76).

:class:`PoiRiskProfile` e' l'output dell'executor SPARQL
(:mod:`crime_risk_analyzer.sparql_module.query_executor`): le quattro dimensioni
TERMINUS Crime associate a una classe POI via il pattern OWL restriction, piu' i
``sparql_path`` (citazione lineare a un salto) per il citation layer.

Schema canonico: ``docs/specs/tree/backend/sparql.md`` §Output. I valori sono
nomi-classe TERMINUS bare in Underscore_Case inglese (l'ontologia ENEA non ha
``rdfs:label``); la mappa EN->IT per la UI si costruisce altrove.

**Nessuno scoring** numerico di pericolosita' (vincolo legale ``_project.md``):
qui ci sono solo insiemi qualitativi di entita' ancorate all'ontologia.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PoiRiskProfile(BaseModel):
    """Rischi TERMINUS associati a una classe POI via OWL restriction.

    Le liste sono vuote (mai ``None``) quando la classe non ha la corrispondente
    restrizione o non esiste nell'ontologia: l'assenza di rischio e' una lista
    vuota, non un errore.
    """

    poi_name: str | None = Field(
        default=None,
        description="Nome leggibile del POI OSM (es. 'Banca Intesa Sanpaolo').",
    )
    terminus_class: str = Field(
        description="Classe TERMINUS bare interrogata (es. 'Bank')."
    )
    hazards: list[str] = Field(
        default_factory=list,
        description="Anthropic_hazard via havingHazard (nomi-classe bare).",
    )
    critical_events: list[str] = Field(
        default_factory=list,
        description="Critical_event_of_system via havingCriticalEvent.",
    )
    vulnerabilities: list[str] = Field(
        default_factory=list,
        description="Vulnerability via isVulnerableTo + havingVulnerability.",
    )
    stakeholders: list[str] = Field(
        default_factory=list,
        description="Stakeholder via havingPerformer.",
    )
    sparql_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Citazioni lineari a un salto 'Classe → property → entita' (glyph "
            "Unicode U+2192), UNA PER FILLER: e' l'input grezzo del citation "
            "layer/grounding (#24). E' una LISTA, distinta dal campo singolare "
            "'sparql_path' per-POI dello schema /analyze (orchestrator.md): la "
            "riduzione lista→singola spetta al wiring orchestrator (#18)/grounding "
            "(#24), non a questo modulo."
        ),
    )
