from typing import get_args

import pytest

from crime_risk_analyzer.eval import compare, harness, metrics
from crime_risk_analyzer.eval.metrics import (
    _MEASURED_TOKEN_BY_MODE,  # pyright: ignore[reportPrivateUsage]
    METRICS_VERSION,
    InconsistentExcludedSentencesError,
    RiskAnchoring,
    _measured_spans,  # pyright: ignore[reportPrivateUsage]
    compute_metrics,
    cost_usd_of,
    grounding,
    hallucination,
    hazards_cited_in,
    latency_ms,
    m1_excluded_sentences,
    risk_anchoring,
)
from crime_risk_analyzer.eval.schema import ExperimentConfig, Mode, RunCase, RunRecord
from crime_risk_analyzer.istat.block import istat_block_for_poi
from crime_risk_analyzer.istat.figures import check_figures
from crime_risk_analyzer.models.vocab import ConfidenceSummary
from crime_risk_analyzer.orchestrator import AnalyzeResponse, GeoZone, PoiOut
from crime_risk_analyzer.rag.generation import (
    Repro,
    RiskItem,
    RiskModel,
    source_block_spans,
)
from crime_risk_analyzer.rag.no_ontology_generation import LLM_SYNTHESIS_BLOCK_HEADER
from tests.istat._factories import BANK_ROBBERIES, istat_poi, make_row


def _resp(
    narrativa: str,
    *,
    with_citation: bool = True,
    tokens: tuple[int, int] = (10, 20),
) -> AnalyzeResponse:
    return AnalyzeResponse(
        citta="Roma",
        zona_normalizzata="Centro",
        poi=[
            PoiOut(
                id="1",
                name="Banca A",
                ontology_class="Bank",
                lat=41.0,
                lon=12.0,
                confidence="verificato",
                sparql_path=(
                    "Bank → havingHazard → Bank_robbery" if with_citation else None
                ),
            )
        ],
        risk_models=[
            RiskModel(
                poi_id="1",
                poi="Banca A",
                risks=[
                    RiskItem(
                        hazard="Bank_robbery",
                        confidence="verificato",
                        tag="ONTOLOGIA",
                    )
                ],
            )
        ],
        narrativa=narrativa,
        confidence_summary=ConfidenceSummary(verificato=1),
        llm_used="claude-sonnet-4-6",
        latenza_ms=120,
        repro=Repro(temperature=0.0, seed=0, prompt_hash="ph"),
        cache_hit=False,
        fallback=False,
        # Fake value: here the metrics are measured on the narrative, the context
        # fingerprint (#242) is irrelevant and a literal declares it.
        contesto_hash="h-ctx",
        # Same for the zone's geo (#260): irrelevant for the metrics tested here.
        zona_geo=GeoZone(
            lat=41.0,
            lon=12.0,
            bbox_min_lat=40.9,
            bbox_min_lon=11.9,
            bbox_max_lat=41.1,
            bbox_max_lon=12.1,
        ),
        tokens_input=tokens[0],
        tokens_output=tokens[1],
    )


# #229 (M1): the real narrative is structured in BLOCKS (#196), with the source tag
# in the HEADER and not inline per sentence. The tests therefore use the real block form
# (before they used inline tags, which does not reflect the output produced by the
# prompt). ``parse_source_prose`` isolates the body of the [ONTOLOGIA] block -- the only
# layer with structured backing from grounding and therefore the only one graded by the
# M1 proxy. Overview and [CONTESTO] are interpretation: NOT gradable by the
# deterministic proxy (their quality/fabrication goes to the human gold #109/#152, and
# is curbed upstream by the prompt).
def _narrative(
    ontology: str,
    *,
    overview: str = "Sintesi della zona.",
    context: str | None = None,
) -> str:
    text = f"{overview}\n\nRischi da ontologia [ONTOLOGIA]\n{ontology}"
    if context is not None:
        text += f"\n\nRischi dal contesto [CONTESTO]\n{context}"
    return text


def test_metrics_version_is_m1_generation() -> None:
    # #229: version bump of the proxy semantics (v1 inline-tag -> v2 block-aware
    # M1). It serves compare.py/winner.py so as not to mix metric generations.
    # #264: v3, a sentence is anchored only if it names a POI of the zone.
    assert METRICS_VERSION == 3


def test_compute_metrics_saves_the_m1_version() -> None:
    # #408: the version goes out in the record, so a comparison sees whether two runs
    # were graded with the same semantics.
    r = _resp(_narrative("Banca A presenta rischio rapina."))
    assert compute_metrics(r).versione == METRICS_VERSION


def test_grounding_full_when_ontology_sentence_backed() -> None:
    r = _resp(_narrative("Banca A presenta rischio rapina."))
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0


def test_ontology_sentence_without_anchor_is_hallucination() -> None:
    # Invariant #109 PRESERVED INSIDE the layer with backing: a sentence in the
    # [ONTOLOGIA] block that asserts a risk without real anchoring (Museo X/incendio
    # are not POI/hazard of the context) is fabrication -> hallucination.
    r = _resp(_narrative("Il Museo X presenta rischio incendio."))
    assert hallucination(r) == 1.0
    assert grounding(r) == 0.0


def test_a_poi_named_after_the_tag_does_not_corrupt_the_graded_block() -> None:
    # The prompt asks to name the real points and the names come from OSM, where
    # anyone can call a venue "Bar [ONTOLOGIA] Fake". Cited in the
    # initial synthesis, the cut by source anchored inside that sentence: in the
    # graded block ended up the true header and the overview prose, i.e.
    # the metric of this experiment measured another text (0.5/0.5 instead
    # of 1.0/0.0). The graded block must be the one the model opened.
    r = _resp(
        _narrative(
            "Banca A presenta rischio rapina.",
            overview="In zona spicca il Bar [ONTOLOGIA] Fake, molto frequentato.",
        )
    )
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0


def test_context_pure_interpretation_is_excluded_not_hallucination() -> None:
    # #229 (correction to the over-penalization): the pure interpretation in [CONTESTO]
    # (no anchoring) is NOT graded by the proxy. Here the only graded block is
    # [ONTOLOGIA] (anchored) -> grounding 1.0, the contextual prose does not lower the
    # score. (Under the v1 inline-tag proxy this block narrative scored 0.)
    r = _resp(
        _narrative(
            "Banca A presenta rischio rapina.",
            context="La zona ha carattere prevalentemente commerciale.",
        )
    )
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0


def test_context_fabrication_is_delegated_to_gold_not_flagged_by_proxy() -> None:
    # #229 (EXPLICIT semantic change with respect to #109): a fabrication in the
    # [CONTESTO] block (invented Museo Z) is NOT detected by the deterministic proxy --
    # [CONTESTO] is interpretation, whose fabrication is delegated to the human gold
    # (#152) and curbed upstream by the prompt (rule 2 + [CONTESTO] "senza inventare").
    # The proxy grades only [ONTOLOGIA]: here the ontology is anchored -> grounding 1.0.
    r = _resp(
        _narrative(
            "Banca A presenta rischio rapina.",
            context="Il Museo Z rischia gravi incendi ogni notte.",
        )
    )
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0


def test_overview_and_headers_excluded_from_grading() -> None:
    # overview and header lines are not ontological assertions: excluded from the proxy.
    # Even if the overview names a non-real entity, it does not count as hallucination.
    r = _resp(
        _narrative(
            "Banca A presenta rischio rapina.",
            overview="Il Museo Y domina la zona.",
        )
    )
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0


def test_sparse_ontology_grounding_is_fraction() -> None:
    # [ONTOLOGIA] block with 2 sentences: 1 anchored + 1 not anchored -> 0.5.
    r = _resp(
        _narrative("Banca A presenta rischio rapina.\nIl Museo X rischia incendi.")
    )
    assert grounding(r) == pytest.approx(0.5)
    assert hallucination(r) == pytest.approx(0.5)


def test_filler_in_ontology_block_counts_as_ungrounded() -> None:
    # #229 (change with respect to #163): under M1 the [ONTOLOGIA] block must be
    # referential (cite the data). A filler sentence IN the block that anchors nothing
    # lowers groundedness (it is no longer excluded from the denominator): it encourages
    # an anchored synthesis, consistent with "more value per word" (#229).
    r = _resp(
        _narrative(
            "Banca A presenta rischio rapina.\n"
            "La sicurezza urbana e' un tema importante."
        )
    )
    assert grounding(r) == pytest.approx(0.5)
    assert hallucination(r) == pytest.approx(0.5)


def test_hallucination_is_complement_of_grounding_on_ontology() -> None:
    r = _resp(
        _narrative(
            "Banca A presenta rischio rapina.\nIl Museo X rischia incendi.\n"
            "Banca A e' esposta a furto."
        )
    )
    assert hallucination(r) == pytest.approx(1.0 - grounding(r))


def test_empty_narrative_is_vacuously_grounded() -> None:
    r = _resp("", tokens=(0, 0))
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0


def test_nonempty_narrative_without_ontology_block_is_penalized() -> None:
    # #229 (anti-gaming fix): a FULL narrative with data to cite but WITHOUT a
    # recognisable [ONTOLOGIA] block (non-compliant model: everything in overview /
    # header omitted) is NOT "vacuously anchored" -> it is NON-ATTRIBUTION: grounding
    # 0.0 / hallucination 1.0. So a model (or an evasive/fabricating answer) does not
    # obtain a perfect score by omitting the header -- the hallucination axis is the
    # PRIMARY criterion of winner.py (#157): evasion loses instead of winning.
    r = _resp("La zona presenta alcuni rischi generici e gravi pericoli inventati.")
    assert grounding(r) == 0.0
    assert hallucination(r) == 1.0


def test_hazards_without_a_poi_are_vacuous_nothing_to_cite() -> None:
    # #264: the risks to cite are there but no POI: nothing can anchor a sentence.
    r = _resp(_narrative("Qualcosa accade nella zona.")).model_copy(update={"poi": []})
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0
    assert compute_metrics(r).quality_vacuous is True


def test_no_anchors_is_vacuous_nothing_to_cite() -> None:
    # Vacuous branch for "nothing to cite": no anchoring available (poi/risk_models
    # empty, e.g. zone without retrieved POIs) -> the proxy has no data to grade against
    # -> grounding 1.0 / hallucination 0.0. Distinct from the non-attribution above
    # (there the data to cite were there). The anchors are not controllable by the model
    # (they come from the pipeline), so this branch is not gameable.
    r = _resp(_narrative("Qualcosa accade nella zona.")).model_copy(
        update={"poi": [], "risk_models": []}
    )
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0


def test_hazards_cited_in_returns_the_lowercased_measured_block() -> None:
    narrativa = (
        "Overview.\n\n[ONTOLOGIA]\nLa zona presenta Rapina al viaggiatore "
        "vicino alla stazione."
    )
    block = hazards_cited_in(narrativa, "analyze")
    assert "rapina al viaggiatore" in block
    assert "attacco informatico" not in block


def test_empty_poi_name_does_not_anchor_everything() -> None:
    # Regression review #163 (I1): a POI without a name (name="") must NOT make
    # every sentence "anchored". A fabricated [ONTOLOGIA] sentence stays hallucination.
    r = _resp(_narrative("Il Museo X presenta rischio incendio."))
    nameless = PoiOut(
        id="2",
        name="",
        ontology_class="Bank",
        lat=41.0,
        lon=12.0,
        confidence="verificato",
        sparql_path=None,
    )
    r = r.model_copy(update={"poi": [*r.poi, nameless]})
    assert hallucination(r) == 1.0
    assert grounding(r) == 0.0


# --- #264: the hazard alone does not anchor a sentence -------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "Il rischio di rapina in banca e' elevato nella zona.",
        "Il rischio Bank_robbery e' elevato nella zona.",
    ],
)
def test_a_sentence_naming_only_a_hazard_is_not_grounded(sentence: str) -> None:
    # Rule 6 of the prompt obliges the model to use the hazard label:
    # a generic sentence that contains it ties the risk to no point.
    r = _resp(_narrative(sentence))
    assert grounding(r) == 0.0
    assert hallucination(r) == 1.0


def test_a_sentence_naming_a_poi_without_a_hazard_is_grounded() -> None:
    r = _resp(_narrative("Banca A e' aperta fino a tardi."))
    assert grounding(r) == 1.0


def test_the_poi_name_grounds_the_sentence_with_or_without_the_hazard() -> None:
    r = _resp(
        _narrative(
            "Banca A: rapina in banca.\n"
            "Il rischio di rapina in banca e' elevato nella zona."
        )
    )
    assert grounding(r) == pytest.approx(0.5)


def test_without_a_named_poi_the_proxy_has_nothing_to_cite() -> None:
    # The hazards are there but no POI has a name: the sentence has nothing that
    # could anchor it, as in the vacuous branch "nothing to cite".
    r = _resp(_narrative("Il rischio di rapina in banca e' elevato.")).model_copy(
        update={"poi": []}
    )
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0
    assert compute_metrics(r).quality_vacuous is True


# --- #236: the graded block depends on the arm, not the computation --------------


def _llm_synthesis_narrative(body: str) -> str:
    """Narrative of the ablated arm: same body, honest block label.

    That arm consulted no ontology, so it does not title the
    block after the ontology (see ``rag/no_ontology_generation.py``).
    """
    return f"Sintesi della zona.\n\n{LLM_SYNTHESIS_BLOCK_HEADER}\n{body}"


def test_the_ablated_arm_is_graded_on_its_own_block_label() -> None:
    """Same text, different labels, same score.

    ONLY which label row the proxy looks for changes, depending on the ``mode`` of the
    run: if the score changed, the comparison between the two arms would measure
    the label instead of the anchoring.
    """
    body = "Banca A presenta rischio rapina.\nIl Museo X rischia incendi."
    ablated = _resp(_llm_synthesis_narrative(body))
    full = _resp(_narrative(body))
    assert grounding(ablated, mode="no_ontology_prompt") == pytest.approx(0.5)
    assert hallucination(ablated, mode="no_ontology_prompt") == pytest.approx(0.5)
    assert grounding(ablated, mode="no_ontology_prompt") == grounding(full)
    assert hallucination(ablated, mode="no_ontology_prompt") == hallucination(full)


def test_the_complete_arm_is_still_graded_on_the_ontology_label() -> None:
    """Non-regression: for ``analyze`` the graded block stays [ONTOLOGIA].

    The default ``mode`` is the historical arm, so every call written
    before #236 measures exactly what it measured.
    """
    r = _resp(_narrative("Banca A presenta rischio rapina."))
    assert grounding(r, mode="analyze") == 1.0
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0


def test_the_label_of_the_other_arm_does_not_open_the_graded_block() -> None:
    """The label is per arm: that of the other does not open the block.

    An ablated run that wrote ``[ONTOLOGIA]`` anyway (non-compliant
    model) falls into NON-ATTRIBUTION like any answer lacking the
    expected block: 0.0/1.0. Same treatment as the omitted header (#229), so
    there is no "convenient" label that pays off.
    """
    r = _resp(_narrative("Banca A presenta rischio rapina."))
    assert grounding(r, mode="no_ontology_prompt") == 0.0
    assert hallucination(r, mode="no_ontology_prompt") == 1.0


def test_compute_metrics_grades_the_block_of_the_given_arm() -> None:
    """The ``mode`` reaches the assembly of the four metrics."""
    r = _resp(_llm_synthesis_narrative("Banca A presenta rischio rapina."))
    assert compute_metrics(r, mode="no_ontology_prompt").grounding == 1.0
    # Without the right mode the same run would turn out unattributed.
    assert compute_metrics(r).grounding == 0.0


def test_compute_metrics_quality_vacuous_true_on_empty_narrative() -> None:
    """#240: the vacuity marker distinguishes the vacuous branch (nothing to judge)."""
    r = _resp("", tokens=(0, 0))
    assert compute_metrics(r).quality_vacuous is True


def test_compute_metrics_quality_vacuous_false_on_graded_narrative() -> None:
    """A gradable narrative (with or without attribution) is not vacuous."""
    grounded = _resp(_narrative("Banca A presenta rischio rapina."))
    assert compute_metrics(grounded).quality_vacuous is False
    unattributed = _resp(
        "La zona presenta alcuni rischi generici e gravi pericoli inventati."
    )
    assert compute_metrics(unattributed).quality_vacuous is False


def test_every_mode_declares_the_block_the_proxy_grades() -> None:
    """A new arm cannot enter without saying what it is measured on.

    The ``mode`` decides which block the proxy grades: if the map fell
    behind, the new mode would be measured on the label of another and
    would get 0.0/1.0 for non-attribution, silently.
    """
    assert set(get_args(Mode)) == set(_MEASURED_TOKEN_BY_MODE)


def test_latency_passthrough() -> None:
    assert latency_ms(_resp("x")) == 120


def test_compute_metrics_cost() -> None:
    m = compute_metrics(
        _resp(_narrative("Banca A presenta rischio rapina."), tokens=(1_000_000, 0))
    )
    assert m.cost_usd == pytest.approx(3.0)
    assert 0.0 <= m.grounding <= 1.0


def test_cost_usd_of_zero_when_no_llm() -> None:
    r = _resp(
        _narrative("Banca A presenta rischio rapina."), tokens=(1_000_000, 0)
    ).model_copy(update={"llm_used": ""})
    assert cost_usd_of(r) == 0.0


# --- M1 with the ISTAT data in the prompt (#345, #368, #369)
# ---------------------------

_ISTAT_BLOCK = istat_block_for_poi(istat_poi(make_row(), BANK_ROBBERIES))
_ANCHORED = "Banca A: rapina in banca."
_NOT_ANCHORED = "La zona e' molto affollata."
_ISTAT = "Secondo l'ISTAT nel Comune di Roma i furti sono in calo."


def _resp_istat(raw: str, *, poi: str = "Banca A") -> AnalyzeResponse:
    """Response with the ISTAT data in the prompt: ``grezzo`` is the model's text,
    the narrative the one filtered by the check (as in ``generate_analysis``)."""
    outcome = check_figures(
        raw,
        blocks=source_block_spans(raw),
        istat_block=_ISTAT_BLOCK.testo,
        context_without_istat="ZONA: Colosseo",
        rows=_ISTAT_BLOCK.righe,
    )
    resp = _resp(outcome.testo_filtrato)
    return resp.model_copy(
        update={
            "narrativa_grezza": raw,
            "controllo_istat": outcome,
            "poi": [resp.poi[0].model_copy(update={"name": poi})],
            "risk_models": [resp.risk_models[0].model_copy(update={"poi": poi})],
        }
    )


def _m1(resp: AnalyzeResponse) -> tuple[float, float, bool | None]:
    m = compute_metrics(resp)
    return (m.grounding, m.hallucination, m.quality_vacuous)


def test_without_istat_no_excluded_sentence() -> None:
    assert m1_excluded_sentences(_resp(_narrative(f"{_ANCHORED} {_ISTAT}"))) is None


def test_m1_istat_excludes_the_istat_sentences_without_poi_or_risk() -> None:
    """#369: the ISTAT sentence that names neither a POI nor a risk leaves the
    denominator; the not-anchored sentence without ISTAT words stays."""
    resp = _resp_istat(_narrative(f"{_ANCHORED} {_NOT_ANCHORED} {_ISTAT}"))
    assert _m1(resp) == (0.5, 0.5, False)
    assert m1_excluded_sentences(resp) == [_ISTAT.rstrip(".")]


@pytest.mark.parametrize(
    ("sentence", "expected_grounding"),
    [
        # names a POI: measured and anchored
        (
            "Secondo l'ISTAT nel Comune di Roma i furti vicino a Banca A sono in calo.",
            2 / 3,
        ),
        # names only a risk: measured but, since #264, not anchored
        (
            "Secondo l'ISTAT nel Comune di Roma la rapina in banca ha un tasso "
            "piu' alto.",
            1 / 3,
        ),
    ],
)
def test_m1_istat_measures_the_istat_sentence_that_names_a_poi_or_a_risk(
    sentence: str, expected_grounding: float
) -> None:
    """#369: with a POI or a risk the ISTAT sentence does not leave the denominator;
    it counts as anchored only if it names a POI (#264). Known cost: the ISTAT sentence
    with a risk and without a POI stays measured and not anchored."""
    resp = _resp_istat(_narrative(f"{_ANCHORED} {_NOT_ANCHORED} {sentence}"))
    assert compute_metrics(resp).grounding == pytest.approx(expected_grounding)
    assert m1_excluded_sentences(resp) == []


def test_m1_istat_block_made_only_of_istat_sentences_is_non_attribution() -> None:
    """No measured sentence remains: the block attributes no risks to the points,
    like an empty block (grounding 0, hallucination 1), not an empty case."""
    resp = _resp_istat(_narrative(f"{_ISTAT} Il tasso dei furti e' piu' alto."))
    # anchors present (Banca A, rapina in banca) and all sentences excluded
    assert m1_excluded_sentences(resp) == [
        _ISTAT.rstrip("."),
        "Il tasso dei furti e' piu' alto",
    ]
    assert _m1(resp) == (0.0, 1.0, False)


def test_m1_istat_without_poi_or_risks_is_vacuous_and_excludes_nothing() -> None:
    """Review #369: without anchors M1 is vacuous and grades nothing, so it
    excludes nothing. Before, every ISTAT sentence turned out excluded and the record
    declared it for a zone not graded."""
    resp = _resp_istat(_narrative(f"{_ANCHORED} {_ISTAT}")).model_copy(
        update={"poi": [], "risk_models": []}
    )
    assert _m1(resp) == (1.0, 0.0, True)
    assert m1_excluded_sentences(resp) == []


def test_m1_istat_without_poi_but_with_risks_is_vacuous_and_excludes_nothing() -> None:
    """#264: the hazards are there but no POI: M1 grades nothing (vacuous branch),
    so it does not exclude the ISTAT sentence. With v2 the hazards were enough to grade
    and the sentence turned out excluded."""
    resp = _resp_istat(_narrative(f"{_ANCHORED} {_ISTAT}")).model_copy(
        update={"poi": []}
    )
    assert _m1(resp) == (1.0, 0.0, True)
    assert m1_excluded_sentences(resp) == []


def test_m1_istat_empty_narrative_is_vacuous_and_excludes_nothing() -> None:
    resp = _resp_istat("")
    assert _m1(resp) == (1.0, 0.0, True)
    assert m1_excluded_sentences(resp) == []


def test_m1_istat_without_header_and_only_istat_sentences_is_non_attribution() -> None:
    """#369: before, the text without the ISTAT sentences stayed empty and counted as an
    empty case, with a perfect score. The narrative is there: it is non-attribution."""
    resp = _resp_istat(f"{_ISTAT}\n")
    assert _m1(resp) == (0.0, 1.0, False)


@pytest.mark.parametrize(
    ("body", "excluded_sentence"),
    [
        # "ecc." does not close the sentence for the filter, for M1 it does
        (f"Banca A: rapina in banca, scippi ecc. {_ISTAT}", _ISTAT.rstrip(".")),
        # period followed by asterisks or by a parenthesis: same
        (f"**Banca A**: rapina in banca.** {_ISTAT}", f"** {_ISTAT.rstrip('.')}"),
        (f"Banca A (rapina in banca.) {_ISTAT}", f") {_ISTAT.rstrip('.')}"),
        # the exclamation mark closes the sentence for the filter, for M1 it does not
        (
            f"{_ANCHORED} La zona e' affollata! {_ISTAT}",
            f"La zona e' affollata! {_ISTAT.rstrip('.')}",
        ),
    ],
)
def test_m1_istat_excludes_m1_sentences(body: str, excluded_sentence: str) -> None:
    """#369: the excluded sentences are those of M1, split as M1 splits them."""
    resp = _resp_istat(_narrative(body))
    assert m1_excluded_sentences(resp) == [excluded_sentence]
    assert _m1(resp) == (1.0, 0.0, False)


@pytest.mark.parametrize(
    "introduction",
    [
        "I dati ISTAT del Comune di Roma (2024) indicano:",
        # removed by the filter: thefts are falling
        "I dati ISTAT del Comune di Roma (2024) indicano furti in aumento:",
    ],
)
def test_m1_istat_inherited_place_does_not_depend_on_the_filter(
    introduction: str,
) -> None:
    """#369: the list row inherits the place also from a removed introduction."""
    resp = _resp_istat(_narrative(f"{_ANCHORED}\n{introduction}\n- furti: in calo;"))
    assert m1_excluded_sentences(resp) == [introduction, "- furti: in calo;"]
    assert _m1(resp) == (1.0, 0.0, False)


@pytest.mark.parametrize("trend", ["in calo", "in aumento"])
def test_m1_istat_measures_the_anchored_sentence_after_any_istat_sentence(
    trend: str,
) -> None:
    """#369, the review case: before, the anchored sentence after a right ISTAT
    sentence (which passes the place) was cut, after a wrong one it stayed."""
    istat = f"Secondo l'ISTAT nel Comune di Roma i furti sono {trend}."
    resp = _resp_istat(_narrative(f"{istat} Vicino a Banca A i furti sono in calo."))
    assert m1_excluded_sentences(resp) == [istat.rstrip(".")]
    assert _m1(resp) == (1.0, 0.0, False)


def test_m1_istat_limit_a_risk_invented_in_istat_words_is_excluded() -> None:
    """Declared limit (#369): a risk that is not in the knowledge base,
    written with the words of the ISTAT datum, leaves the denominator instead of
    counting as not anchored. The record keeps it among the excluded sentences."""
    invented = "Secondo i dati ISTAT nel Comune di Roma i sequestri di persona crescono"
    resp = _resp_istat(_narrative(f"{_ANCHORED} {invented}."))
    assert m1_excluded_sentences(resp) == [invented]
    assert _m1(resp) == (1.0, 0.0, False)


def test_m1_istat_measures_the_raw_text_without_touching_it() -> None:
    """#369: the measured sentences are those of the raw text, not of a rewritten text
    (before the cut compressed double spaces and the POI name was no longer
    found)."""
    name = "Bar  Centrale"
    resp = _resp_istat(_narrative(f"{name}: borseggi. {_ISTAT}"), poi=name)
    assert _m1(resp) == (1.0, 0.0, False)


def test_m1_istat_same_with_crlf_newlines() -> None:
    lf = _narrative(f"{_ANCHORED}\n{_ISTAT}\n\n- furti: in calo;")
    crlf = lf.replace("\n", "\r\n")
    assert _m1(_resp_istat(crlf)) == _m1(_resp_istat(lf)) == (0.5, 0.5, False)
    assert m1_excluded_sentences(_resp_istat(crlf)) == m1_excluded_sentences(
        _resp_istat(lf)
    )


def test_m1_istat_grades_the_raw_text_not_the_filtered_one() -> None:
    """The filter removes the sentence with an invented number, M1 measures it
    (#345)."""
    resp = _resp_istat(_narrative(f"{_ANCHORED} Si stimano 999 episodi l'anno."))
    assert "999" not in (resp.narrativa or "")
    assert _m1(resp) == (0.5, 0.5, False)
    assert grounding(resp) == 0.5 and hallucination(resp) == 0.5


def test_m1_istat_raw_text_emptied_by_the_filter_is_non_attribution() -> None:
    """The filter removes the only sentence (thefts are falling): the displayed
    narrative is empty, but the model wrote. M1 looks at the raw text, so it is
    non-attribution and not the empty case with a perfect score."""
    resp = _resp_istat("Secondo l'ISTAT nel Comune di Roma i furti sono in aumento.\n")
    assert (resp.narrativa or "").strip() == ""
    assert _m1(resp) == (0.0, 1.0, False)


def test_m1_istat_numbered_list_ends_like_the_dashed_one() -> None:
    """#369, B1 and B-1: M1 detaches "1" from "1. furti: in calo;". That number must
    not interrupt the list nor extend it (the sentence after the list, which does not
    speak of the datum, stays measured) and it follows the item: excluded with it, not
    counted as a not-anchored assertion. Numbered and dashed give the same M1."""
    introduction = "I dati ISTAT del Comune di Roma (2024) indicano:"
    after = "La zona e' affollata e i furti sono in calo"

    def resp(first: str, second: str) -> AnalyzeResponse:
        return _resp_istat(
            _narrative(
                f"{_ANCHORED}\n{introduction}\n{first} furti: in calo;\n"
                f"{second} furti: sopra la media italiana\n{after}."
            )
        )

    numbered, dashes = resp("1.", "2."), resp("-", "-")
    assert m1_excluded_sentences(numbered) == [
        introduction,
        "1",
        "furti: in calo;",
        "2",
        "furti: sopra la media italiana",
    ]
    assert m1_excluded_sentences(dashes) == [
        introduction,
        "- furti: in calo;",
        "- furti: sopra la media italiana",
    ]
    # measured in both: Banca A (anchored) and the sentence after the list
    assert _m1(numbered) == _m1(dashes) == (0.5, 0.5, False)


def test_m1_istat_prose_on_the_label_row_passes_the_place() -> None:
    """#369, C2: M1 does not measure the prose written on the label row, but the place
    it names holds for the list that follows, as for the filter."""
    raw = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA] I dati ISTAT del Comune di "
        f"Roma (2024) indicano:\n- furti: in calo;\n{_ANCHORED}\n"
    )
    resp = _resp_istat(raw)
    assert m1_excluded_sentences(resp) == ["- furti: in calo;"]
    assert _m1(resp) == (1.0, 0.0, False)


def test_m1_istat_prose_on_the_label_row_is_never_excluded() -> None:
    """#369, C2: contract of ``frasi_istat_m1``. The prose on the label row
    passes the place but is not an M1 sentence: it does not appear among the check's
    intervals nor among the excluded sentences, even when it speaks of the datum."""
    prose = "Secondo l'ISTAT nel Comune di Roma i furti sono in calo"
    raw = (
        f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA] {prose}. I dati ISTAT del "
        f"Comune di Roma (2024) indicano:\n- furti: in calo;\n{_ANCHORED}\n"
    )
    resp = _resp_istat(raw)
    assert resp.controllo_istat is not None
    block_start = raw.index("\n", raw.index("[ONTOLOGIA]")) + 1
    intervals = resp.controllo_istat.frasi_istat_m1
    assert intervals and all(a >= block_start for a, _ in intervals)
    excluded = m1_excluded_sentences(resp)
    assert excluded is not None
    assert excluded == ["- furti: in calo;"]
    assert not any(prose in e or "indicano" in e for e in excluded)


def test_m1_istat_without_raw_text_raises() -> None:
    """#369, C3: the offsets of the ISTAT sentences are those of the raw text; without
    the raw text M1 does not silently fall back on the filtered narrative."""
    resp = _resp_istat(_narrative(f"{_ANCHORED} {_ISTAT}")).model_copy(
        update={"narrativa_grezza": None}
    )
    with pytest.raises(ValueError, match="narrativa_grezza"):
        compute_metrics(resp)
    with pytest.raises(ValueError, match="narrativa_grezza"):
        m1_excluded_sentences(resp)


# --- Parity between the M1 sentences and those of the ISTAT check (#369) -------------
#
# M1 (``_measured_spans``) and the check (``CheckOutcome.frasi_istat_m1``)
# must split the same block into the same sentences: if they diverged, the
# check's intervals would not coincide with any M1 sentence and no
# sentence would be excluded, without error.

#: Narratives in which EVERY M1 sentence of the measured block names ISTAT: the ISTAT
#: sentences of the check must be exactly the M1 sentences.
_ALL_ISTAT = [
    _narrative("Per l'ISTAT a Roma i furti sono in calo."),
    _narrative("Secondo l'ISTAT scippi ecc. Per l'ISTAT a Roma i furti calano."),
    _narrative("**Per l'ISTAT a Roma furti in calo.** Per l'ISTAT anche rapine."),
    _narrative("Per l'ISTAT a Roma (furti in calo.) Per l'ISTAT rapine stabili."),
    _narrative("Per l'ISTAT a Roma furti in calo! Per l'ISTAT rapine. Ecco l'ISTAT"),
    _narrative(
        "I dati ISTAT di Roma:\n- ISTAT, furti: in calo;\n\n1. ISTAT, rapine: ok"
    ),
    _narrative("Per l'ISTAT a Roma furti in calo.\nPer l'ISTAT rapine.").replace(
        "\n", "\r\n"
    ),
    "Sintesi.\n\n**Rischi da ontologia [ONTOLOGIA]**\nPer l'ISTAT a Roma furti.\n"
    "\nRischi dal contesto [CONTESTO]\nPer l'ISTAT a Roma furti.\n",
    "Sintesi.\n\nRischi dal contesto [CONTESTO]\nPer l'ISTAT a Roma furti.\n\n"
    "Rischi da ontologia [ONTOLOGIA]\nPer l'ISTAT a Roma. Per l'ISTAT rapine.\n",
    "Sintesi.\n\nRischi da ontologia [ONTOLOGIA] I dati ISTAT di Roma:\n"
    "- per l'ISTAT, furti: in calo;\n",
]

#: Narratives of the tests of this module, with ISTAT sentences and not: the ISTAT
#: sentences of the check are a subset of the M1 sentences.
_MIXED = [
    _narrative(f"{_ANCHORED} {_NOT_ANCHORED} {_ISTAT}"),
    _narrative(f"Banca A: rapina in banca, scippi ecc. {_ISTAT}"),
    _narrative(f"**Banca A**: rapina in banca.** {_ISTAT}"),
    _narrative(f"Banca A (rapina in banca.) {_ISTAT}"),
    _narrative(f"{_ANCHORED} La zona e' affollata! {_ISTAT}"),
    _narrative(
        f"{_ANCHORED}\nI dati ISTAT del Comune di Roma (2024) indicano:\n"
        "1. furti: in calo;\n2. furti: sopra la media italiana\n"
        "La zona e' affollata e i furti sono in calo."
    ),
    _narrative(f"{_ANCHORED}\n{_ISTAT}\n\n- furti: in calo;").replace("\n", "\r\n"),
    _narrative(f"{_ANCHORED} Si stimano 999 episodi l'anno."),
    f"{_ISTAT}\n",
]


def _m1_and_istat_sentences(
    raw: str,
) -> tuple[list[tuple[int, int]], tuple[tuple[int, int], ...]]:
    resp = _resp_istat(raw)
    assert resp.controllo_istat is not None
    return _measured_spans(raw, "analyze"), resp.controllo_istat.frasi_istat_m1


@pytest.mark.parametrize("raw", _ALL_ISTAT)
def test_parity_of_m1_and_check_sentences(raw: str) -> None:
    measured, istat = _m1_and_istat_sentences(raw)
    assert measured, "the corpus must have a non-empty measured block"
    assert list(istat) == measured


@pytest.mark.parametrize("raw", _MIXED)
def test_check_istat_sentences_are_m1_sentences(raw: str) -> None:
    measured, istat = _m1_and_istat_sentences(raw)
    assert set(istat) <= set(measured)


# --- Risk anchoring on the text measured by M1 with ISTAT (#377) ---------------


def _record_istat(resp: AnalyzeResponse) -> RunRecord:
    """The record that the harness writes for ``resp`` (raw text and excluded
    sentences)."""
    return harness._record_from_response(  # pyright: ignore[reportPrivateUsage]
        run_id="r",
        snapshot_id="s",
        config=ExperimentConfig(
            name="istat", mode="analyze", model="groq", cases=[], istat=True
        ),
        case=RunCase(citta="Roma", zona="Colosseo"),
        model_id="m",
        resp=resp,
        code_commit="a",
        ontology_hash="b",
        snapshot_catturato_il=None,
        snapshot_configurazione_canonica=None,
    )


def _anchoring_from_record(resp: AnalyzeResponse) -> RiskAnchoring | None:
    """The comparison section on the record written by the harness."""
    return compare._record_anchoring(  # pyright: ignore[reportPrivateUsage]
        _record_istat(resp)
    )


@pytest.mark.parametrize(
    "raw",
    [
        *_MIXED,
        _narrative(f"{_ISTAT} Il tasso dei furti e' piu' alto."),
        _narrative(f"{_ANCHORED} {_ISTAT} {_ISTAT}"),
    ],
)
def test_anchoring_from_istat_record_splits_the_m1_sentences(raw: str) -> None:
    """#377: raw text minus the saved excluded sentences = the M1 assertions."""
    resp = _resp_istat(raw)
    graded = metrics._grade(resp, "analyze")  # pyright: ignore[reportPrivateUsage]
    r = _anchoring_from_record(resp)
    assert graded is not None and r is not None
    if r.frasi_misurate:
        assert (
            r.frasi_ancorate_rischio + r.frasi_ancorate_solo_poi,
            r.frasi_misurate,
        ) == graded
    else:
        # Without block, or with the block made only of excluded ISTAT sentences: M1
        # counts it non-attribution, the risk anchoring is 0.
        assert graded == (0, 1)
        assert r.ancoraggio_rischi == 0.0


def test_anchoring_from_record_without_excluded_sentences_measures_the_raw_text() -> (
    None
):
    """#377: empty exclusion list but filtered narrative different from the raw text
    (the check removes a non-ISTAT figure): the M1 sentences are measured, i.e.
    the raw text, not the displayed narrative."""
    resp = _resp_istat(_narrative(f"{_ANCHORED} Si stimano 999 episodi l'anno."))
    record = _record_istat(resp)
    assert record.frasi_escluse_m1 == []
    assert record.narrativa != record.narrativa_grezza
    graded = metrics._grade(resp, "analyze")  # pyright: ignore[reportPrivateUsage]
    r = _anchoring_from_record(resp)
    assert r is not None
    assert (r.frasi_ancorate_rischio + r.frasi_ancorate_solo_poi, r.frasi_misurate) == (
        graded
    )
    assert r.frasi_misurate == 2


def test_block_of_only_excluded_istat_sentences_is_conforming() -> None:
    """The format is there: it is not a non-conforming narrative, just without
    sentences."""
    r = _anchoring_from_record(
        _resp_istat(_narrative(f"{_ISTAT} Il tasso dei furti e' piu' alto."))
    )
    assert r == RiskAnchoring(0, 0, 0, 0, conforme=True)


def test_anchoring_with_excluded_sentences_removes_one_sentence_per_item() -> None:
    text = _narrative(f"{_ANCHORED} {_NOT_ANCHORED} {_NOT_ANCHORED}")
    r = risk_anchoring(
        text,
        mode="analyze",
        poi_names=["Banca A"],
        risk_models=[],
        excluded_sentences=[_NOT_ANCHORED.rstrip(".")],
    )
    assert r == RiskAnchoring(2, 0, 1, 0, conforme=True)


def test_anchoring_excluded_sentence_absent_from_the_block_raises() -> None:
    with pytest.raises(InconsistentExcludedSentencesError, match="frase esclusa"):
        risk_anchoring(
            _narrative(_ANCHORED),
            mode="analyze",
            poi_names=["Banca A"],
            risk_models=[],
            excluded_sentences=["Frase che non c'e'"],
        )
