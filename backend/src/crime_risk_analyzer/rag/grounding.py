"""Grounding e citation layer -> context validato (#24).

Secondo layer della pipeline /analyze (retrieval #22 -> grounding #24 ->
generation #23). :func:`ground` trasforma il ``RetrievalContext`` grezzo (#22) nel
``context_dict`` VALIDATO che
:func:`~crime_risk_analyzer.rag.generation.generate_analysis` gia' si aspetta.

Grounding DETERMINISTICO pre-LLM: i rischi strutturati sono costruiti dai profili
ontologici, non dall'output del modello -> non allucinabili. Poiche' il
``RetrievalContext`` contiene solo hazard ontologici (da SPARQL/OWL restriction),
ogni rischio strutturato e' ``tag="ONTOLOGIA"`` e ``confidence="confermato"``
(doppio-ancoraggio: ontologia + POI presente in OSM). ``CONTESTO``/``SPECULATIVO``
restano vocabolario per la narrativa LLM, non prodotti qui.

Funzione PURA e sincrona: nessun I/O, nessun accesso al grafo/executor.
"""

from __future__ import annotations

from typing import TypedDict

from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.models.vocab import Confidence, Tag
from crime_risk_analyzer.rag.retrieval import RetrievalContext

__all__ = ["GroundedContext", "GroundedRisk", "ValidatedRisk", "ground"]

#: Tutti i rischi strutturati sono ontologici e doppio-ancorati (vedi docstring).
_TAG: Tag = "ONTOLOGIA"
_CONFIDENCE: Confidence = "confermato"


class GroundedRisk(TypedDict):
    """Singolo rischio ancorato: hazard + tag/confidence + citazione SPARQL."""

    hazard: str
    tag: Tag
    confidence: Confidence
    source: str


class ValidatedRisk(TypedDict):
    """Rischi validati per un POI (forma letta da generation)."""

    poi: str
    terminus_class: str
    risks: list[GroundedRisk]
    vulnerabilities: list[str]
    sparql_path: str | None


class GroundedContext(TypedDict):
    """Context validato: input di ``generate_analysis`` (#23)."""

    zona: str
    validated_risks: list[ValidatedRisk]
    confidence_summary: dict[str, int]


def _source_for_hazard(profile: PoiRiskProfile, hazard: str) -> str:
    """Path SPARQL reale di ``hazard`` da ``profile.sparql_paths``.

    Un hazard puo' essere ereditato da una superclasse via ``rdfs:subClassOf*``: il
    path reale cita quella classe, quindi va PRESO dai ``sparql_paths`` (non
    sintetizzato da ``terminus_class``). Filtra su ``havingHazard`` e match per
    filler esatto. Fallback sintetizzato solo se nessun path combacia (non atteso:
    ``sparql_paths`` ha un path per filler).
    """
    for path in profile.sparql_paths:
        parts = [segment.strip() for segment in path.split("→")]
        if len(parts) == 3 and parts[1] == "havingHazard" and parts[2] == hazard:
            return path
    return f"{profile.terminus_class} → havingHazard → {hazard}"


def ground(context: RetrievalContext) -> GroundedContext:
    """Trasforma il ``RetrievalContext`` grezzo (#22) nel context validato (#23).

    Per ogni POI costruisce i rischi ontologici (tutti ``ONTOLOGIA``/``confermato``)
    con la citazione SPARQL per-hazard; i POI fuori ontologia
    (``GenericUrbanPOI``/profilo vuoto) restano con ``risks=[]``. Conta il
    ``confidence_summary`` (tutti confermati).
    """
    validated: list[ValidatedRisk] = []
    n_confermato = 0
    for poi in context["pois"]:
        profile = context["profiles"][poi["terminus_class"]]
        risks: list[GroundedRisk] = [
            {
                "hazard": hazard,
                "tag": _TAG,
                "confidence": _CONFIDENCE,
                "source": _source_for_hazard(profile, hazard),
            }
            for hazard in profile.hazards
        ]
        n_confermato += len(risks)
        validated.append(
            {
                "poi": poi["name"],
                "terminus_class": poi["terminus_class"],
                "risks": risks,
                "vulnerabilities": list(profile.vulnerabilities),
                "sparql_path": risks[0]["source"] if risks else None,
            }
        )
    return {
        "zona": context["zona"],
        "validated_risks": validated,
        "confidence_summary": {
            "confermato": n_confermato,
            "plausibile": 0,
            "speculativo": 0,
        },
    }
