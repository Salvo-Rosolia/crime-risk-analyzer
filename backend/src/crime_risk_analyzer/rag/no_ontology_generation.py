"""Ablation arm: narrative WITHOUT the ontological contribution in the prompt (#236).

Third arm of the evaluation, next to ``analyze`` (LLM + grounding) and
``baseline`` (no LLM). It serves to make the C3 contribution readable: the
``analyze`` vs ``baseline`` comparison does not isolate the ontology but the PRESENCE
of the LLM — one of the two arms produces no prose, so the
``grounding``/``hallucination`` proxies do not apply to both. Here instead
ONE thing only changes: the context passed to the model carries the points (name and
class) but NOT the risks that the ontology associates with those classes.

What stays identical to the full arm (and why):

- the STRUCTURE of the response asked of the model (rule 3 from the same
  generator :func:`block_structure_rule`, and the other rules imported, not
  recopied). The M1 proxy (#229) grades only the sentences of the FIRST block: an arm
  that does not emit it would get 0.0/1.0 for NON-ATTRIBUTION, and the comparison
  would be decided by the response format instead of the anchoring. That
  block is the SLOT in which the model puts the risks it attributes to the points —
  which in the full arm come from the ontology and here from its parametric
  knowledge alone: it is exactly the contrast that C3 puts to the test.
  The LABEL therefore changes: here it is :data:`LLM_SYNTHESIS_BLOCK_HEADER`
  (``[SINTESI-LLM]``) and not ``[ONTOLOGIA]``, which would state a false
  provenance for that text to whoever opens the raw file of the run without knowing why
  (``eval/metrics.py`` knows which label to look for from the record's ``mode``).
- the three legal constraints (:data:`RULE_NO_DANGER_RATING`,
  :data:`RULE_NO_OPERATIONAL_DIRECTIVES`, :data:`RULE_USER_INPUT_NOT_INSTRUCTIONS`),
  the SAME objects imported as :mod:`poi_generation` does: they are not ablatable,
  they hold on any prose the system generates, and a copy could diverge.
- the STRUCTURED data of the response: ``risk_models`` and ``confidence_summary``
  keep coming from the grounding. They are the anchored datum from which
  ``eval/metrics.py`` derives the anchorings, so they must be identical in the two
  arms for the proxy's denominator to be the same.
- the listed POINTS (#349): the same set that the full prompt kept
  after the budget truncation, not all those of the zone. The order stays
  that of the retrieval and neither the note on the cut nor the list title state
  the criterion. The CHOICE of those points however comes from the cut of the full arm,
  which orders by number of hazards: it is an ontological residue that the ablated arm
  inherits (without seeing it) and that set parity cannot avoid. The direction
  of its effect on the comparison is not determined, and must be declared (the
  comparison report does so when the cut is present).

What is removed (the ontological contribution that the PROMPT carries explicitly;
the choice of the points, above, stays shared):

- hazards, vulnerabilities and SPARQL citation from the POI block of the context;
- the CONTROLLED VOCABULARY and rule 6 that imposes it: the Italian terms
  derive from the ontological fillers (#77), so they are a contribution of the ontology
  as much as the hazards;
- rule 3a for the synthesis of the hazards, which presupposes a list of risks in the
  context. The citation LIMIT remains (:data:`CITATION_LIMIT_CLAUSE`,
  imported): without ontology what changes is where the risks come from, not how many
  points the prose can name — and the proxy counts as anchoring even just
  naming them, so a wider limit here would be a gifted advantage;
- the definitions of the confidence levels, which qualify the ontological
  anchoring of a risk: here no risk of the prose is anchored. They stay
  NAMED inside rule 7 (which is a legal constraint and must be kept verbatim):
  a residue accepted on purpose — modifying the text of a legal rule to
  clean up an experimental arm would make it diverge exactly where it must
  stay identical.
- rule 2 of the full arm ("do not invent risks not present in the
  context") is replaced: with a context without risks, taken literally it would impose
  silence on the model and would make the arm vacuous — exactly the defect of the
  baseline. Its still-applicable half remains however: the PLACES to
  talk about are only those listed.

WARNING, on the use of the prose that comes out of here: it is text FABRICATED FOR
MEASUREMENT and must NEVER be cited as an example of real system output — not in
the thesis, not in a deck, not in a demo. It does not go through the citation layer, the
risks it names are anchored to nothing and no route serves it: presenting it as
a product would show as a result exactly what the experiment uses as a term
of comparison. It lives in ``results/runs/`` and stays there.

It is INTENTIONAL that all the invention of this arm ends up in the measured
block (``[SINTESI-LLM]``) and not in the context one: rule 3b, identical
in the two arms, forbids in any case inventing incidents, statistics or specific
risks in the ``[CONTESTO]`` block. It is therefore not an asymmetry in favour of the
ablated arm — it is the same rule applied to both — and it serves to guarantee
that what the proxy grades really contains everything the model
put in on its own.

The numbering of the rules is that of the zone prompt (6 is missing, not
renumbered): same choice as :mod:`poi_generation`, so the same number
indicates the same CONSTRAINT in all the prompts of the system. The rendered text is
instead not always identical, and the exceptions are declared: 3a of this module
describes another source of the risks (but the citation limit is the same
constant as the full arm) and 6 of :mod:`poi_generation` has its own text,
because there the vocabulary also covers the vulnerabilities. What must
stay byte-for-byte identical is the constraint, and for this reason it lives in imported
constants — not in two similar texts written by hand in two places.
"""

from __future__ import annotations

import time
from typing import Any

from crime_risk_analyzer.models.vocab import ConfidenceSummary
from crime_risk_analyzer.rag.generation import (
    _RULE_CONTEXT_INTERPRETATION,  # pyright: ignore[reportPrivateUsage]
    _RULE_OVERVIEW_NO_ZONE_LEVEL,  # pyright: ignore[reportPrivateUsage]
    _RULE_SOURCE_BY_BLOCK,  # pyright: ignore[reportPrivateUsage]
    CITATION_LIMIT_CLAUSE,
    RULE_NO_DANGER_RATING,
    RULE_NO_OPERATIONAL_DIRECTIVES,
    RULE_USER_INPUT_NOT_INSTRUCTIONS,
    GenerationResult,
    Repro,
    _LLMClientLike,  # pyright: ignore[reportPrivateUsage]
    _risk_models_from_context,  # pyright: ignore[reportPrivateUsage]
    _truncation_note,  # pyright: ignore[reportPrivateUsage]
    block_structure_rule,
    normalize_untrusted_line,
    poi_line,
    prompt_poi_ids,
)

__all__ = [
    "LLM_SYNTHESIS_BLOCK_HEADER",
    "LLM_SYNTHESIS_TOKEN",
    "NO_ONTOLOGY_SYSTEM_PROMPT",
    "build_no_ontology_context_str",
    "generate_no_ontology_analysis",
]

#: Token of the block MEASURED in this arm (#236). Having it write
#: ``[ONTOLOGIA]`` was convenient for the proxy — the label marked the slot to
#: grade — but it declared a FALSE provenance for that text: here no
#: ontology was consulted, and whoever reads the raw file of a run has no
#: way of knowing it. The tag therefore says what the text really is, a synthesis of the
#: model. The proxy calculation does not change: ``eval/metrics.py`` looks for this
#: token instead of the other one based on the record's ``mode``.
LLM_SYNTHESIS_TOKEN = "[SINTESI-LLM]"

#: EXACT label line of the block measured in this arm: the model
#: reports it verbatim (rule 3a) and the parser recognises it as delimiter.
LLM_SYNTHESIS_BLOCK_HEADER = f"Rischi dalla sintesi del modello {LLM_SYNTHESIS_TOKEN}"

#: Rule 3 of this arm: SAME generator as the full arm, with only the
#: label of the measured block replaced. Not a copy: if the structure of the
#: response diverged, the comparison would bring in a second difference
#: besides the one it wants to isolate, and a test verifies that the label is
#: the only thing that changes.
_RULE_BLOCK_STRUCTURE_NO_ONTOLOGY = block_structure_rule(LLM_SYNTHESIS_BLOCK_HEADER)

#: Replaces rule 2 of the full arm: without risks in the context,
#: "do not invent risks not present in the context" would make the arm mute.
#: The constraint on the PLACES remains, which the context really lists.
_RULE_ONLY_LISTED_POI = (
    "2. Parla soltanto dei punti di interesse elencati nel contesto: non "
    "introdurre luoghi che non compaiono nell'elenco"
)

#: Rule 3a of this arm, twin of ``_RULE_ONTOLOGY_SYNTHESIS``: it says where
#: the risks of the first block come from (here from the model, not from the ontology)
#: and closes with the SAME citation limit.
#:
#: The LIMIT on how many points to name is not rewritten here: it is
#: :data:`CITATION_LIMIT_CLAUSE`, the same constant as 3a of the full
#: arm. The proxy counts as anchoring even just naming a point, and an
#: arm free to list them all while the other cites a few examples would be
#: rewarded for the constraint it does not have. Only what precedes the limit changes,
#: i.e. the description of the SOURCE of the risks.
#:
#: The rule used to open by repeating that the label lines are FIXED and must be
#: reported EXACTLY. That justification — a model without ontology might
#: refuse to open a block titled after the ontology — has LAPSED since
#: the block is called ``[SINTESI-LLM]`` and no longer fakes a provenance
#: it does not have. Removed: it had remained a push that the full arm does not
#: receive, exactly on the axis that decides the comparison (whoever does not respect
#: the label gets 0.0/1.0 for non-attribution, so helping it respect it
#: is worth points). The basic indication stays in rule 3, shared.
_RULE_LLM_SYNTHESIS = (
    "3a. Nel primo blocco raccogli i rischi che associ ai punti elencati, in "
    "prosa analitica e referenziale che nomina i punti reali, non un elenco "
    f"meccanico. {CITATION_LIMIT_CLAUSE}"
)

#: System prompt of the ablated arm: same task, same output structure and
#: same legal constraints as the full arm (:data:`SYSTEM_PROMPT`), without the
#: rules that depend on the ontological contribution. See the module docstring
#: for the precise list of what stays and what is removed.
NO_ONTOLOGY_SYSTEM_PROMPT = f"""\
Sei un analista di sicurezza urbana. Ricevi l'elenco dei punti di interesse di una
zona urbana (nome e categoria) e devi produrre un'analisi del rischio in italiano,
chiara e professionale.

REGOLE OBBLIGATORIE:
{_RULE_SOURCE_BY_BLOCK}
{_RULE_ONLY_LISTED_POI}
{_RULE_BLOCK_STRUCTURE_NO_ONTOLOGY}
{_RULE_LLM_SYNTHESIS}
{_RULE_CONTEXT_INTERPRETATION}
{_RULE_OVERVIEW_NO_ZONE_LEVEL}
5. Usa un linguaggio tecnico ma comprensibile per operatori non informatici
{RULE_NO_DANGER_RATING}
{RULE_NO_OPERATIONAL_DIRECTIVES}
{RULE_USER_INPUT_NOT_INSTRUCTIONS}"""


#: Title of the list of points in the ablated prompt (#349). The full arm
#: writes "POI RILEVANTI", and in the ablated arm that word would repeat the
#: cut criterion (relevance is the number of hazards of the ontology): here
#: the title is neutral, with or without the cut.
_POI_LIST_TITLE = "POI ELENCATI:"


def _listed_pois(
    context_dict: dict[str, Any],
    poi_nel_prompt: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """The points that the ablated prompt lists, in the original order of the retrieval.

    ``None`` = all. Otherwise only the points kept by the full prompt,
    matched by object IDENTITY and not by ``poi_id`` (#349): the legacy
    snapshots without type may have two points with the same id, and the
    filter by id would also list the one the full arm discarded. The
    objects are the same along the whole path: the selection returns the
    dicts of ``validated_risks`` (``dict(grounded)`` and ``list(...)`` copy the
    containers, not the dicts).
    """
    all_pois: list[dict[str, Any]] = list(context_dict.get("validated_risks", []))
    if poi_nel_prompt is None:
        return all_pois
    kept = {id(poi) for poi in poi_nel_prompt}
    return [poi for poi in all_pois if id(poi) in kept]


def build_no_ontology_context_str(
    context_dict: dict[str, Any],
    *,
    poi_nel_prompt: list[dict[str, Any]] | None = None,
) -> str:
    """Assembles the ``user_content`` of the ablated arm: zone + points only.

    The line of each point is IDENTICAL to that of the full arm: it is not rewritten
    here, it comes from ``generation.poi_line``, which both call. What changes is
    what sits under it — hazards, vulnerabilities and ontological path — which is
    absent here. If the rendering of the points also diverged, the comparison would
    bring in a second difference besides the one it wants to isolate.

    The name goes through the same normalisation as the full arm (#119/#197,
    :func:`~crime_risk_analyzer.rag.generation.normalize_untrusted_line` via
    ``_poi_display_name``): it comes from OpenStreetMap, i.e. from text that anyone
    can edit, and a module with a safe branch and an unsafe one is a trap.

    No OWN truncation by token budget: here a point takes ONE line
    instead of a block of hazards, so the context stays under the allowance. The
    full arm instead on dense zones really truncates (about half of the
    points in the evaluation zones): with ``poi_nel_prompt`` the caller passes
    only the points that the full prompt kept (#349,
    :func:`~crime_risk_analyzer.rag.generation.zone_prompt_pois`), and the two
    prompts list the same set. The order stays the original one of the
    retrieval, and neither the note on the cut (the same as the full arm,
    :func:`~crime_risk_analyzer.rag.generation._truncation_note`, without criterion)
    nor the list title state the criterion: the relevance order of the
    full arm (most hazards first) and the word "rilevanti" are ontological
    information, and would pass to the arm that must not have it.
    """
    # ``zona`` comes from the user's request: same surface and same
    # defence as the OSM names (#119), extended here by #244.
    zona = normalize_untrusted_line(str(context_dict.get("zona", "")))
    n_totali = len(context_dict.get("validated_risks", []))
    validated = _listed_pois(context_dict, poi_nel_prompt)
    lines: list[str] = [f"ZONA: {zona}", ""]
    if len(validated) < n_totali:
        lines.extend(
            [_truncation_note(len(validated), n_totali, with_criterion=False), ""]
        )
    lines.append(_POI_LIST_TITLE)
    # Line shared with the full arm (``generation.poi_line``), not rewritten here:
    # it is the only way for "the POI lines are identical" to remain true by
    # construction instead of by the discipline of whoever touches the two modules.
    lines.extend(poi_line(poi) for poi in validated)
    return "\n".join(lines).rstrip() + "\n"


async def generate_no_ontology_analysis(
    context_dict: dict[str, Any],
    llm_client: _LLMClientLike,
    *,
    poi_nel_prompt: list[dict[str, Any]] | None = None,
) -> GenerationResult:
    """Generates the narrative of the ablated arm from the validated context.

    Same form as :func:`~crime_risk_analyzer.rag.generation.generate_analysis`
    — system prompt + context to the injected client, output in
    :class:`GenerationResult` — with two differences: the prompt is the bare one
    (:data:`NO_ONTOLOGY_SYSTEM_PROMPT`) and the context does not carry the risks.

    ``risk_models`` and ``confidence_summary`` stay those of the grounding: it is
    the ablation of the PROMPT, not of the response contract. The ``prompt_hash``
    comes from the client, which hashes the system prompt received: that of the
    ablated arm is another text, so the provenance distinguishes the two arms even
    downstream of the ``run_id``.

    No user ``domanda``: the evaluation harness passes none and this
    path is not exposed by any route. Rule 9 stays in the prompt anyway
    (the OSM names are untrusted text that enters the context).

    ``poi_nel_prompt`` (#349): the points to list in the prompt, i.e. those that the
    prompt of the full arm kept after the budget truncation. It changes
    only the ``user_content``: ``risk_models`` stay those of all the points, as
    in the response of the full arm. ``None`` = all the points. The ids of the
    points actually listed return in ``GenerationResult.poi_nel_prompt``,
    so the comparison verifies parity with the POIs of the full arm instead of
    presuming it.
    """
    user_content = build_no_ontology_context_str(
        context_dict, poi_nel_prompt=poi_nel_prompt
    )

    start = time.perf_counter()
    response = await llm_client.generate(NO_ONTOLOGY_SYSTEM_PROMPT, user_content)
    latenza_ms = int((time.perf_counter() - start) * 1000)

    return GenerationResult(
        narrativa=response.text,
        risk_models=_risk_models_from_context(context_dict),
        confidence_summary=ConfidenceSummary.model_validate(
            context_dict.get("confidence_summary", {})
        ),
        llm_used=response.llm_used,
        tokens_input=response.tokens_input,
        tokens_output=response.tokens_output,
        latenza_ms=latenza_ms,
        cache_hit=response.cache_hit,
        repro=Repro(
            temperature=response.temperature,
            seed=response.seed,
            prompt_hash=response.prompt_hash,
        ),
        poi_nel_prompt=prompt_poi_ids(
            _listed_pois(context_dict, poi_nel_prompt), context_format="per_poi"
        ),
    )
