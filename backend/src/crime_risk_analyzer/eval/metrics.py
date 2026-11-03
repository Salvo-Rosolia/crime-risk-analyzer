"""Deterministic evaluation metrics (#34).

Structural metrics on the AnalyzeResponse. ``grounding``/``hallucination`` are
textual PROXIES (see the EN/IT caveat in the spec): they measure whether the risk
assertions cite the anchored data (names of the zone's POIs, #264).

**M1 semantics (#229, ``METRICS_VERSION == 3`` since #264).** The proxy grades ONLY the
assertions of the FIRST block of the narrative, the one in which the model attributes
risks to the points:
in the product arm it is ``[ONTOLOGIA]``, the only layer with structured backing from
grounding (``grounding.py`` emits only the ``ONTOLOGIA`` tag); in the ablation arm
(#236) it is ``[SINTESI-LLM]``, which has no backing by construction -- and that is the
point of the experiment, to measure how anchored that block stays when the anchored data
do not reach the prompt. The summary ``overview`` and the
``[CONTESTO]`` block are the LLM's INTERPRETATION (general knowledge, not an
ontological datum): their quality/fabrication is NOT gradable by a deterministic
anchoring proxy and today has no dedicated measure (see below), besides being curbed
upstream by the prompt (rule 2 + ``[CONTESTO]`` "without inventing"). The attribution of
the source is per BLOCK (header #196), not per inline tag: the v1 proxy (pre-#229)
looked for ``[TAG]`` in the single sentence and, with the tags now only in the headers,
was mis-calibrated on real output -- the reason for the change (not a regression).

**What is NOT validated.** The agreement between this proxy and an overall human
judgement is not measured anywhere: the per-run correlation (#109) was REMOVED with #152
and not replaced by a direct equivalent. ``eval/gold.py`` validates at another grain --
the source of the single risk cited in the measured block
(:func:`~crime_risk_analyzer.eval.gold.collect_kept_risks`) -- which is a
different question. A strong claim on these numbers therefore remains without a human
anchoring.

**What still counts as a sentence (#264).** A sentence is anchored only if it names a
POI of the zone. Hazards (identifier and EN/IT labels) are not enough: rule 6 of the
prompt obliges the model to use those words, so a generic sentence like "the risk of
theft is high" always contains them and would pass as anchored without being tied to any
point. Without POIs with a name there is nothing that can anchor a sentence: VACUOUS
branch. Hazards stay anchors for the exclusion of ISTAT sentences (:func:`_assertions`)
and for the decomposition of :func:`risk_anchoring`.

**How the arm enters the computation (#236).** From the ``mode`` of the run only the
label row to look for is derived (:data:`_MEASURED_TOKEN_BY_MODE`); the formula does not
change, and two identical narratives under the two labels get the same score --
otherwise the comparison between arms would measure the label instead of the anchoring.

**With ISTAT data in the prompt (#345, #369).** The text of the model is graded before
the filter, without the sentences that speak of the ISTAT datum and name neither a POI
nor a risk (:func:`m1_excluded_sentences`). The sentences are the same as M1's: the
ISTAT check splits them with the same splitter
(:func:`~crime_risk_analyzer.istat.figures.split_sentences_m1`). The anchored sentences
are measured as in every arm, even if they cite ISTAT.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from crime_risk_analyzer.eval.pricing import cost_usd
from crime_risk_analyzer.eval.schema import Metrics, Mode
from crime_risk_analyzer.istat.figures import measured_block, split_sentences_m1
from crime_risk_analyzer.orchestrator import AnalyzeResponse
from crime_risk_analyzer.rag.generation import (
    ONTOLOGY_TOKEN,
    RiskModel,
    parse_source_prose,
    source_block_spans,
)
from crime_risk_analyzer.rag.no_ontology_generation import LLM_SYNTHESIS_TOKEN

#: Generation of the SEMANTICS of the grounding/hallucination proxy (#229). ``1`` was
#: the inline-tag proxy (pre-#229): it looked for ``[TAG]`` in the single sentence, but
#: the block structure #196 puts the tag ONLY in the header -> on real output the v1
#: proxy was mis-calibrated. ``2`` is block-aware M1: it grades ONLY the assertions of
#: the [ONTOLOGIA] block (the only layer with structured backing from grounding),
#: delegating the [CONTESTO] interpretation to the human gold (#152). It exposes the
#: version so that a comparison (compare.py/winner.py #157) does not silently mix metric
#: generations: the pre-#229 values on real output are not comparable with these.
#: ``3`` (#264): anchored only the sentence that names a POI of the zone; with ``2`` a
#: hazard was enough, a word that rule 6 of the prompt imposes, so the ``2`` values are
#: inflated and not comparable with the ``3`` ones.
METRICS_VERSION = 3

#: Label row of the block that the proxy grades, PER ARM (#236). The arm
#: without ontology labels its block for what it is -- a synthesis of the
#: model, not an ontological datum -- so looking in every arm for the same
#: string would measure it on a block it does not emit: 0.0/1.0 by NON-ATTRIBUTION
#: on every run, and the C3 comparison decided by the name of the label. ONLY the
#: searched substring changes: the grounding/hallucination formula is the same.
#: ``baseline`` generates no prose (vacuous branch of :func:`_grade`) but stays mapped:
#: the exhaustive coverage of the ``Mode``s is verified by a test, so a new
#: arm cannot enter without declaring what it is measured on.
_MEASURED_TOKEN_BY_MODE: dict[Mode, str] = {
    "analyze": ONTOLOGY_TOKEN,
    "baseline": ONTOLOGY_TOKEN,
    "no_ontology_prompt": LLM_SYNTHESIS_TOKEN,
}

#: Arm assumed when the caller does not declare it: the historical one. It keeps
#: unchanged every measurement point written before #236.
_DEFAULT_MODE: Mode = "analyze"


def _non_empty_lower(tokens: Iterable[str]) -> set[str]:
    """Lowercase tokens without the empty/whitespace ones.

    An OSM POI without a `name` tag arrives with name="" and, since `"" in s` is always
    true, it would make EVERY sentence "anchored", neutralising the discrimination
    (it would reopen cat.2 and defeat the exclusion of the filler). See review
    #163 I1.
    """
    return {t.lower() for t in tokens if t.strip()}


def _poi_anchors(poi_names: Iterable[str]) -> set[str]:
    """POI anchors: the names of the points, lowercase, without the empty names."""
    return _non_empty_lower(poi_names)


def _hazard_anchors(risk_models: Iterable[RiskModel]) -> set[str]:
    """Hazard anchors: identifier + EN/IT labels (#77), lowercase."""
    tokens: list[str] = []
    for model in risk_models:
        for risk in model.risks:
            tokens.append(risk.hazard)
            if risk.hazard_label_it:
                tokens.append(risk.hazard_label_it)
            if risk.hazard_label_en:
                tokens.append(risk.hazard_label_en)
    return _non_empty_lower(tokens)


def _anchors(resp: AnalyzeResponse) -> set[str]:
    """Anchored tokens: POI names + hazards (identifier + EN/IT labels), lowercase.

    Includes the controlled Italian labels (#77) so the match holds when the
    narrative cites the hazard in Italian (closes the EN/IT caveat of the metrics).
    Empty tokens (e.g. POI without a name) are discarded: they must not anchor
    everything. Union of the two families that :func:`risk_anchoring` keeps separate
    (#359).
    """
    return _poi_anchors(p.name for p in resp.poi) | _hazard_anchors(resp.risk_models)


def hazards_cited_in(narrativa: str, mode: Mode) -> str:
    """Lowercase text of the measured block: check a hazard/label with `in`.

    Reused by ``eval/gold.py`` (#152, see Task 3 ``collect_kept_risks``): the
    sampler of the per-risk annotation must exclude a hazard
    present in the grounded set (``RunRecord.risk_models``, built BEFORE
    the LLM generation, identical across ``analyze``/``baseline``) but never
    cited in the narrative -- otherwise it would measure the candidate set instead of
    "what the LLM kept", exactly what the spec asks.

    Returns the whole text (not a set of pre-extracted tokens) because the
    caller already holds the candidate hazards to test (from the record's
    ``risk_models``) -- same idea as :func:`_grounded`, but
    on the whole block instead of per sentence. Same block and same
    per-arm substring as :func:`_measured_spans`.
    """
    return parse_source_prose(
        narrativa or "", measured_token=_MEASURED_TOKEN_BY_MODE[mode]
    ).ontologia.lower()


def _measured_spans(narrativa: str, mode: Mode) -> list[tuple[int, int]]:
    """Offsets of the sentences of the measured block of arm ``mode`` (M1, #229).

    The block is that of
    :func:`~crime_risk_analyzer.rag.generation.parse_source_prose` (#196): without
    the header, the ``overview`` and the ``[CONTESTO]`` block, which are interpretation
    (-> human gold). Which label row opens it depends on the arm
    (:data:`_MEASURED_TOKEN_BY_MODE`): ``[ONTOLOGIA]`` where the ontology is really
    there, ``[SINTESI-LLM]`` in the ablated arm (#236). The sentences are split by
    :func:`~crime_risk_analyzer.istat.figures.split_sentences_m1`, the same
    splitter with which the ISTAT check marks its sentences (#369). ``[]`` if the
    block is missing.
    """
    spans = source_block_spans(narrativa, measured_token=_MEASURED_TOKEN_BY_MODE[mode])
    block = measured_block(spans)
    if block is None:
        return []
    return split_sentences_m1(narrativa, block.inizio, block.fine)


def _measured_sentences(narrativa: str | None, mode: Mode) -> list[str]:
    """Sentences of the measured block of arm ``mode``; ``[]`` if the block is
    missing."""
    text = narrativa or ""
    return [text[a:b] for a, b in _measured_spans(text, mode)]


def _names_any(sentence: str, anchors: set[str]) -> bool:
    """True if the sentence names at least one anchor (substring match)."""
    low = sentence.lower()
    return any(a in low for a in anchors)


def _grounded(assertions: list[str], poi: set[str]) -> list[str]:
    """Anchored ontological assertions: they name a POI of the zone (#264)."""
    return [s for s in assertions if _names_any(s, poi)]


def _m1_text(resp: AnalyzeResponse) -> str:
    """Text that M1 grades: the raw model text if there is the ISTAT check.

    The filter removes sentences after generation (#345): measuring the filtered text
    would change the measured assertions. The ISTAT sentences of the check have the
    offsets of the raw text: a response with the check and without the raw text cannot
    be measured and raises :class:`ValueError` (the orchestrator always writes the
    raw text, so it is an error of whoever built the response).
    """
    if resp.controllo_istat is None:
        return resp.narrativa or ""
    if resp.narrativa_grezza is None:
        raise ValueError(
            "risposta con il controllo ISTAT ma senza narrativa_grezza: le frasi "
            "ISTAT di M1 hanno gli offset del grezzo"
        )
    return resp.narrativa_grezza


def _assertions(
    resp: AnalyzeResponse, mode: Mode, anchors: set[str]
) -> tuple[list[str], list[str]]:
    """``(measured, excluded)``: the sentences of the measured block split between the
    M1 assertions and the excluded ISTAT sentences (#369).

    A sentence is excluded if the ISTAT check marks it as a sentence that speaks of the
    datum (``CheckOutcome.frasi_istat_m1``, same sentences and same text as M1) and
    that does not name an anchor: it does not attribute a risk to a point, so
    counting it as not anchored would measure how much the model talks about ISTAT. An
    ISTAT sentence that names a POI or a risk stays an assertion like the others.
    Without an ISTAT check no sentence is excluded.
    """
    text = _m1_text(resp)
    check = resp.controllo_istat
    istat: set[tuple[int, int]] = (
        set(check.frasi_istat_m1) if check is not None else set()
    )
    measured: list[str] = []
    excluded: list[str] = []
    for a, b in _measured_spans(text, mode):
        sentence = text[a:b]
        if (a, b) in istat and not _names_any(sentence, anchors):
            excluded.append(sentence)
        else:
            measured.append(sentence)
    return measured, excluded


def m1_excluded_sentences(
    resp: AnalyzeResponse, *, mode: Mode = _DEFAULT_MODE
) -> list[str] | None:
    """ISTAT sentences excluded from the M1 denominator (#369); ``None`` without ISTAT.

    They are the sentences of the raw text that speak of the ISTAT datum without naming
    a POI nor a risk. The harness saves them in the record, so the measured text can be
    rebuilt from the raw text and the exclusion checked by hand. Limit: a risk
    outside the knowledge base written with the words of the datum ("according to the
    ISTAT data ... kidnappings") ends up here instead of counting as not
    anchored.

    On the VACUOUS branch of :func:`_grade` (empty raw text or no POI with a name) M1
    does not grade anything, so it excludes nothing: ``[]``. Without POIs every ISTAT
    sentence would turn out "not anchored" and the record would declare exclusions from
    a denominator that does not exist.

    Here the hazards stay anchors (#264): an ISTAT sentence that names a risk
    but not a POI stays in the denominator and, for M1, is always not anchored. It is
    the known cost of not making the exclusion depend on the rule that anchors.
    """
    if resp.controllo_istat is None:
        return None
    if _vacuo(resp):
        return []
    return _assertions(resp, mode, _anchors(resp))[1]


def _poi_names(resp: AnalyzeResponse) -> set[str]:
    return _poi_anchors(p.name for p in resp.poi)


def _vacuo(resp: AnalyzeResponse) -> bool:
    """VACUOUS branch of :func:`_grade`: empty raw text or no POI to cite."""
    return not _m1_text(resp).strip() or not _poi_names(resp)


def _grade(resp: AnalyzeResponse, mode: Mode) -> tuple[int, int] | None:
    """``(grounded, assertions)`` of the measured block, or ``None`` if not gradable.

    ``None`` = VACUOUS branch (grounding 1.0 / hallucination 0.0), reserved for the
    cases where the proxy legitimately has nothing to grade:
    - empty narrative (structured fallback: no LLM output to judge);
    - no POI with a name (no datum that can anchor a sentence, #264).

    The case "FULL narrative with data to cite but WITHOUT assertions in the measured
    block" (e.g. a model that does not emit the expected header, or emits it empty) is
    NOT vacuous: it is NON-ATTRIBUTION and counts as ``(0, 1)`` -> grounding 0.0 /
    hallucination 1.0. So a model cannot obtain a perfect score by omitting the header
    (the hallucination axis is the PRIMARY criterion of ``winner.py``, #157): evasion
    loses instead of winning. A run that emits the header of the OTHER arm also falls
    here: the expected label is that of its ``mode``, not any one.

    ``resp.narrativa`` is ``str | None`` since #259 (phase 1: narrative not yet
    generated): a ``None`` narrative is treated as empty, same VACUOUS branch --
    the harness runs only on pipelines that today always produce a string.

    With ISTAT data in the prompt (#345, #369) the raw text is graded (:func:`_m1_text`)
    without the excluded ISTAT sentences (:func:`_assertions`). The VACUOUS branch looks
    at the whole raw text: a narrative made only of ISTAT sentences, without block or
    with the block entirely excluded, attributes no risks to the points and is
    NON-ATTRIBUTION.
    """
    if _vacuo(resp):
        return None
    assertions, _ = _assertions(resp, mode, _anchors(resp))
    if not assertions:
        return (0, 1)
    return (len(_grounded(assertions, _poi_names(resp))), len(assertions))


def grounding(resp: AnalyzeResponse, *, mode: Mode = _DEFAULT_MODE) -> float:
    """Fraction of ASSERTIONS of the measured block anchored to the data [0,1] (M1,
    #229).

    Assertion = sentence of the measured block (:func:`_assertions`); grounded =
    assertion that names a POI of the zone (#264: the hazard alone is not enough).
    Vacuous branches (:func:`_grade` -> ``None``: empty narrative or no POI to cite) ->
    1.0. Full narrative with data to cite but without assertions in the block (header
    absent/empty) -> 0.0 (non-attribution, not "vacuous"). ``overview``/``[CONTESTO]``
    are excluded (interpretation, delegated to the gold).

    ``mode`` selects the label row of the block to grade
    (:data:`_MEASURED_TOKEN_BY_MODE`, #236): same computation, another substring
    searched. Default = historical arm ``analyze``.
    """
    graded = _grade(resp, mode)
    if graded is None:
        return 1.0
    grounded, assertions = graded
    return grounded / assertions


def hallucination(resp: AnalyzeResponse, *, mode: Mode = _DEFAULT_MODE) -> float:
    """Fraction of ASSERTIONS of the measured block NOT anchored to the data [0,1] (M1,
    #229).

    Complement of :func:`grounding` on the same denominator (the assertions of the
    measured block): ``hallucination == 1 - grounding`` on every branch (up to
    floating-point rounding). A sentence in that block that asserts
    a risk without real anchoring is fabrication and counts as hallucination
    (invariant #109 preserved INSIDE the layer with backing). Vacuous branches -> 0.0;
    full narrative without assertions in the block -> 1.0 (non-attribution).
    Fabrication in the ``[CONTESTO]`` interpretation is NOT detected by the proxy
    and today has no dedicated human validation: the gold annotation of #152
    (:mod:`crime_risk_analyzer.eval.gold`) verifies the source of the risks CITED in the
    measured block, which is a different question from "did ``[CONTESTO]`` invent
    anything?". The hole is declared, not planned.

    ``mode`` as in :func:`grounding`.
    """
    graded = _grade(resp, mode)
    if graded is None:
        return 0.0
    grounded, assertions = graded
    return (assertions - grounded) / assertions


@dataclass(frozen=True)
class RiskAnchoring:
    """Decomposition of the sentences of the measured block by type of anchoring (#359).

    Alongside M1, never in its place: for equal narrative, POI names and
    ``risk_models``, same block and same sentences as :func:`_grade`. The sentences that
    name a risk (``frasi_ancorate_rischio``, with or without a point) are
    counted apart from those that name only a point
    (``frasi_ancorate_solo_poi``); ``frasi_ancorate_poi_e_rischio`` are those that
    name both, the number of the stricter rule "POI and risk in the
    same sentence" (#264). The anchored sentences of M1 are ``solo_poi +
    poi_e_rischio``. On records with ISTAT data M1 grades the raw text without the
    excluded ISTAT sentences, not ``RunRecord.narrativa``: the same text is obtained by
    passing to :func:`risk_anchoring` the raw text and the excluded sentences saved in
    the record (#377). ``conforme`` is ``False``
    when the narrative is full but the measured block is missing or empty (format
    not respected): in that case all the counts are zero. A block made
    only of excluded ISTAT sentences is conforme, with zero measured sentences.
    """

    frasi_misurate: int
    frasi_ancorate_rischio: int
    frasi_ancorate_solo_poi: int
    frasi_ancorate_poi_e_rischio: int
    conforme: bool

    @property
    def ancoraggio_rischi(self) -> float:
        """``frasi_ancorate_rischio / frasi_misurate``; 0.0 without measured sentences.

        The zero on the unrespected format follows M1, which on the same case gives
        grounding 0.0 (non-attribution): omitting it must not pay off.
        """
        if not self.frasi_misurate:
            return 0.0
        return self.frasi_ancorate_rischio / self.frasi_misurate


class InconsistentExcludedSentencesError(ValueError):
    """A sentence excluded from M1 is not among the sentences of the measured block of
    the raw text: raw text and excluded sentences of the record are not consistent
    (#377)."""


def _without_excluded_sentences(
    sentences: list[str], excluded: Sequence[str]
) -> list[str]:
    """``sentences`` without the ``excluded`` ones, one occurrence per excluded sentence
    (#377).

    Two sentences with the same text are indistinguishable for M1 (same
    anchors), so removing one or the other gives the same counts.
    """
    remaining = list(sentences)
    for excluded_sentence in excluded:
        if excluded_sentence not in remaining:
            raise InconsistentExcludedSentencesError(
                "frase esclusa da M1 che non e' fra le frasi del blocco misurato "
                f"del grezzo: {excluded_sentence!r}"
            )
        remaining.remove(excluded_sentence)
    return remaining


def risk_anchoring(
    narrativa: str | None,
    *,
    mode: Mode,
    poi_names: Iterable[str],
    risk_models: Iterable[RiskModel],
    excluded_sentences: Sequence[str] = (),
) -> RiskAnchoring | None:
    """How many sentences of the measured block name a risk, and how many only a POI.

    The M1 proxy (:func:`grounding`) counts as anchored a sentence that names a POI
    (#264). Here the two families stay separate: a sentence that names at least one
    hazard (identifier or EN/IT label) is anchored by the risk, even if it also names
    a point; one that names no hazard but names a point is anchored only by the
    POI; one that names both is also counted in ``poi_e_rischio``.

    It takes the data and not an ``AnalyzeResponse`` because it is also computed on
    records already written (``RunRecord``), without redoing runs. On records prior
    to #77 the EN/IT labels are rebuilt from today's vocabulary on
    reading (``RiskItem``) and may differ from those M1 used then.
    Same branches as
    :func:`_grade`: ``None`` (not gradable) on empty narrative or without any
    POI with a name; full narrative without measured block -> ``conforme=False`` and
    counts at zero.

    With ISTAT data in the prompt (#377) ``narrativa`` is the raw model text and
    ``excluded_sentences`` the sentences that M1 excluded
    (:func:`m1_excluded_sentences`, saved in the record): they are removed from the
    block's sentences, so the measured sentences are the M1 assertions.

    Raises:
        InconsistentExcludedSentencesError: an excluded sentence is not among the
            block's sentences, i.e. raw text and excluded sentences inconsistent.
    """
    if not (narrativa or "").strip():
        return None
    poi = _poi_anchors(poi_names)
    hazards = _hazard_anchors(risk_models)
    if not poi:
        return None
    all_sentences = _measured_sentences(narrativa, mode)
    sentences = _without_excluded_sentences(all_sentences, excluded_sentences)
    if not all_sentences:
        return RiskAnchoring(0, 0, 0, 0, conforme=False)
    risk_sentences = [f for f in sentences if _names_any(f, hazards)]
    poi_only = [
        f for f in sentences if not _names_any(f, hazards) and _names_any(f, poi)
    ]
    poi_and_risk = [f for f in risk_sentences if _names_any(f, poi)]
    return RiskAnchoring(
        frasi_misurate=len(sentences),
        frasi_ancorate_rischio=len(risk_sentences),
        frasi_ancorate_solo_poi=len(poi_only),
        frasi_ancorate_poi_e_rischio=len(poi_and_risk),
        conforme=True,
    )


def latency_ms(resp: AnalyzeResponse) -> int:
    """End-to-end latency (passthrough from AnalyzeResponse)."""
    return resp.latenza_ms


def cost_usd_of(resp: AnalyzeResponse) -> float:
    """Estimated cost; 0 if there is no LLM (baseline/fallback -> empty llm_used)."""
    if not resp.llm_used:
        return 0.0
    return cost_usd(resp.llm_used, resp.tokens_input, resp.tokens_output)


def compute_metrics(
    resp: AnalyzeResponse,
    *,
    mode: Mode = _DEFAULT_MODE,
) -> Metrics:
    """Assemble the four metrics from the AnalyzeResponse.

    ``mode`` is the arm of the run: it decides on which block the two textual proxies
    pronounce (#236). The harness passes it from the ``ExperimentConfig``, the only
    place that knows it.

    With ISTAT data in the prompt (``resp.controllo_istat``, #345, #369) M1 grades the
    raw model text without the sentences that speak of the ISTAT datum and name neither
    a POI nor a risk (:func:`m1_excluded_sentences`). Formula, splitter and
    ``METRICS_VERSION`` are the same; the measured text changes, so the ISTAT
    records of different versions (``IstatMetrics.versione``) are not compared.

    ``quality_vacuous`` (#240) exposes whether this record fell on the VACUOUS branch of
    :func:`_grade` (empty narrative or no POI to cite): grounding/
    hallucination are still 1.0/0.0 on that branch, but do not measure real
    quality. Before #240 this distinction was visible only in the comparison
    report (#231); here it becomes a field of the record so that aggregate.py and
    compare.py can mark it also outside that report (per-run table, CSV,
    and the vacuous arms/zones of the comparison itself).

    ``_grade`` is called only once here (not three times, one per metric): it is
    deterministic so it was not a bug, but the three independent invocations from
    before were repeated work without reason.
    """
    graded = _grade(resp, mode)
    if graded is None:
        grounding_value, hallucination_value = 1.0, 0.0
    else:
        grounded, assertions = graded
        grounding_value = grounded / assertions
        hallucination_value = (assertions - grounded) / assertions
    return Metrics(
        grounding=grounding_value,
        hallucination=hallucination_value,
        quality_vacuous=graded is None,
        versione=METRICS_VERSION,
        latency_ms=latency_ms(resp),
        cost_usd=cost_usd_of(resp),
    )
