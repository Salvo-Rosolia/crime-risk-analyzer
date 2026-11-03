"""Per-POI risk profile extracted from the ontology (#76).

:class:`PoiRiskProfile` is the output of the SPARQL executor
(:mod:`crime_risk_analyzer.sparql_module.query_executor`): the four TERMINUS Crime
dimensions associated with a POI class via the OWL restriction pattern, plus the
``sparql_path`` (one-hop linear citation) for the citation layer.

Canonical schema: ``docs/specs/tree/backend/sparql.md`` §Output. The values are
bare TERMINUS class names in English Underscore_Case (the ENEA ontology has no
``rdfs:label``); the EN->IT map for the UI is built elsewhere.

**No numeric scoring** of dangerousness (legal constraint ``_project.md``):
here there are only qualitative sets of entities anchored to the ontology.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PoiRiskProfile(BaseModel):
    """TERMINUS risks associated with a POI class via OWL restriction.

    The lists are empty (never ``None``) when the class does not have the
    corresponding restriction or does not exist in the ontology: the absence of
    risk is an empty list, not an error.
    """

    poi_name: str | None = Field(
        default=None,
        description="Nome leggibile del POI OSM (es. 'Banca Intesa Sanpaolo').",
    )
    ontology_class: str = Field(
        description="Classe dell'ontologia attiva, bare interrogata (es. 'Bank')."
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
