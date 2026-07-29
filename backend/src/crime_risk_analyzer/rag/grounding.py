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


class OntologyEntity(TypedDict):
    """Entita' ontologica di un asse non-hazard, con la propria citazione (#256).

    Non porta ``confidence``: la forza probatoria e' un bit derivato dal NOME del
    POI, quindi identica per ogni asserzione ontologica su quel punto — il badge
    del POI le qualifica tutte, e ripeterlo per voce aggiungerebbe rumore invece di
    informazione. Non porta ``tag`` per la stessa ragione: la fonte e' l'ontologia
    per costruzione.
    """

    name: str
    source: str


class ValidatedRisk(TypedDict):
    """Rischi validati per un POI (forma letta da generation).

    ``poi_id`` e' l'id OSM del punto: e' la chiave con cui un consumatore attribuisce
    questi rischi al POI giusto. Il ``poi`` (nome) resta per il display, ma i nomi OSM
    non sono ne' unici ne' sempre presenti (le feature anonime arrivano con
    ``name=""``), quindi non identificano nulla.

    Limite noto dell'id, pre-esistente e non chiuso qui: ``overpass_client`` lo
    costruisce dal solo ``element["id"]`` senza il tipo di elemento, e node e way
    vivono in namespace OSM separati — ``node/123`` e ``way/123`` collasserebbero
    sulla stessa stringa. Sui 4 snapshot committati non ci sono collisioni, ma
    l'unicita' e' un fatto osservato, non garantito per costruzione.
    """

    poi_id: str
    poi: str
    terminus_class: str
    risks: list[GroundedRisk]
    #: Gli assi TERMINUS oltre agli hazard (#256): l'executor li estraeva gia' a ogni
    #: richiesta, ma ``critical_events`` non lo leggeva nessuno e le vulnerabilita'
    #: arrivavano al prompt come stringhe nude, senza la citazione che le ancora. Ora
    #: ognuno porta il proprio path. Lo stakeholder resta fuori: vedi
    #: :data:`_PROPS_VULNERABILITY` e il commento sopra.
    critical_events: list[OntologyEntity]
    vulnerabilities: list[OntologyEntity]
    sparql_path: str | None


class GroundedContext(TypedDict):
    """Context validato: input di ``generate_analysis`` (#23)."""

    zona: str
    validated_risks: list[ValidatedRisk]
    confidence_summary: dict[str, int]


#: Le property TERMINUS per asse, nell'ordine in cui ``query_executor`` le
#: interroga. La vulnerabilita' ne usa DUE (divergenza #78): entrambe vanno cercate
#: o si perde il path di un filler legittimo.
_PROPS_HAZARD = ("havingHazard",)
_PROPS_CRITICAL_EVENT = ("havingCriticalEvent",)
_PROPS_VULNERABILITY = ("isVulnerableTo", "havingVulnerability")
#: ``havingPerformer`` (stakeholder) NON e' ancorato qui, di proposito: il vocabolario
#: controllato (#77) non ha la categoria e 72 dei suoi filler non hanno etichetta
#: italiana, quindi l'asse uscirebbe interamente in inglese in una UI italiana. Non
#: e' calcolato-e-non-letto — sarebbe il difetto che #256 chiude — ma semplicemente
#: non ancorato finche' il vocabolario non lo copre. Con ``_source_for``/``_entities``
#: generalizzate, ri-aggiungerlo e' una riga per punto.


def _source_for(profile: PoiRiskProfile, props: tuple[str, ...], filler: str) -> str:
    """Path SPARQL reale di ``filler`` per una delle ``props``, dai ``sparql_paths``.

    Un filler puo' essere ereditato da una superclasse via ``rdfs:subClassOf*``: il
    path reale cita quella classe, quindi va PRESO dai ``sparql_paths`` (non
    sintetizzato da ``terminus_class``). Fallback sintetizzato sulla prima property
    solo se nessun path combacia (non atteso: ``sparql_paths`` ha un path per
    filler).
    """
    for path in profile.sparql_paths:
        parts = [segment.strip() for segment in path.split("→")]
        if len(parts) == 3 and parts[1] in props and parts[2] == filler:
            return path
    return f"{profile.terminus_class} → {props[0]} → {filler}"


def _entities(
    profile: PoiRiskProfile, props: tuple[str, ...], fillers: list[str]
) -> list[OntologyEntity]:
    """Filler di un asse, ciascuno con la propria citazione."""
    return [
        OntologyEntity(name=filler, source=_source_for(profile, props, filler))
        for filler in fillers
    ]


def ground(context: RetrievalContext) -> GroundedContext:
    """Trasforma il ``RetrievalContext`` grezzo (#22) nel context validato (#23).

    Per ogni POI costruisce i rischi ontologici (tag ``ONTOLOGIA``) con la
    citazione SPARQL per-hazard; la ``confidence`` di TUTTI i rischi del POI e'
    ``verificato`` se il POI ha un nome OSM, ``da_confermare`` se e' una feature
    anonima (:func:`confidence_from_poi_name`, #202). I POI fuori ontologia
    (``GenericUrbanPOI``/profilo vuoto) restano con ``risks=[]``. Il
    ``confidence_summary`` conta i livelli reali.
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
                "source": _source_for(profile, _PROPS_HAZARD, hazard),
            }
            for hazard in profile.hazards
        ]
        if confidence == _CONFIDENCE_NAMED:
            n_verificato += len(risks)
        else:
            n_da_confermare += len(risks)
        validated.append(
            {
                "poi_id": poi["id"],
                "poi": poi["name"],
                "terminus_class": poi["terminus_class"],
                "risks": risks,
                "critical_events": _entities(
                    profile, _PROPS_CRITICAL_EVENT, profile.critical_events
                ),
                "vulnerabilities": _entities(
                    profile, _PROPS_VULNERABILITY, profile.vulnerabilities
                ),
                "sparql_path": risks[0]["source"] if risks else None,
            }
        )
    return {
        "zona": context["zona"],
        "validated_risks": validated,
        "confidence_summary": {
            "verificato": n_verificato,
            "da_confermare": n_da_confermare,
        },
    }
