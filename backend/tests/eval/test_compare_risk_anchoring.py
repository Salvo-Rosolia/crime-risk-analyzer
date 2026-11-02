"""Section "Ancoraggio ai rischi (esplorativo)" of the comparison reports (#359).

Computed at report time from the data already in the records (narrative,
``risk_models``): it also applies to records written before #359.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crime_risk_analyzer.eval.compare import (
    M1_VERSIONS_DIFFER_HEAD,
    RISK_ANCHORING_HEAD,
    RISK_ANCHORING_ISTAT_EXCLUDED,
    RISK_ANCHORING_ISTAT_INCLUDED,
    Comparison,
    compare_records,
    risk_anchoring_pointer,
    to_json,
    to_markdown,
)
from crime_risk_analyzer.eval.harness import make_run_id, write_record
from crime_risk_analyzer.eval.repeated_comparison import build_repeated_report
from crime_risk_analyzer.eval.schema import (
    IstatMetrics,
    Metrics,
    Mode,
    Provenance,
    RunRecord,
    RunStatus,
)
from crime_risk_analyzer.rag.generation import RiskItem, RiskModel

_MODELS = [
    RiskModel(
        poi_id="1",
        poi="Banca X",
        risks=[
            RiskItem(
                hazard="Bank_robbery",
                confidence="verificato",
                tag="ONTOLOGIA",
                hazard_label_it="Rapina in banca",
                hazard_label_en="Bank robbery",
            )
        ],
    )
]


_POINTER_MARK = "le frasi ancorate solo da un nome di punto superano"


_ISTAT = IstatMetrics(
    versione=2,
    cifre_totali=0,
    cifre_istat=0,
    frasi_scartabili=0,
    voci_fornite=1,
    voci_citate=0,
    frasi_istat=0,
    frasi_istat_con_luogo=0,
    direzioni_totali=0,
    direzioni_coerenti=0,
    corrispondenze_non_dichiarate=0,
    numeri_in_lettere=0,
)


def _onto(body: str) -> str:
    return f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{body}"


def _synth(body: str) -> str:
    return f"Sintesi.\n\nRischi dalla sintesi del modello [SINTESI-LLM]\n{body}"


def _rec(
    experiment: str,
    zona: str,
    narrativa: str,
    *,
    mode: Mode,
    rep: int = 0,
    status: RunStatus = RunStatus.OK,
    risk_models: list[RiskModel] | None = None,
    istat: bool = False,
) -> RunRecord:
    return RunRecord(
        run_id=make_run_id(experiment, "Roma", zona, mode, "groq", rep),
        experiment=experiment,
        citta="Roma",
        zona=zona,
        mode=mode,
        model_id="openai/gpt-oss-120b",
        status=status,
        metrics=Metrics(
            grounding=0.5,
            hallucination=0.5,
            quality_vacuous=False,
            latency_ms=100,
            cost_usd=0.001,
        ),
        narrativa=narrativa,
        n_poi=1,
        risk_models=_MODELS if risk_models is None else risk_models,
        poi_nel_prompt=["1"],
        istat_metrics=_ISTAT if istat else None,
        provenance=Provenance(
            code_commit="c",
            ontology_hash="o",
            snapshot_id=f"roma__{zona}".lower(),
            model_id="openai/gpt-oss-120b",
            prompt_hash="p",
            temperature=0.0,
            seed=rep,
            experiment=experiment,
            istat=istat,
        ),
    )


def _arms() -> tuple[list[RunRecord], list[RunRecord]]:
    with_ontology = [
        _rec(
            "con",
            "Colosseo",
            _onto("Possibile rapina in banca. Zona frequentata."),
            mode="analyze",
        ),
        _rec(
            "con",
            "Termini",
            _onto("Alla Banca X rapina in banca. La Banca X e' aperta."),
            mode="analyze",
        ),
    ]
    without_ontology = [
        _rec(
            "senza",
            "Colosseo",
            _synth("La Banca X attira persone. Folla."),
            mode="no_ontology_prompt",
        ),
        # Full narrative without the measured block: not conforming to the format.
        _rec("senza", "Termini", "Testo senza blocco.", mode="no_ontology_prompt"),
    ]
    return with_ontology, without_ontology


def test_section_per_zone_and_arm() -> None:
    with_ontology, without_ontology = _arms()
    cmp = compare_records(
        with_ontology, without_ontology, label_a="con", label_b="senza"
    )
    section = cmp.ancoraggio_rischi
    assert section is not None
    colosseo, termini = section.zones
    assert (colosseo.zona, termini.zona) == ("Colosseo", "Termini")
    assert colosseo.a.frasi_misurate == 2
    assert colosseo.a.frasi_ancorate_rischio == 1
    assert colosseo.a.frasi_ancorate_solo_poi == 0
    assert colosseo.a.ancoraggio_rischi == pytest.approx(0.5)
    assert termini.a.frasi_ancorate_rischio == 1
    assert termini.a.frasi_ancorate_solo_poi == 1
    assert (
        colosseo.a.frasi_ancorate_poi_e_rischio,
        termini.a.frasi_ancorate_poi_e_rischio,
    ) == (0, 1)
    assert colosseo.b.quota_solo_poi == pytest.approx(0.5)
    assert colosseo.b.quota_rischio == 0.0
    # Not conforming: counted apart, 0 sentences, anchoring 0.0, undefined shares.
    assert termini.b.non_conformi == 1
    assert termini.b.frasi_misurate == 0
    assert termini.b.ancoraggio_rischi == 0.0
    assert termini.b.quota_rischio is None
    # Whole arm: totals summed, shares on the sentences, means over the zones.
    assert section.a.frasi_misurate == 4
    assert section.a.frasi_ancorate_rischio == 2
    assert section.a.frasi_ancorate_solo_poi == 1
    assert section.a.frasi_ancorate_poi_e_rischio == 1
    assert section.a.quota_rischio == pytest.approx(0.5)
    assert section.a.quota_solo_poi == pytest.approx(0.25)
    assert section.a.ancoraggio_rischi == pytest.approx(0.5)
    assert section.a.frasi_misurate_media == pytest.approx(2.0)
    assert section.b.frasi_misurate_media == pytest.approx(1.0)
    assert section.b.non_conformi == 1
    assert section.b.ancoraggio_rischi == 0.0
    assert section.solo_poi_prevale == ["senza"]


def test_markdown_carries_section_numbers_and_note() -> None:
    with_ontology, without_ontology = _arms()
    md = to_markdown(
        compare_records(with_ontology, without_ontology, label_a="con", label_b="senza")
    )
    assert RISK_ANCHORING_HEAD in md
    assert "ancoraggio_rischi solo conformi" in md
    assert (
        "| Roma | Colosseo | con | 1 | 2.0 | 50.0% | 0.0% | 0.500 | 0.500 | 0 |" in md
    )
    assert "| Roma | Termini | senza | 1 | 0.0 | n/d | n/d | 0.000 | n/d | 1 |" in md
    assert "| MEDIA |  | con | 2 | 2.0 | 50.0% | 25.0% | 0.500 | 0.500 | 0 |" in md
    assert "| MEDIA |  | senza | 2 | 1.0 | 0.0% | 50.0% | 0.000 | 0.000 | 1 |" in md
    assert "nomi dei POI" in md
    # The anchored sentences of M1 are only POI + POI and risk: the text adds them up.
    assert (
        "`con`: 4 misurate, 2 da rischio, 1 solo POI, 1 POI e rischio; "
        "`senza`: 2 misurate, 0 da rischio, 1 solo POI, 0 POI e rischio." in md
    )
    # How it aggregates, said in one sentence.
    assert "frasi del braccio messe insieme, narrative non conformi escluse" in md
    assert "narrative gradabili, comprese le non conformi" in md
    # The wrong caveat (the POIs without risks are in risk_models) is no longer there.
    assert "un punto senza rischi non conta" not in md
    assert "circolare" in md
    assert "annotazione umana" in md
    # The section precedes the methodological note on the proxies.
    assert md.index(RISK_ANCHORING_HEAD) < md.index("Nota metodologica")


def test_json_carries_the_section() -> None:
    with_ontology, without_ontology = _arms()
    cmp = compare_records(
        with_ontology, without_ontology, label_a="con", label_b="senza"
    )
    data = json.loads(cmp.model_dump_json())
    assert data["ancoraggio_rischi"]["b"]["non_conformi"] == 1
    assert data["ancoraggio_rischi"]["solo_poi_prevale"] == ["senza"]


def test_m1_and_verdict_unchanged() -> None:
    with_ontology, without_ontology = _arms()
    cmp = compare_records(
        with_ontology, without_ontology, label_a="con", label_b="senza"
    )
    assert cmp.mean_a.grounding == 0.5
    assert cmp.quality_verdict.applicable is True


def test_pointer_line_only_when_poi_only_prevails() -> None:
    with_ontology, without_ontology = _arms()
    cmp = compare_records(
        with_ontology, without_ontology, label_a="con", label_b="senza"
    )
    line = risk_anchoring_pointer(cmp)
    assert line == (
        "> Per «senza» le frasi ancorate solo da un nome di punto superano "
        "quelle che nominano un punto e un rischio: vedi la sezione «Ancoraggio ai "
        "rischi (esplorativo)»."
    )
    tied = compare_records(with_ontology, with_ontology, label_a="con", label_b="con2")
    assert risk_anchoring_pointer(tied) == ""


def test_tie_does_not_trigger_the_pointer() -> None:
    # 1 POI-only sentence and 1 with point and risk: "exceeds" is strict.
    a = [
        _rec(
            "a",
            "Colosseo",
            _onto("Alla Banca X rapina in banca. La Banca X e' aperta."),
            mode="analyze",
        )
    ]
    cmp = compare_records(a, a, label_a="a", label_b="b")
    assert cmp.ancoraggio_rischi is not None
    assert cmp.ancoraggio_rischi.a.frasi_ancorate_solo_poi == 1
    assert cmp.ancoraggio_rischi.a.frasi_ancorate_poi_e_rischio == 1
    assert cmp.ancoraggio_rischi.solo_poi_prevale == []


def test_risk_sentence_without_point_does_not_count_against_poi_only() -> None:
    # #408: "from risk" includes sentences without POI, which M1 does not count as
    # anchored. With only 1 POI-only sentence and none with point and risk, the POI-only
    # prevails among the anchored sentences even if there are many risk sentences
    # without a point.
    a = [
        _rec(
            "a",
            "Colosseo",
            _onto("Rapina in banca. Possibile rapina in banca. La Banca X e' aperta."),
            mode="analyze",
        )
    ]
    cmp = compare_records(a, a, label_a="a", label_b="b")
    section = cmp.ancoraggio_rischi
    assert section is not None
    assert section.a.frasi_ancorate_rischio == 2
    assert section.a.frasi_ancorate_poi_e_rischio == 0
    assert section.solo_poi_prevale == ["a", "b"]


def test_non_ok_records_excluded() -> None:
    with_ontology, without_ontology = _arms()
    extra = _rec(
        "senza",
        "Colosseo",
        _synth("La Banca X. La Banca X. La Banca X."),
        mode="no_ontology_prompt",
        rep=1,
        status=RunStatus.FALLBACK,
    )
    cmp = compare_records(
        with_ontology,
        without_ontology,
        label_a="con",
        label_b="senza",
        anchoring_records=(with_ontology, [*without_ontology, extra]),
    )
    assert cmp.ancoraggio_rischi is not None
    assert cmp.ancoraggio_rischi.zones[0].b.frasi_misurate == 2


def test_old_records_without_new_fields() -> None:
    # Record written before #349/#345 and without #77 labels: minimal dictionary.
    old = _rec("v", "Colosseo", _onto("Rapina in banca."), mode="analyze")
    raw = json.loads(old.model_dump_json())
    for key in ("poi_nel_prompt", "narrativa_grezza", "istat_metrics"):
        raw.pop(key)
    for risk in raw["risk_models"][0]["risks"]:
        risk.pop("hazard_label_it")
        risk.pop("hazard_label_en")
    legacy = RunRecord.model_validate(raw)
    cmp = compare_records([legacy], [legacy], label_a="a", label_b="b")
    assert cmp.ancoraggio_rischi is not None
    # The missing labels are rebuilt from the vocabulary (#77) on reading.
    assert cmp.ancoraggio_rischi.zones[0].a.frasi_ancorate_rischio == 1
    assert cmp.ancoraggio_rischi.zones[0].a.frasi_misurate == 1


def test_records_without_anchors_not_gradable() -> None:
    without_risks = [
        _rec("x", "Colosseo", _onto("Testo."), mode="analyze", risk_models=[])
    ]
    cmp = compare_records(without_risks, without_risks, label_a="a", label_b="b")
    # No gradable narrative in any arm: no section.
    assert cmp.ancoraggio_rischi is None
    assert RISK_ANCHORING_HEAD not in to_markdown(cmp)


def _repeated(tmp_path: Path, without_body: str) -> str:
    records = [
        _rec(
            "con", "Colosseo", _onto("Possibile rapina in banca. Zona."), mode="analyze"
        ),
        _rec("con", "Colosseo", _onto("Rapina in banca."), mode="analyze", rep=1),
        _rec("senza", "Colosseo", _synth(without_body), mode="no_ontology_prompt"),
        _rec(
            "senza", "Colosseo", _synth(without_body), mode="no_ontology_prompt", rep=1
        ),
    ]
    for rec in records:
        write_record(tmp_path, rec)
    md_path, json_path = build_repeated_report(
        tmp_path, "con", "senza", label_a="con", label_b="senza"
    )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    section = data["comparison"]["ancoraggio_rischi"]
    # Computed on the repetitions, not on the mean-record (which has no risks).
    assert section["zones"][0]["a"]["narrative_gradabili"] == 2
    assert section["zones"][0]["a"]["frasi_misurate"] == 3
    assert section["zones"][0]["a"]["ancoraggio_rischi"] == pytest.approx(0.75)
    return md_path.read_text(encoding="utf-8")


def test_repeated_report_points_to_the_section_near_the_verdict(
    tmp_path: Path,
) -> None:
    md = _repeated(tmp_path, "La Banca X attira persone. Folla.")
    assert RISK_ANCHORING_HEAD in md
    verdict = md.index("### Esito del criterio proxy")
    line = md.index(_POINTER_MARK)
    assert line > verdict
    # Only once: in the repeated report the pointer sits only next to the verdict.
    assert md.count(_POINTER_MARK) == 1


def test_repeated_report_without_pointer(tmp_path: Path) -> None:
    md = _repeated(tmp_path, "Rapina in banca alla Banca X. Folla.")
    assert RISK_ANCHORING_HEAD in md
    assert _POINTER_MARK not in md


def test_pointer_one_line_per_arm() -> None:
    _, without_ontology = _arms()
    cmp = compare_records(
        without_ontology, without_ontology, label_a="s1", label_b="s2"
    )
    lines = [r for r in risk_anchoring_pointer(cmp).splitlines() if r]
    assert len(lines) == 2
    assert lines[0].startswith("> Per «s1» le frasi ancorate")
    assert lines[1].startswith("> Per «s2» le frasi ancorate")


def test_anchoring_conforming_only_excludes_the_non_conforming() -> None:
    # Two repetitions: one conforming (1 risk sentence out of 2), one not conforming.
    conforming = _rec("c", "Colosseo", _onto("Rapina in banca. Folla."), mode="analyze")
    non_conforming = _rec("c", "Colosseo", "Testo libero.", mode="analyze", rep=1)
    cmp = compare_records(
        [conforming],
        [conforming],
        label_a="a",
        label_b="b",
        anchoring_records=([conforming, non_conforming], [conforming]),
    )
    section = cmp.ancoraggio_rischi
    assert section is not None
    zone_a = section.zones[0].a
    assert zone_a.ancoraggio_rischi == pytest.approx(0.25)
    assert zone_a.ancoraggio_rischi_conformi == pytest.approx(0.5)
    assert section.a.ancoraggio_rischi_conformi == pytest.approx(0.5)
    assert section.b.ancoraggio_rischi_conformi == pytest.approx(0.5)


def test_only_non_conforming_conforming_column_undefined() -> None:
    _, without_ontology = _arms()
    cmp = compare_records(without_ontology, without_ontology, label_a="a", label_b="b")
    assert cmp.ancoraggio_rischi is not None
    assert cmp.ancoraggio_rischi.zones[1].a.ancoraggio_rischi_conformi is None


def test_runs_with_istat_excluded_from_the_section() -> None:
    # Version 2: from these records the text measured by M1 cannot be rebuilt.
    with_ontology, without_ontology = _arms()
    with_istat = [r.model_copy(update={"istat_metrics": _ISTAT}) for r in with_ontology]
    cmp = compare_records(
        with_ontology,
        without_ontology,
        label_a="istat",
        label_b="senza",
        anchoring_records=(with_istat, without_ontology),
    )
    section = cmp.ancoraggio_rischi
    assert section is not None
    assert section.a.narrative_gradabili == 0
    assert section.a.run_istat_escluse == 2
    assert section.a.run_istat_incluse == 0
    assert section.b.run_istat_escluse == 0
    assert section.b.narrative_gradabili == 2
    md = to_markdown(cmp)
    assert f"> {RISK_ANCHORING_ISTAT_EXCLUDED} (run escluse — `istat`: 2)." in md
    assert "versione 4" in RISK_ANCHORING_ISTAT_EXCLUDED
    assert "misurato dal `grounding`" in RISK_ANCHORING_ISTAT_EXCLUDED
    assert "`narrativa_grezza`" in RISK_ANCHORING_ISTAT_EXCLUDED
    assert "`frasi_escluse_m1`" in RISK_ANCHORING_ISTAT_EXCLUDED
    assert RISK_ANCHORING_ISTAT_INCLUDED not in md


def test_all_runs_with_istat_the_section_says_so() -> None:
    rec = _rec("i", "Colosseo", _onto("Rapina in banca."), mode="analyze", istat=True)
    cmp = compare_records([rec], [rec], label_a="a", label_b="b")
    assert cmp.ancoraggio_rischi is not None
    assert cmp.ancoraggio_rischi.a.run_istat_escluse == 1
    assert RISK_ANCHORING_ISTAT_EXCLUDED in to_markdown(cmp)


def test_without_istat_no_sentence_about_istat_runs() -> None:
    with_ontology, without_ontology = _arms()
    cmp = compare_records(
        with_ontology, without_ontology, label_a="con", label_b="senza"
    )
    md = to_markdown(cmp)
    assert RISK_ANCHORING_ISTAT_EXCLUDED not in md
    assert RISK_ANCHORING_ISTAT_INCLUDED not in md
    assert cmp.ancoraggio_rischi is not None
    assert cmp.ancoraggio_rischi.a.run_istat_incluse == 0
    assert cmp.ancoraggio_rischi.a.frasi_istat_escluse == 0


# --- ISTAT version 4 runs: included on the text measured by M1 (#377) --------

_ISTAT_V4 = _ISTAT.model_copy(update={"versione": 4})

#: ISTAT sentence without POI nor risk: M1 excludes it and the record saves it.
_ISTAT_SENTENCE = "Secondo l'ISTAT i furti sono in calo"

#: Raw model text: 1 risk sentence, 1 POI-only, 1 not anchored, 1 ISTAT.
_RAW = _onto(
    f"Rapina in banca alla Banca X. La Banca X e' aperta. Folla. {_ISTAT_SENTENCE}."
)

#: Filtered narrative (shown to the operator): different from the raw text, so the
#: tests see which text the section measures.
_FILTERED = _onto("Rapina in banca alla Banca X. Folla.")


def _rec_istat_v4(
    zona: str = "Colosseo",
    *,
    experiment: str = "i4",
    rep: int = 0,
    raw: str | None = _RAW,
    excluded: list[str] | None = None,
) -> RunRecord:
    rec = _rec(experiment, zona, _FILTERED, mode="analyze", rep=rep, istat=True)
    sentences = [_ISTAT_SENTENCE] if excluded is None else excluded
    # Like the harness: the count of the ISTAT metrics is the length of the list.
    v4_metrics = _ISTAT_V4.model_copy(update={"frasi_escluse_m1": len(sentences)})
    return rec.model_copy(
        update={
            "istat_metrics": v4_metrics,
            "narrativa_grezza": raw,
            "frasi_escluse_m1": sentences,
        }
    )


def test_istat_v4_runs_included_on_the_text_measured_by_m1() -> None:
    rec = _rec_istat_v4()
    cmp = compare_records([rec], [rec], label_a="a", label_b="b")
    section = cmp.ancoraggio_rischi
    assert section is not None
    zone_a = section.zones[0].a
    # Raw text without the excluded ISTAT sentence: 3 sentences, not the 2 of the
    # filtered one nor the 4 of the whole raw text.
    assert zone_a.narrative_gradabili == 1
    assert zone_a.frasi_misurate == 3
    assert zone_a.frasi_ancorate_rischio == 1
    assert zone_a.frasi_ancorate_solo_poi == 1
    assert zone_a.ancoraggio_rischi == pytest.approx(1 / 3)
    assert zone_a.run_istat_incluse == 1
    assert zone_a.run_istat_escluse == 0
    assert zone_a.frasi_istat_escluse == 1
    assert section.a.run_istat_incluse == 1
    assert section.a.frasi_istat_escluse == 1


def test_mixed_arm_sums_only_the_reconstructible_runs() -> None:
    without_istat = _rec("i4", "Colosseo", _onto("Rapina in banca."), mode="analyze")
    v4 = _rec_istat_v4(rep=1)
    v2 = _rec("i4", "Colosseo", _onto("Folla."), mode="analyze", rep=2, istat=True)
    # v4 without the raw text or without the excluded sentences: it cannot be rebuilt.
    without_raw = _rec_istat_v4(rep=3, raw=None)
    without_excluded = _rec_istat_v4(rep=4).model_copy(
        update={"frasi_escluse_m1": None}
    )
    runs = [without_istat, v4, v2, without_raw, without_excluded]
    cmp = compare_records(
        [without_istat],
        [without_istat],
        label_a="a",
        label_b="b",
        anchoring_records=(runs, [without_istat]),
    )
    section = cmp.ancoraggio_rischi
    assert section is not None
    assert section.a.narrative_gradabili == 2
    assert section.a.frasi_misurate == 1 + 3
    assert section.a.frasi_ancorate_rischio == 1 + 1
    assert section.a.frasi_ancorate_solo_poi == 0 + 1
    assert section.a.run_istat_incluse == 1
    assert section.a.run_istat_escluse == 3
    assert section.a.frasi_istat_escluse == 1
    assert section.b.run_istat_incluse == 0
    md = to_markdown(cmp)
    assert RISK_ANCHORING_ISTAT_INCLUDED in md
    assert f"> {RISK_ANCHORING_ISTAT_EXCLUDED} (run escluse — `a`: 3)." in md


def test_markdown_warning_included_istat_runs_with_excluded_sentences_per_arm() -> None:
    a = [_rec_istat_v4(), _rec_istat_v4("Termini")]
    b = [
        _rec_istat_v4(experiment="i4b"),
        _rec_istat_v4("Termini", experiment="i4b", raw=_onto("Rapina."), excluded=[]),
    ]
    cmp = compare_records(a, b, label_a="a", label_b="b")
    md = to_markdown(cmp)
    assert RISK_ANCHORING_ISTAT_INCLUDED in md
    assert (
        "> Run con dati ISTAT nella sezione — `a`: 2 run, 2 frasi ISTAT escluse; "
        "`b`: 2 run, 1 frase ISTAT esclusa."
    ) in md
    # The ISTAT table counts the same excluded sentences as the records.
    # The fixture does not have the count of the excluded without item (#378): n/d.
    without_count = "di cui n/d senza voce ISTAT del prompt (record senza il conteggio)"
    assert (
        f"> Frasi escluse da M1 — `a`: 2 frasi escluse, {without_count}; "
        f"`b`: 1 frasi escluse, {without_count}."
    ) in md
    assert RISK_ANCHORING_ISTAT_EXCLUDED not in md
    # The warning says that the measured text has ISTAT mentions in words, and that the
    # ISTAT rows of the prompt carry the labels of the linked risks.
    assert "a parole" in RISK_ANCHORING_ISTAT_INCLUDED
    assert "«Collegata a: ...»" in RISK_ANCHORING_ISTAT_INCLUDED
    assert "da rischio" in RISK_ANCHORING_ISTAT_INCLUDED
    section = md[md.index(RISK_ANCHORING_HEAD) :]
    assert section.index(RISK_ANCHORING_ISTAT_INCLUDED) < section.index(
        "Come leggere questa sezione"
    )


def test_json_carries_included_istat_runs_and_excluded_sentences() -> None:
    rec = _rec_istat_v4()
    cmp = compare_records([rec], [rec], label_a="a", label_b="b")
    data = json.loads(cmp.model_dump_json())
    section = data["ancoraggio_rischi"]
    assert section["a"]["run_istat_incluse"] == 1
    assert section["a"]["frasi_istat_escluse"] == 1
    assert section["zones"][0]["b"]["frasi_misurate"] == 3


def test_istat_v4_run_verdict_and_m1_unchanged() -> None:
    rec = _rec_istat_v4()
    old = rec.model_copy(update={"istat_metrics": _ISTAT})
    new = compare_records([rec], [rec], label_a="a", label_b="b")
    before = compare_records([old], [old], label_a="a", label_b="b")
    assert new.mean_a == before.mean_a
    assert new.mean_delta == before.mean_delta
    assert new.quality_verdict == before.quality_verdict


def test_istat_v4_record_read_from_json() -> None:
    raw = json.loads(_rec_istat_v4().model_dump_json())
    rec = RunRecord.model_validate(raw)
    cmp = compare_records([rec], [rec], label_a="a", label_b="b")
    assert cmp.ancoraggio_rischi is not None
    assert cmp.ancoraggio_rischi.a.frasi_misurate == 3


def test_repeated_report_includes_the_istat_v4_runs(tmp_path: Path) -> None:
    records = [
        _rec_istat_v4(experiment=exp, rep=rep)
        for exp in ("i4", "i4b")
        for rep in (0, 1)
    ]
    for rec in records:
        write_record(tmp_path, rec)
    md_path, json_path = build_repeated_report(
        tmp_path, "i4", "i4b", label_a="a", label_b="b"
    )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    section = data["comparison"]["ancoraggio_rischi"]
    assert section["a"]["run_istat_incluse"] == 2
    assert section["a"]["frasi_istat_escluse"] == 2
    assert section["a"]["frasi_misurate"] == 6
    assert RISK_ANCHORING_ISTAT_INCLUDED in md_path.read_text(encoding="utf-8")


def test_istat_v3_run_excluded_even_with_raw_text_and_excluded_sentences() -> None:
    """Before version 4 M1 excluded other sentences: even if the record has the
    two fields, the text measured then is not raw text minus these sentences."""
    v3 = _rec_istat_v4().model_copy(
        update={"istat_metrics": _ISTAT_V4.model_copy(update={"versione": 3})}
    )
    cmp = compare_records([v3], [v3], label_a="a", label_b="b")
    assert cmp.ancoraggio_rischi is not None
    assert cmp.ancoraggio_rischi.a.run_istat_escluse == 1
    assert cmp.ancoraggio_rischi.a.run_istat_incluse == 0
    assert cmp.ancoraggio_rischi.a.narrative_gradabili == 0


def test_inconsistent_istat_v4_run_excluded_without_failing_the_report(
    tmp_path: Path,
) -> None:
    """An excluded sentence that is not among the sentences of the raw text
    (inconsistent record): the run stays out of the section like the other
    non-reconstructible ones, the report is generated."""
    altered = _ISTAT_SENTENCE.replace("calo", "aumento")
    broken = _rec_istat_v4(rep=1, excluded=[altered])
    good = _rec_istat_v4(rep=0)
    cmp = compare_records(
        [good],
        [good],
        label_a="a",
        label_b="b",
        anchoring_records=([good, broken], [good]),
    )
    section = cmp.ancoraggio_rischi
    assert section is not None
    assert section.a.run_istat_escluse == 1
    assert section.a.run_istat_incluse == 1
    assert section.a.narrative_gradabili == 1
    assert section.a.frasi_istat_escluse == 1
    md = to_markdown(cmp)
    assert f"> {RISK_ANCHORING_ISTAT_EXCLUDED} (run escluse — `a`: 1)." in md
    # The repeated report is generated too.
    for rec in (broken, good, _rec_istat_v4(experiment="i4b")):
        write_record(tmp_path, rec)
    md_path, json_path = build_repeated_report(
        tmp_path, "i4", "i4b", label_a="a", label_b="b"
    )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["comparison"]["ancoraggio_rischi"]["a"]["run_istat_escluse"] == 1
    assert RISK_ANCHORING_ISTAT_EXCLUDED in md_path.read_text(encoding="utf-8")


def _m1_version(rec: RunRecord, version: int | None) -> RunRecord:
    metrics = rec.metrics.model_copy(update={"versione": version})
    return rec.model_copy(update={"metrics": metrics})


def test_metrics_without_version_count_as_not_recorded() -> None:
    # Records written before #408: the M1 version is not known (it was 1, 2 or 3).
    assert (
        Metrics(grounding=1.0, hallucination=0.0, latency_ms=0, cost_usd=0.0).versione
        is None
    )


def test_arms_with_different_m1_versions_have_a_warning() -> None:
    with_ontology, without_ontology = _arms()
    with_ontology = [_m1_version(r, 2) for r in with_ontology]
    without_ontology = [_m1_version(r, 3) for r in without_ontology]
    cmp = compare_records(
        with_ontology, without_ontology, label_a="con", label_b="senza"
    )
    assert cmp.avviso_versioni_m1.startswith(M1_VERSIONS_DIFFER_HEAD)
    assert "`con`: versione 2; `senza`: versione 3" in cmp.avviso_versioni_m1
    md = to_markdown(cmp)
    assert md.index(M1_VERSIONS_DIFFER_HEAD) < md.index("| citta |")
    assert json.loads(to_json(cmp))["avviso_versioni_m1"] == cmp.avviso_versioni_m1


def test_same_m1_version_no_warning() -> None:
    with_ontology, without_ontology = _arms()
    with_ontology = [_m1_version(r, 3) for r in with_ontology]
    without_ontology = [_m1_version(r, 3) for r in without_ontology]
    cmp = compare_records(
        with_ontology, without_ontology, label_a="con", label_b="senza"
    )
    assert cmp.avviso_versioni_m1 == ""
    assert M1_VERSIONS_DIFFER_HEAD not in to_markdown(cmp)
    # Even if none is recorded (records all pre-#408): nothing to signal.
    assert compare_records(*_arms(), label_a="a", label_b="b").avviso_versioni_m1 == ""


def test_unrecorded_m1_version_against_recorded_is_flagged() -> None:
    with_ontology, without_ontology = _arms()
    without_ontology = [_m1_version(r, 3) for r in without_ontology]
    cmp = compare_records(
        with_ontology, without_ontology, label_a="con", label_b="senza"
    )
    assert "`con`: versione n/d; `senza`: versione 3" in cmp.avviso_versioni_m1


def test_mixed_m1_versions_within_an_arm_are_flagged_without_rejecting() -> None:
    # Unlike ISTAT (#369) the comparison does not reject: it warns.
    with_ontology, without_ontology = _arms()
    extra = _m1_version(
        _rec("con", "Colosseo", _onto("Rapina in banca."), mode="analyze", rep=1), 2
    )
    with_ontology = [_m1_version(r, 3) for r in with_ontology]
    cmp = compare_records(
        with_ontology,
        without_ontology,
        label_a="con",
        label_b="senza",
        anchoring_records=([*with_ontology, extra], without_ontology),
    )
    assert "`con`: versione 2, 3" in cmp.avviso_versioni_m1


def test_version_of_excluded_records_does_not_count() -> None:
    with_ontology, without_ontology = _arms()
    fallback = _m1_version(
        _rec(
            "senza",
            "Colosseo",
            _synth("La Banca X."),
            mode="no_ontology_prompt",
            rep=1,
            status=RunStatus.FALLBACK,
        ),
        1,
    )
    cmp = compare_records(
        with_ontology,
        without_ontology,
        label_a="con",
        label_b="senza",
        anchoring_records=(with_ontology, [*without_ontology, fallback]),
    )
    assert cmp.avviso_versioni_m1 == ""


def test_zone_discarded_in_one_arm_does_not_count_for_m1_versions() -> None:
    # Colosseo: v2 in A but FALLBACK in B -> zone in `failed`, not compared.
    with_ontology, without_ontology = _arms()
    with_ontology = [
        _m1_version(r, 3) if r.zona != "Colosseo" else _m1_version(r, 2)
        for r in with_ontology
    ]
    without_ontology = [
        _m1_version(r, 3)
        if r.zona != "Colosseo"
        else _m1_version(r.model_copy(update={"status": RunStatus.FALLBACK}), 3)
        for r in without_ontology
    ]
    cmp = compare_records(
        with_ontology, without_ontology, label_a="con", label_b="senza"
    )
    assert [f.zona for f in cmp.failed] == ["Colosseo"]
    assert cmp.avviso_versioni_m1 == ""


def test_zone_discarded_with_repetitions_does_not_count_for_m1_versions() -> None:
    with_ontology, without_ontology = _arms()
    with_ontology = [
        _m1_version(r, 3) if r.zona != "Colosseo" else _m1_version(r, 2)
        for r in with_ontology
    ]
    without_ontology = [
        _m1_version(r, 3)
        if r.zona != "Colosseo"
        else _m1_version(r.model_copy(update={"status": RunStatus.FALLBACK}), 3)
        for r in without_ontology
    ]
    # Extra OK repetition of the discarded zone, at v2: it stays out of the set.
    extra = _m1_version(
        _rec("con", "Colosseo", _onto("Rapina in banca."), mode="analyze", rep=1), 2
    )
    cmp = compare_records(
        with_ontology,
        without_ontology,
        label_a="con",
        label_b="senza",
        anchoring_records=([*with_ontology, extra], without_ontology),
    )
    assert cmp.avviso_versioni_m1 == ""


def _vacuous(rec: RunRecord) -> RunRecord:
    metrics = rec.metrics.model_copy(update={"quality_vacuous": True})
    return rec.model_copy(update={"metrics": metrics})


def test_vacuous_baseline_at_old_version_does_not_trigger_the_warning() -> None:
    with_ontology, without_ontology = _arms()
    with_ontology = [_vacuous(_m1_version(r, 2)) for r in with_ontology]
    without_ontology = [_m1_version(r, 3) for r in without_ontology]
    cmp = compare_records(
        with_ontology, without_ontology, label_a="con", label_b="senza"
    )
    assert cmp.avviso_versioni_m1 == ""


def test_excluded_vacuous_record_does_not_hide_a_real_disagreement() -> None:
    with_ontology, without_ontology = _arms()
    with_ontology = [_m1_version(r, 2) for r in with_ontology]
    with_ontology[0] = _vacuous(_m1_version(with_ontology[0], 1))
    without_ontology = [_m1_version(r, 3) for r in without_ontology]
    cmp = compare_records(
        with_ontology, without_ontology, label_a="con", label_b="senza"
    )
    assert "`con`: versione 2; `senza`: versione 3" in cmp.avviso_versioni_m1


def test_n_a_warning_says_it_is_unknown_whether_versions_differ() -> None:
    with_ontology, without_ontology = _arms()
    without_ontology = [_m1_version(r, 3) for r in without_ontology]
    warning = compare_records(
        with_ontology, without_ontology, label_a="con", label_b="senza"
    ).avviso_versioni_m1
    assert "non si sa se le versioni differiscano davvero" in warning
    assert "falso allarme" in warning
    assert "rigirare" not in warning


def test_warning_with_known_different_versions_suggests_rerunning() -> None:
    with_ontology, without_ontology = _arms()
    with_ontology = [_m1_version(r, 2) for r in with_ontology]
    without_ontology = [_m1_version(r, 3) for r in without_ontology]
    warning = compare_records(
        with_ontology, without_ontology, label_a="con", label_b="senza"
    ).avviso_versioni_m1
    assert "rigirare i bracci con lo stesso codice" in warning
    assert "falso allarme" not in warning


def test_old_json_without_m1_warning_is_readable() -> None:
    with_ontology, without_ontology = _arms()
    data = json.loads(
        to_json(
            compare_records(with_ontology, without_ontology, label_a="a", label_b="b")
        )
    )
    del data["avviso_versioni_m1"]
    assert Comparison.model_validate(data).avviso_versioni_m1 == ""
