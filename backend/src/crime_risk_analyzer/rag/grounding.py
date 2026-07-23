"""Grounding e citation layer -> context validato (#24).

Secondo layer della pipeline /analyze (retrieval #22 -> grounding #24 ->
generation #23). :func:`ground` trasforma il ``RetrievalContext`` grezzo (#22) nel
``context_dict`` VALIDATO che
:func:`~crime_risk_analyzer.rag.generation.generate_analysis` gia' si aspetta.

Grounding DETERMINISTICO pre-LLM: i rischi strutturati sono costruiti dai profili
ontologici, non dall'output del modello -> non allucinabili. Poiche' il
``RetrievalContext`` contiene solo hazard ontologici (da SPARQL/OWL restriction),
ogni rischio strutturato ha ``tag="ONTOLOGIA"``: la FONTE e' sempre l'ontologia.

La ``confidence`` gradua invece la FORZA PROBATORIA del rischio in base alla
verificabilita' del POI in OSM (#202):

- ``verificato`` = hazard ontologico su un POI con ``name`` OSM non vuoto (doppio
  ancoraggio: ontologia + entita' OSM verificabile).
- ``da_confermare`` = hazard ontologico su una feature OSM anonima (``name`` vuoto/
  whitespace): l'ancoraggio OSM e' debole, il supporto poggia sulla sola ontologia.
- ``ipotesi`` = NON prodotto qui (rimandato, fuori scope): resta 0.

Il ``tag`` resta ``ONTOLOGIA`` per entrambi i livelli (la fonte non cambia, cambia
solo la forza probatoria). La confidence qualifica la prova, MAI la pericolosita'
(vincolo legale, _project.md §Vincoli). ``CONTESTO``/``SPECULATIVO`` restano
vocabolario per la narrativa LLM, non prodotti qui.

Funzione PURA e sincrona: nessun I/O, nessun accesso al grafo/executor.
"""

from __future__ import annotations

from typing import TypedDict

from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.models.vocab import Confidence, Tag
from crime_risk_analyzer.rag.retrieval import RetrievalContext

__all__ = [
    "GroundedContext",
    "GroundedRisk",
    "ValidatedRisk",
    "confidence_from_poi_name",
    "ground",
]

#: La fonte di ogni rischio strutturato e' sempre l'ontologia (vedi docstring): il
#: tag non gradua la forza probatoria, quella e' compito della ``confidence``.
_TAG: Tag = "ONTOLOGIA"
#: Confidence per un hazard su POI con nome OSM (doppio ancoraggio: ontologia +
#: entita' OSM verificabile).
_CONFIDENCE_NAMED: Confidence = "verificato"
#: Confidence per un hazard su feature OSM anonima (ancoraggio OSM debole): il
#: supporto poggia sulla sola ontologia, la fonte (tag) resta comunque ONTOLOGIA.
_CONFIDENCE_ANONYMOUS: Confidence = "da_confermare"


def confidence_from_poi_name(name: str) -> Confidence:
    """Grada la confidence dalla verificabilita' del POI in OSM (#202).

    ``verificato`` se ``name`` (strip) e' non vuoto (entita' OSM verificabile,
    doppio ancoraggio ontologia + OSM), ``da_confermare`` se vuoto/whitespace
    (feature anonima, ancoraggio OSM debole). Il tag della fonte resta ONTOLOGIA
    in entrambi i casi.

    Helper CONDIVISO (unica sorgente della regola nome->verificabilita', M1): il
    grounding lo applica per-rischio, l'orchestrator per la ``confidence``
    per-POI, cosi' il badge del POI non diverge dai livelli dei suoi rischi.
    """
    return _CONFIDENCE_NAMED if name.strip() else _CONFIDENCE_ANONYMOUS


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

    Per ogni POI costruisce i rischi ontologici (tag ``ONTOLOGIA``) con la
    citazione SPARQL per-hazard; la ``confidence`` di TUTTI i rischi del POI e'
    ``verificato`` se il POI ha un nome OSM, ``da_confermare`` se e' una feature
    anonima (:func:`confidence_from_poi_name`, #202). I POI fuori ontologia
    (``GenericUrbanPOI``/profilo vuoto) restano con ``risks=[]``. Il
    ``confidence_summary`` conta i livelli reali; ``ipotesi`` resta 0
    (rimandato, fuori scope).
    """
    validated: list[ValidatedRisk] = []
    n_verificato = 0
    n_da_confermare = 0
    for poi in context["pois"]:
        profile = context["profiles"][poi["terminus_class"]]
        confidence = confidence_from_poi_name(poi["name"])
        risks: list[GroundedRisk] = [
            {
                "hazard": hazard,
                "tag": _TAG,
                "confidence": confidence,
                "source": _source_for_hazard(profile, hazard),
            }
            for hazard in profile.hazards
        ]
        if confidence == _CONFIDENCE_NAMED:
            n_verificato += len(risks)
        else:
            n_da_confermare += len(risks)
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
            "verificato": n_verificato,
            "da_confermare": n_da_confermare,
            "ipotesi": 0,
        },
    }
