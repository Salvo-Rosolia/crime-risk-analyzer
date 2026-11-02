"""Grounding and citation layer -> validated context (#24).

Second layer of the /analyze pipeline (retrieval #22 -> grounding #24 ->
generation #23). :func:`ground` transforms the raw ``RetrievalContext`` (#22) into the
VALIDATED ``context_dict`` that
:func:`~crime_risk_analyzer.rag.generation.generate_analysis` already expects.

DETERMINISTIC pre-LLM grounding: the structured risks are built from the
ontological profiles, not from the model output -> not hallucinable. Since the
``RetrievalContext`` contains only ontological hazards (from SPARQL/OWL restriction),
every structured risk has ``tag="ONTOLOGIA"``: the SOURCE is always the ontology.

The ``confidence`` instead grades the EVIDENTIAL STRENGTH of the risk based on the
verifiability of the POI in OSM (#202):

- ``verificato`` = ontological hazard on a POI with a non-empty OSM ``name`` (double
  anchoring: ontology + verifiable OSM entity).
- ``da_confermare`` = ontological hazard on an anonymous OSM feature (empty/
  whitespace ``name``): the OSM anchoring is weak, the support rests on the ontology
  alone.

The ``tag`` stays ``ONTOLOGIA`` for both levels (the source does not change, only the
evidential strength changes). The confidence qualifies the evidence, NEVER the
dangerousness (legal constraint, _project.md §Vincoli). ``CONTESTO``/``SPECULATIVO``
remain vocabulary for the LLM narrative, not produced here.

Synchronous and deterministic function: no access to the graph/executor. The only I/O
is the reading, once per process and then cached, of the package's ISTAT data
(#345).
"""

from __future__ import annotations

from typing import NotRequired, TypedDict

from crime_risk_analyzer.istat.rows import IstatPoi, istat_for_poi
from crime_risk_analyzer.models.risk import PoiRiskProfile
from crime_risk_analyzer.models.vocab import Confidence, Tag
from crime_risk_analyzer.rag.retrieval import RetrievalContext
from crime_risk_analyzer.sources.context import current_ontology

__all__ = [
    "GroundedContext",
    "GroundedRisk",
    "ValidatedRisk",
    "confidence_from_poi_name",
    "ground",
]

#: The source of every structured risk is always the ontology (see docstring): the
#: tag does not grade the evidential strength, that is the job of the ``confidence``.
_TAG: Tag = "ONTOLOGIA"
#: Confidence for a hazard on a POI with an OSM name (double anchoring: ontology +
#: verifiable OSM entity).
_CONFIDENCE_NAMED: Confidence = "verificato"
#: Confidence for a hazard on an anonymous OSM feature (weak OSM anchoring): the
#: support rests on the ontology alone, the source (tag) stays ONTOLOGIA anyway.
_CONFIDENCE_ANONYMOUS: Confidence = "da_confermare"


def confidence_from_poi_name(name: str) -> Confidence:
    """Grades the confidence from the verifiability of the POI in OSM (#202).

    ``verificato`` if ``name`` (stripped) is non-empty (verifiable OSM entity,
    double anchoring ontology + OSM), ``da_confermare`` if empty/whitespace
    (anonymous feature, weak OSM anchoring). The source tag stays ONTOLOGIA
    in both cases.

    SHARED helper (single source of the name->verifiability rule, M1): the
    grounding applies it per risk, the orchestrator for the per-POI ``confidence``,
    so the POI badge does not diverge from the levels of its risks.

    SINGLE and deterministic signal (#258): only the presence of the OSM ``name``
    tag, no other source (``wikidata``/``operator``/``brand``, element type,
    mapping fidelity) contributes to the level. The literal values
    (``verificato``/``da_confermare``) remain the stable contract between
    backend/frontend/eval; the frontend instead shows the honest labels
    "Identificato"/"Anonimo" (:mod:`core/confidence.ts`) so as not to suggest
    a verification process wider than this single bit.
    """
    return _CONFIDENCE_NAMED if name.strip() else _CONFIDENCE_ANONYMOUS


class GroundedRisk(TypedDict):
    """Single anchored risk: hazard + tag/confidence + SPARQL citation."""

    hazard: str
    tag: Tag
    confidence: Confidence
    source: str


class OntologyEntity(TypedDict):
    """Ontological entity of a non-hazard axis, with its own citation (#256).

    It does not carry ``confidence``: the evidential strength is a bit derived from the
    NAME of the POI, hence identical for every ontological assertion on that point — the
    POI badge qualifies them all, and repeating it per item would add noise instead of
    information. It does not carry ``tag`` for the same reason: the source is the
    ontology by construction.
    """

    name: str
    source: str


class ValidatedRisk(TypedDict):
    """Validated risks for a POI (shape read by generation).

    ``poi_id`` is the OSM id of the point: it is the key by which a consumer attributes
    these risks to the right POI. The ``poi`` (name) stays for display, but the OSM
    names are neither unique nor always present (anonymous features arrive with
    ``name=""``), so they identify nothing.

    Known limit of the id, pre-existing and not closed here: ``overpass_client`` builds
    it from ``element["id"]`` alone without the element type, and node and way
    live in separate OSM namespaces — ``node/123`` and ``way/123`` would collapse
    onto the same string. On the 4 committed snapshots there are no collisions, but
    uniqueness is an observed fact, not guaranteed by construction.
    """

    poi_id: str
    poi: str
    terminus_class: str
    risks: list[GroundedRisk]
    #: The TERMINUS axes beyond the hazards (#256): the executor already extracted them
    #: on every request, but nobody read ``critical_events`` and the vulnerabilities
    #: reached the prompt as bare strings, without the citation that anchors them. Now
    #: each carries its own path, ``stakeholders`` included since the controlled
    #: vocabulary also covers that category (#270).
    critical_events: list[OntologyEntity]
    vulnerabilities: list[OntologyEntity]
    stakeholders: list[OntologyEntity]
    sparql_path: str | None
    #: ISTAT data of the POI's place linked to its hazards (#345, spec 4.3):
    #: capoluogo municipality or province derived from the POI's COORDINATES, never from
    #: the centre of the area (in evaluation the ``geo`` is a placeholder). ALWAYS
    #: computed: the zone cache already carries it and the cold-cache reconstruction is
    #: deterministic; the switch acts only on the prompt and the figures check. Since
    #: #346 it also decides whether ``poi[].istat`` reaches the client in phase 1 of
    #: ``/analyze`` (the filter is in ``orchestrator._build_poi_list``): i.e. the order
    #: of the risks in the POI Detail. ``None`` outside every polygon, without linked
    #: items or without data. ``NotRequired``: the hand-built contexts (tests, doubles)
    #: remain valid without the field.
    istat: NotRequired[IstatPoi | None]


class GroundedContext(TypedDict):
    """Validated context: input of ``generate_analysis`` (#23)."""

    zona: str
    validated_risks: list[ValidatedRisk]
    confidence_summary: dict[str, int]


def _source_for(profile: PoiRiskProfile, props: tuple[str, ...], filler: str) -> str:
    """Real SPARQL path of ``filler`` for one of the ``props``, from the
    ``sparql_paths``.

    A filler can be inherited from a superclass via ``rdfs:subClassOf*``: the real
    path cites that class, so it must be TAKEN from the ``sparql_paths`` (not
    synthesised from ``terminus_class``). Fallback synthesised on the first property
    only if no path matches (not expected: ``sparql_paths`` has a path per
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
    """Fillers of an axis, each with its own citation."""
    return [
        OntologyEntity(name=filler, source=_source_for(profile, props, filler))
        for filler in fillers
    ]


def ground(context: RetrievalContext) -> GroundedContext:
    """Transforms the raw ``RetrievalContext`` (#22) into the validated context (#23).

    For each POI it builds the ontological risks (tag ``ONTOLOGIA``) with the
    per-hazard SPARQL citation; the ``confidence`` of ALL the risks of the POI is
    ``verificato`` if the POI has an OSM name, ``da_confermare`` if it is an
    anonymous feature (:func:`confidence_from_poi_name`, #202). POIs outside the
    ontology (``GenericUrbanPOI``/empty profile) stay with ``risks=[]``. The
    ``confidence_summary`` counts the real levels.
    """
    # The properties are those of the active ontology (#434), not fixed TERMINUS:
    # a citation with a property that does not exist in its graph is not anchored.
    ontology = current_ontology()
    props_hazard = (ontology.hazard,)
    props_critical_event = (ontology.critical_event,)
    props_vulnerability = ontology.vulnerability
    props_stakeholder = (ontology.performer,)
    validated: list[ValidatedRisk] = []
    n_verified = 0
    n_to_confirm = 0
    for poi in context["pois"]:
        profile = context["profiles"][poi["terminus_class"]]
        confidence = confidence_from_poi_name(poi["name"])
        risks: list[GroundedRisk] = [
            {
                "hazard": hazard,
                "tag": _TAG,
                "confidence": confidence,
                "source": _source_for(profile, props_hazard, hazard),
            }
            for hazard in profile.hazards
        ]
        if confidence == _CONFIDENCE_NAMED:
            n_verified += len(risks)
        else:
            n_to_confirm += len(risks)
        validated.append(
            {
                "poi_id": poi["id"],
                "poi": poi["name"],
                "terminus_class": poi["terminus_class"],
                "risks": risks,
                "critical_events": _entities(
                    profile, props_critical_event, profile.critical_events
                ),
                "vulnerabilities": _entities(
                    profile, props_vulnerability, profile.vulnerabilities
                ),
                "stakeholders": _entities(
                    profile, props_stakeholder, profile.stakeholders
                ),
                "sparql_path": risks[0]["source"] if risks else None,
                "istat": istat_for_poi(poi["lat"], poi["lon"], profile.hazards),
            }
        )
    return {
        "zona": context["zona"],
        "validated_risks": validated,
        "confidence_summary": {
            "verificato": n_verified,
            "da_confermare": n_to_confirm,
        },
    }
