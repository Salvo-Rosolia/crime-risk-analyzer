"""Ontology vs ontology + ISTAT comparison (#345, spec 4.9 / D12)."""

from __future__ import annotations

import json

import pytest

from crime_risk_analyzer.eval.compare import (
    CONFOUNDED_VARIABLE_HEAD,
    ISTAT_EXCLUDED_WITHOUT_ITEM_TEXT,
    ISTAT_ISOLATED_VARIABLE_HEAD,
    ISTAT_M1_REDUCED_TEXT,
    ISTAT_M1_SPLITTER_LIMIT,
    ISTAT_NO_WINNER_REASON,
    ISTAT_VERSIONS_DIFFER_HEAD,
    Comparison,
    compare_records,
    is_istat_isolating_pair,
    to_json,
    to_markdown,
)
from crime_risk_analyzer.eval.schema import (
    IstatMetrics,
    Metrics,
    Mode,
    Provenance,
    RunRecord,
    RunStatus,
)


def _istat_metrics(
    versione: int = 2,
    frasi_escluse_m1: int = 0,
    frasi_escluse_senza_voce: int | None = None,
) -> IstatMetrics:
    return IstatMetrics(
        versione=versione,
        frasi_escluse_m1=frasi_escluse_m1,
        frasi_escluse_senza_voce=frasi_escluse_senza_voce,
        cifre_totali=4,
        cifre_istat=1,
        confronti_totali=2,
        confronti_coerenti=1,
        frasi_scartabili=1,
        voci_fornite=3,
        voci_citate=2,
        frasi_istat=2,
        frasi_istat_con_luogo=2,
        direzioni_totali=1,
        direzioni_coerenti=1,
        corrispondenze_non_dichiarate=0,
        numeri_in_lettere=0,
    )


def _rec(
    experiment: str,
    zona: str,
    *,
    istat: bool,
    mode: Mode = "analyze",
    model: str = "openai/gpt-oss-120b",
    hallucination: float = 0.2,
) -> RunRecord:
    return RunRecord(
        run_id=f"{experiment}__roma__{zona}".lower(),
        experiment=experiment,
        citta="Roma",
        zona=zona,
        mode=mode,
        model_id=model,
        status=RunStatus.OK,
        metrics=Metrics(
            grounding=1 - hallucination,
            hallucination=hallucination,
            quality_vacuous=False,
            latency_ms=100,
            cost_usd=0.001,
        ),
        narrativa="testo",
        n_poi=1,
        # #349: record with the POIs in the prompt, like those the harness writes today.
        poi_nel_prompt=["1"],
        istat_metrics=_istat_metrics() if istat else None,
        provenance=Provenance(
            code_commit="c",
            ontology_hash="o",
            snapshot_id=f"roma__{zona}".lower(),
            model_id=model,
            prompt_hash="p",
            temperature=0.0,
            seed=0,
            experiment=experiment,
            istat=istat,
        ),
    )


def _arms(**kw_b: object) -> tuple[list[RunRecord], list[RunRecord]]:
    a = [_rec("istat", z, istat=True) for z in ("Colosseo", "Termini")]
    b = [
        _rec("base", z, istat=False, hallucination=0.4) for z in ("Colosseo", "Termini")
    ]
    if kw_b:
        b = [r.model_copy(update=kw_b) for r in b]
    return a, b


def test_istat_pair_recognised() -> None:
    a, b = _arms()
    assert is_istat_isolating_pair(a, b) and is_istat_isolating_pair(b, a)
    assert not is_istat_isolating_pair(a, a)
    same = [_rec("x", "Colosseo", istat=False)]
    assert not is_istat_isolating_pair(same, same)


def test_isolated_variable_note_and_no_winner() -> None:
    a, b = _arms()
    comparison = compare_records(a, b, label_a="istat", label_b="base")
    assert comparison.isolated_variable.startswith(ISTAT_ISOLATED_VARIABLE_HEAD)
    assert "`istat` lo riceve, `base` no" in comparison.isolated_variable
    assert comparison.quality_verdict.applicable is False
    assert comparison.quality_verdict.reason == ISTAT_NO_WINNER_REASON


def test_different_settings_declare_the_variable_not_isolated() -> None:
    a, _ = _arms()
    b = [
        _rec("base", z, istat=False, model="claude-sonnet-4-6")
        for z in ("Colosseo", "Termini")
    ]
    comparison = compare_records(a, b, label_a="istat", label_b="base")
    assert comparison.isolated_variable.startswith(CONFOUNDED_VARIABLE_HEAD)
    assert "modello" in comparison.isolated_variable


def test_ontology_pair_with_different_istat_is_not_isolated() -> None:
    """ISTAT is a shared setting in the thesis comparison (D6)."""
    a = [_rec("con", z, istat=True) for z in ("Colosseo", "Termini")]
    b = [
        _rec("senza", z, istat=False, mode="no_ontology_prompt")
        for z in ("Colosseo", "Termini")
    ]
    comparison = compare_records(a, b, label_a="con", label_b="senza")
    assert comparison.isolated_variable.startswith(CONFOUNDED_VARIABLE_HEAD)
    assert "dati ISTAT nel prompt" in comparison.isolated_variable


def test_istat_metrics_side_by_side_in_the_report() -> None:
    a, b = _arms()
    comparison = compare_records(a, b, label_a="istat", label_b="base")
    assert [
        (z.zona, z.a is not None, z.b is None) for z in comparison.istat_metrics
    ] == [
        ("Colosseo", True, True),
        ("Termini", True, True),
    ]
    md = to_markdown(comparison)
    assert "### Metriche ISTAT (affiancate, nessun vincitore)" in md
    # Version 2: the sentences excluded from M1 (#369) did not exist.
    assert (
        "| Roma | Colosseo | 2 | 1 | 2/3 | 2/2 | 0 | 1 | 1/1 | 1/2 | 0 | 0 | 0 | n/d "
        "| - | - | - | - | - | - | - | - | - | - | - | - |" in md
    )


def test_report_says_m1_with_istat_is_on_a_reduced_text() -> None:
    """#369: the arm with ISTAT is graded on a reduced text; the report says
    so, with how many sentences are excluded and the limit of the invented risk."""
    a, b = _arms()
    a = [r.model_copy(update={"istat_metrics": _istat_metrics(4, 3)}) for r in a]
    md = to_markdown(compare_records(a, b, label_a="istat", label_b="base"))
    assert (
        "| Roma | Colosseo | 4 | 1 | 2/3 | 2/2 | 0 | 1 | 1/1 | 1/2 | 0 | 0 | 0 | 3 |"
        in md
    )
    assert ISTAT_M1_REDUCED_TEXT in md
    assert "`istat`: 6 frasi escluse" in md
    section = md.split("### Metriche ISTAT")[1]
    assert section.index(ISTAT_M1_REDUCED_TEXT) < section.index("Nota metodologica")


def _with_without_item(without_item: tuple[int | None, int | None]) -> Comparison:
    a, b = _arms()
    a = [
        r.model_copy(update={"istat_metrics": _istat_metrics(4, 3, n)})
        for r, n in zip(a, without_item, strict=True)
    ]
    return compare_records(a, b, label_a="istat", label_b="base")


def test_report_counts_apart_the_excluded_without_item_of_the_prompt() -> None:
    """#378: next to the excluded sentences, how many do not name an item of the
    ISTAT rows of the prompt; the note says they are candidates to read by hand."""
    comparison = _with_without_item((1, 0))
    md = to_markdown(comparison)
    assert (
        "> Frasi escluse da M1 — `istat`: 6 frasi escluse, di cui 1 senza voce "
        "ISTAT del prompt." in md
    )
    assert ISTAT_EXCLUDED_WITHOUT_ITEM_TEXT in md
    section = md.split("### Metriche ISTAT")[1]
    assert (
        section.index(ISTAT_M1_REDUCED_TEXT)
        < section.index(ISTAT_EXCLUDED_WITHOUT_ITEM_TEXT)
        < section.index("Nota metodologica")
    )
    zone = json.loads(to_json(comparison))["istat_metrics"]
    assert [z["a"]["frasi_escluse_senza_voce"] for z in zone] == [1, 0]


def test_excluded_without_item_do_not_touch_m1_nor_the_verdict() -> None:
    counted, uncounted = _with_without_item((2, 1)), _with_without_item((None, None))
    assert counted.model_dump(exclude={"istat_metrics"}) == uncounted.model_dump(
        exclude={"istat_metrics"}
    )


def test_record_without_the_count_of_excluded_without_item() -> None:
    """One zone written before #378 is enough: the arm's total is n/d."""
    md = to_markdown(_with_without_item((1, None)))
    assert (
        "`istat`: 6 frasi escluse, di cui n/d senza voce ISTAT del prompt (record "
        "senza il conteggio)." in md
    )


def test_the_note_declares_the_pieces_of_the_m1_splitter() -> None:
    """#369, C1: the pieces that M1 derives from "d.lgs. 7/2016" or "134.169" stay
    measured as not anchored; the note says so."""
    assert ISTAT_M1_SPLITTER_LIMIT in ISTAT_M1_REDUCED_TEXT
    a, b = _arms()
    md = to_markdown(compare_records(a, b, label_a="istat", label_b="base"))
    assert "«d.lgs. 7/2016» o «134.169»" in md


def test_arms_with_istat_of_different_versions_have_a_warning() -> None:
    """#369, D2: two arms with ISTAT of different versions are compared, but the
    report warns before the tables that M1 is graded with different rules."""
    old_records = [_rec("v3", z, istat=True) for z in ("Colosseo", "Termini")]
    old_records = [
        r.model_copy(update={"istat_metrics": _istat_metrics(3)}) for r in old_records
    ]
    new_records = [
        _rec("v4", z, istat=True).model_copy(
            update={"istat_metrics": _istat_metrics(4, 1)}
        )
        for z in ("Colosseo", "Termini")
    ]
    comparison = compare_records(old_records, new_records, label_a="v3", label_b="v4")
    warning = comparison.avviso_versioni_istat
    assert warning.startswith(ISTAT_VERSIONS_DIFFER_HEAD)
    assert "`v3`: versione 3; `v4`: versione 4" in warning
    md = to_markdown(comparison)
    assert md.index(ISTAT_VERSIONS_DIFFER_HEAD) < md.index("| citta |")
    # Field of the model (point 4 of the review): the JSON carries the same warning.
    assert json.loads(to_json(comparison))["avviso_versioni_istat"] == warning
    same_pair = compare_records(new_records, new_records, label_a="x", label_b="y")
    assert same_pair.avviso_versioni_istat == ""
    assert ISTAT_VERSIONS_DIFFER_HEAD not in to_markdown(same_pair)
    assert json.loads(to_json(same_pair))["avviso_versioni_istat"] == ""


def test_only_one_arm_with_istat_no_version_warning() -> None:
    a, b = _arms()
    comparison = compare_records(a, b, label_a="istat", label_b="base")
    assert comparison.avviso_versioni_istat == ""


def test_old_json_without_warning_is_readable() -> None:
    """The new field has a default: a comparison JSON written before is readable."""
    a, b = _arms()
    data = json.loads(to_json(compare_records(a, b, label_a="istat", label_b="base")))
    del data["avviso_versioni_istat"]
    assert Comparison.model_validate(data).avviso_versioni_istat == ""


def test_without_istat_no_note_on_the_reduced_text() -> None:
    a = [_rec("x", z, istat=False) for z in ("Colosseo", "Termini")]
    b = [_rec("y", z, istat=False) for z in ("Colosseo", "Termini")]
    assert ISTAT_M1_REDUCED_TEXT not in to_markdown(
        compare_records(a, b, label_a="x", label_b="y")
    )


@pytest.mark.parametrize("arm", ["a", "b"])
def test_an_arm_with_istat_metrics_of_different_versions_is_rejected(
    arm: str,
) -> None:
    """#369: M1 of the ISTAT records of different versions is graded on different texts;
    averaging them in the same arm would give a number that measures nothing."""
    with_istat = [
        _rec("istat", "Colosseo", istat=True),
        _rec("istat", "Termini", istat=True).model_copy(
            update={"istat_metrics": _istat_metrics(4)}
        ),
    ]
    without_istat = [_rec("base", z, istat=False) for z in ("Colosseo", "Termini")]
    a, b = (with_istat, without_istat) if arm == "a" else (without_istat, with_istat)
    with pytest.raises(ValueError, match=r"`istat`.*versioni.*\[2, 4\]"):
        compare_records(
            a,
            b,
            label_a="istat" if arm == "a" else "base",
            label_b="base" if arm == "a" else "istat",
        )


def test_records_without_istat_metrics_do_not_count_as_a_version() -> None:
    """A zone without ISTAT rows in the prompt has no ISTAT metrics: the arm
    stays of a single version."""
    a, b = _arms()
    a[1] = a[1].model_copy(update={"istat_metrics": None})
    comparison = compare_records(a, b, label_a="istat", label_b="base")
    assert len(comparison.istat_metrics) == 1


def test_comparisons_without_istat_stay_identical() -> None:
    a = [_rec("x", z, istat=False) for z in ("Colosseo", "Termini")]
    b = [_rec("y", z, istat=False, hallucination=0.4) for z in ("Colosseo", "Termini")]
    comparison = compare_records(a, b, label_a="x", label_b="y")
    assert comparison.isolated_variable == ""
    assert comparison.istat_metrics == []
    assert comparison.quality_verdict.applicable is True
    assert "Metriche ISTAT" not in to_markdown(comparison)


def _with_budget(
    records: list[RunRecord], budget: int | None, max_tokens: int | None = 1536
) -> list[RunRecord]:
    return [
        r.model_copy(
            update={
                "provenance": r.provenance.model_copy(
                    update={
                        "request_token_budget": budget,
                        "llm_max_tokens": max_tokens,
                    }
                )
            }
        )
        for r in records
    ]


def test_different_budget_makes_the_istat_pair_not_isolated() -> None:
    """F8 (final review): an old record (budget 10000, or not recorded)
    against a new one with ISTAT (8700) does not isolate ISTAT."""
    a, b = _arms()
    for budget_b in (10000, None):
        comparison = compare_records(
            _with_budget(a, 8700),
            _with_budget(b, budget_b),
            label_a="istat",
            label_b="base",
        )
        assert comparison.isolated_variable.startswith(CONFOUNDED_VARIABLE_HEAD)
        assert "budget di token della richiesta" in comparison.isolated_variable


def test_different_max_tokens_makes_the_istat_pair_not_isolated() -> None:
    a, b = _arms()
    comparison = compare_records(
        _with_budget(a, 8700, 1536),
        _with_budget(b, 8700, 2048),
        label_a="istat",
        label_b="base",
    )
    assert comparison.isolated_variable.startswith(CONFOUNDED_VARIABLE_HEAD)
    assert "max_tokens" in comparison.isolated_variable


def test_same_budget_the_istat_pair_stays_isolated() -> None:
    a, b = _arms()
    comparison = compare_records(
        _with_budget(a, 8700), _with_budget(b, 8700), label_a="istat", label_b="base"
    )
    assert comparison.isolated_variable.startswith(ISTAT_ISOLATED_VARIABLE_HEAD)


def test_different_budget_makes_the_ontology_pair_not_isolated() -> None:
    """The same check holds for the ontology vs without-ontology pair."""
    a = [_rec("con", z, istat=False) for z in ("Colosseo", "Termini")]
    b = [
        _rec("senza", z, istat=False, mode="no_ontology_prompt")
        for z in ("Colosseo", "Termini")
    ]
    confounded = compare_records(
        _with_budget(a, 10000), _with_budget(b, 8700), label_a="con", label_b="senza"
    )
    assert confounded.isolated_variable.startswith(CONFOUNDED_VARIABLE_HEAD)
    assert "budget di token della richiesta" in confounded.isolated_variable
    isolated = compare_records(
        _with_budget(a, 8700), _with_budget(b, 8700), label_a="con", label_b="senza"
    )
    assert not isolated.isolated_variable.startswith(CONFOUNDED_VARIABLE_HEAD)


def test_version_1_record_without_the_new_fields() -> None:
    """#365: on records written with #345 the version 2 fields are n/d."""
    a, b = _arms()
    old_records = [
        r.model_copy(
            update={
                "istat_metrics": IstatMetrics.model_validate(
                    {
                        k: v
                        for k, v in _istat_metrics().model_dump().items()
                        if k
                        not in {
                            "versione",
                            "cifre_istat",
                            "confronti_totali",
                            "confronti_coerenti",
                        }
                    }
                )
            }
        )
        for r in a
    ]
    md = to_markdown(compare_records(old_records, b, label_a="istat", label_b="base"))
    assert (
        "| Roma | Colosseo | 1 | n/d | 2/3 | 2/2 | n/d | 1 | 1/1 | n/d | 0 | 0 | n/d "
        "| n/d " in md
    )
