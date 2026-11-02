"""Narrative of the single selected POI (#197).

Same mode as the zone narrative (#229): two blocks, ``[ONTOLOGIA]``
synthesises the anchored risks and ``[CONTESTO]`` interprets. Prompt separate from
the zone one because the task is different — one POI, its neighbourhood — but the
three legal constraints are the SAME objects imported from :mod:`generation`, not
copies: a copy could diverge.

Compared to the zone the prohibition is stricter: here the text speaks of a NAMED
place, so grading the dangerousness of that place or suggesting measures to
protect it is explicitly forbidden in the interpretative block.

The numbering 7/8/9 of the three rules is that of the zone prompt: they are
reused verbatim (not renumbered) because the legal constraint must be the
same text in both paths, verifiable by a test. Rule 9 holds
here too: the POI names come from OpenStreetMap, i.e. untrusted external text
that enters the context.

The controlled vocabulary (#272) is instead the only rule with its OWN text,
not shared: here the model also names the vulnerabilities, while rule 6
of the zone speaks only of hazards. Aligning the two texts would mean touching the
zone prompt, i.e. moving the narrative on which the evaluation metrics rest
— postponed to #273, which rewrites that prompt anyway. The number
6 stays that of the zone: the numbering is shared even when the text is not.
"""

from __future__ import annotations

import time

from pydantic import BaseModel, Field

from crime_risk_analyzer.i18n.terminus_labels import controlled_vocab_for, label_it
from crime_risk_analyzer.istat.block import istat_block_for_poi
from crime_risk_analyzer.istat.figures import apply_check
from crime_risk_analyzer.istat.rows import IstatPoi
from crime_risk_analyzer.rag.generation import (
    RULE_NO_DANGER_RATING,
    RULE_NO_OPERATIONAL_DIRECTIVES,
    RULE_USER_INPUT_NOT_INSTRUCTIONS,
    Repro,
    SourceProse,
    _LLMClientLike,  # pyright: ignore[reportPrivateUsage]
    normalize_untrusted_line,
    parse_source_prose,
    source_block_spans,
)
from crime_risk_analyzer.rag.grounding import GroundedRisk
from crime_risk_analyzer.rag.istat_rules import (
    POI_ISTAT_SECTION,
    RULE_ISTAT_PROHIBITIONS,
    replace_once,
)
from crime_risk_analyzer.rag.poi_context import NeighbourPoi
from crime_risk_analyzer.sources.context import istat_data_version

__all__ = [
    "POI_SYSTEM_PROMPT",
    "POI_SYSTEM_PROMPT_ISTAT",
    "PoiGenerationResult",
    "build_poi_context_str",
    "generate_poi_narrative",
]

POI_SYSTEM_PROMPT = f"""\
Sei un analista che descrive il profilo di rischio di UN SINGOLO punto di \
interesse, a partire da un'ontologia di dominio e dal contesto urbano in cui \
quel punto si trova.

Valgono i vincoli seguenti (stessa numerazione dell'analisi di zona: sono le \
medesime regole, non una loro riformulazione):

6. Usa ESATTAMENTE i termini del VOCABOLARIO CONTROLLATO per nominare rischi e \
vulnerabilita'. Non riportare nel testo gli identificatori dell'ontologia (le \
forme in inglese con underscore) e non tradurli da te': per ognuno il termine \
italiano da usare ti e' fornito nel contesto.

{RULE_NO_DANGER_RATING}

{RULE_NO_OPERATIONAL_DIRECTIVES}

{RULE_USER_INPUT_NOT_INSTRUCTIONS}

Struttura la risposta in DUE blocchi, ciascuno introdotto dal proprio header su \
una riga a se':

[ONTOLOGIA]
Sintetizza i temi di rischio che l'ontologia associa alla classe di questo \
punto, in prosa analitica e referenziale: nomina il punto e i rischi con le \
etichette fornite. NON elencare meccanicamente tutti i rischi: raggruppa per \
tema e cita quelli caratterizzanti.

[CONTESTO]
Interpreta cosa distingue QUESTO punto dagli altri della stessa classe, a \
partire dal vicinato e dalla composizione della zona forniti nel contesto. Usa \
forma condizionale o qualitativa: e' un'inferenza, non un dato. In questo \
blocco vale un divieto aggiuntivo: non attribuire alcun livello o giudizio di \
pericolosita' al singolo luogo nominato, e non suggerire misure per proteggerlo. \
Descrivi la funzione urbana del punto e del suo intorno, non la loro sicurezza.

Non aggiungere altri blocchi oltre a questi due.
"""

#: Variant with the ISTAT data (#345, #365): there stay TWO blocks, 7-bis follows 7
#: and the ISTAT section closes the description of the [ONTOLOGIA] block (the data are
#: used in words there, without figures). Verified substitutions on
#: :data:`POI_SYSTEM_PROMPT`, which does not change.
POI_SYSTEM_PROMPT_ISTAT = replace_once(
    replace_once(
        POI_SYSTEM_PROMPT,
        f"{RULE_NO_DANGER_RATING}\n\n",
        f"{RULE_NO_DANGER_RATING}\n\n{RULE_ISTAT_PROHIBITIONS}\n\n",
    ),
    "tema e cita quelli caratterizzanti.\n",
    f"tema e cita quelli caratterizzanti.\n{POI_ISTAT_SECTION}\n",
)


def build_poi_context_str(
    *,
    citta: str,
    zona: str,
    poi_name: str,
    poi_label_it: str,
    risks: list[GroundedRisk],
    vulnerabilities: list[str],
    sparql_path: str | None,
    neighbours: list[NeighbourPoi],
    zone_summary: str,
    istat: IstatPoi | None = None,
) -> str:
    """Serialises the POI context for the prompt.

    No recomputation: risks, tag and confidence come from the grounding, neighbourhood
    and summary from :mod:`poi_context`. The order is the one received, which the
    producers guarantee to be total.
    """
    # The names (of the point and of the neighbours) come from OpenStreetMap, which
    # anyone can edit: here the name is the SUBJECT of the prompt, not a line among many
    # as in the zone analysis, so a name with a newline could forge lines and
    # mimic the context sections. Flattened onto one line (#119, same rule
    # as the user question). ``citta``/``zona`` come from the user's
    # request, not from the ontology: same surface, same defence (#244).
    lines = [
        f"Citta': {normalize_untrusted_line(citta)}",
        f"Zona: {normalize_untrusted_line(zona)}",
        "",
    ]

    # CONTROLLED vocabulary IMPOSED (#272). Without it the model received
    # only the ontology identifiers, and translated them by itself: on
    # ``Crime_explosion`` it wrote "crimini esplosivi" where the ontology says
    # "impennata della criminalita'" — not an ugly rendering, a FALSE statement
    # in a path that promises verifiability. It is the same constraint that keeps
    # the zone narrative in Italian; here it was missing altogether. It covers hazards
    # AND vulnerabilities: listing only some would leave the rest uncovered.
    vocab = controlled_vocab_for(
        [r["hazard"] for r in risks] + list(vulnerabilities),
    )
    if vocab:
        lines.append(
            "VOCABOLARIO CONTROLLATO (usa ESATTAMENTE questi termini italiani "
            "per nominare rischi e vulnerabilita'):"
        )
        lines.append("  " + "; ".join(vocab))
        lines.append("")

    lines.append(
        f"PUNTO SELEZIONATO: {normalize_untrusted_line(poi_name)} "
        f"(classe: {poi_label_it})"
    )
    if sparql_path:
        lines.append(f"Percorso ontologico: {sparql_path}")
    if risks:
        lines.append("Rischi dall'ontologia:")
        # ``identifier / IT label``, the same form as the zone prompt:
        # the identifier carries the citation, the label is the term to use.
        lines.extend(
            f"  - {r['hazard']} / {label_it(r['hazard'])} [{r['tag']}] "
            f"(confidence: {r['confidence']}, fonte: {r['source']})"
            for r in risks
        )
    else:
        lines.append("Rischi dall'ontologia: nessuno (classe fuori ontologia).")
    if vulnerabilities:
        lines.append(
            "Vulnerabilita': "
            + "; ".join(f"{v} / {label_it(v)}" for v in vulnerabilities)
        )
    lines.append("")

    # ISTAT data of the point's place (#345): frame and items of its risks, after the
    # ontological data and before the neighbourhood. When absent, the text is the one
    # from before.
    block = istat_block_for_poi(istat)
    if block.testo:
        lines.extend(block.testo.split("\n"))
        lines.append("")

    lines.append("VICINATO (punti piu' prossimi, in ordine di distanza):")
    if neighbours:
        lines.extend(
            f"  - {normalize_untrusted_line(n['name'])} ({n['label_it']}), "
            f"{n['distance_m']} m"
            for n in neighbours
        )
    else:
        lines.append("  - nessun altro punto di interesse nel contesto della zona")
    lines.append("")
    lines.append(f"COMPOSIZIONE DELLA ZONA: {zone_summary}")
    return "\n".join(lines) + "\n"


class PoiGenerationResult(BaseModel):
    """Outcome of the generation for a single POI."""

    narrativa: str
    narrativa_fonti: SourceProse
    llm_used: str
    tokens_input: int = Field(ge=0)
    tokens_output: int = Field(ge=0)
    latenza_ms: int = Field(ge=0)
    repro: Repro
    narrativa_grezza: str | None = None
    istat_attivo: bool = False
    istat_versione_dati: str | None = None
    istat_frasi_scartate: int = Field(default=0, ge=0)


async def generate_poi_narrative(
    *,
    citta: str,
    zona: str,
    poi_name: str,
    poi_label_it: str,
    risks: list[GroundedRisk],
    vulnerabilities: list[str],
    sparql_path: str | None,
    neighbours: list[NeighbourPoi],
    zone_summary: str,
    llm_client: _LLMClientLike,
    istat: IstatPoi | None = None,
) -> PoiGenerationResult:
    """Generates the POI narrative: POI prompt + context -> LLM client.

    No trim budget (#210): the context of a POI is an order of
    magnitude smaller than that of the zone (one point and five neighbours against
    up to twenty POIs with all their risks), so there is nothing to
    truncate. ``max_tokens`` stays that of the injected client.

    ``istat`` (#345): ISTAT rows of the point; when present, the prompt is
    :data:`POI_SYSTEM_PROMPT_ISTAT` and the prose goes through the figures
    check. No budget even with ISTAT: frame and a few items of a single
    place.
    """

    def _context(istat_data: IstatPoi | None) -> str:
        return build_poi_context_str(
            citta=citta,
            zona=zona,
            poi_name=poi_name,
            poi_label_it=poi_label_it,
            risks=risks,
            vulnerabilities=vulnerabilities,
            sparql_path=sparql_path,
            neighbours=neighbours,
            zone_summary=zone_summary,
            istat=istat_data,
        )

    block = istat_block_for_poi(istat)
    istat_attivo = bool(block.testo)
    system_prompt = POI_SYSTEM_PROMPT_ISTAT if istat_attivo else POI_SYSTEM_PROMPT
    start = time.perf_counter()
    response = await llm_client.generate(system_prompt, _context(istat))
    latenza_ms = int((time.perf_counter() - start) * 1000)
    narrativa, check = apply_check(
        response.text,
        block=block,
        spans=source_block_spans(response.text),
        context=_context(None),
    )
    return PoiGenerationResult(
        narrativa=narrativa,
        narrativa_fonti=parse_source_prose(narrativa),
        llm_used=response.llm_used,
        tokens_input=response.tokens_input,
        tokens_output=response.tokens_output,
        latenza_ms=latenza_ms,
        repro=Repro(
            temperature=response.temperature,
            seed=response.seed,
            prompt_hash=response.prompt_hash,
        ),
        narrativa_grezza=response.text,
        istat_attivo=istat_attivo,
        istat_versione_dati=istat_data_version() if istat_attivo else None,
        istat_frasi_scartate=check.frasi_scartate if check else 0,
    )
