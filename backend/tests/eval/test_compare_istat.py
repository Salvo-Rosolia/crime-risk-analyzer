"""Confronto ontologia vs ontologia + ISTAT (#345, spec 4.9 / D12)."""

from __future__ import annotations

import json

import pytest

from crime_risk_analyzer.eval.compare import (
    CONFOUNDED_VARIABLE_HEAD,
    ISTAT_ESCLUSE_SENZA_VOCE_TEXT,
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


def _metriche_istat(
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
    esperimento: str,
    zona: str,
    *,
    istat: bool,
    mode: Mode = "analyze",
    modello: str = "openai/gpt-oss-120b",
    hallucination: float = 0.2,
) -> RunRecord:
    return RunRecord(
        run_id=f"{esperimento}__roma__{zona}".lower(),
        experiment=esperimento,
        citta="Roma",
        zona=zona,
        mode=mode,
        model_id=modello,
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
        # #349: record con i POI nel prompt, come quelli che l'harness scrive oggi.
        poi_nel_prompt=["1"],
        istat_metrics=_metriche_istat() if istat else None,
        provenance=Provenance(
            code_commit="c",
            ontology_hash="o",
            snapshot_id=f"roma__{zona}".lower(),
            model_id=modello,
            prompt_hash="p",
            temperature=0.0,
            seed=0,
            experiment=esperimento,
            istat=istat,
        ),
    )


def _bracci(**kw_b: object) -> tuple[list[RunRecord], list[RunRecord]]:
    a = [_rec("istat", z, istat=True) for z in ("Colosseo", "Termini")]
    b = [
        _rec("base", z, istat=False, hallucination=0.4) for z in ("Colosseo", "Termini")
    ]
    if kw_b:
        b = [r.model_copy(update=kw_b) for r in b]
    return a, b


def test_coppia_istat_riconosciuta() -> None:
    a, b = _bracci()
    assert is_istat_isolating_pair(a, b) and is_istat_isolating_pair(b, a)
    assert not is_istat_isolating_pair(a, a)
    stessi = [_rec("x", "Colosseo", istat=False)]
    assert not is_istat_isolating_pair(stessi, stessi)


def test_nota_variabile_isolata_e_nessun_vincitore() -> None:
    a, b = _bracci()
    confronto = compare_records(a, b, label_a="istat", label_b="base")
    assert confronto.isolated_variable.startswith(ISTAT_ISOLATED_VARIABLE_HEAD)
    assert "`istat` lo riceve, `base` no" in confronto.isolated_variable
    assert confronto.quality_verdict.applicable is False
    assert confronto.quality_verdict.reason == ISTAT_NO_WINNER_REASON


def test_impostazioni_diverse_dichiarano_la_variabile_non_isolata() -> None:
    a, _ = _bracci()
    b = [
        _rec("base", z, istat=False, modello="claude-sonnet-4-6")
        for z in ("Colosseo", "Termini")
    ]
    confronto = compare_records(a, b, label_a="istat", label_b="base")
    assert confronto.isolated_variable.startswith(CONFOUNDED_VARIABLE_HEAD)
    assert "modello" in confronto.isolated_variable


def test_coppia_ontologica_con_istat_diverso_non_e_isolata() -> None:
    """ISTAT e' un'impostazione condivisa nel confronto della tesi (D6)."""
    a = [_rec("con", z, istat=True) for z in ("Colosseo", "Termini")]
    b = [
        _rec("senza", z, istat=False, mode="no_ontology_prompt")
        for z in ("Colosseo", "Termini")
    ]
    confronto = compare_records(a, b, label_a="con", label_b="senza")
    assert confronto.isolated_variable.startswith(CONFOUNDED_VARIABLE_HEAD)
    assert "dati ISTAT nel prompt" in confronto.isolated_variable


def test_metriche_istat_affiancate_nel_report() -> None:
    a, b = _bracci()
    confronto = compare_records(a, b, label_a="istat", label_b="base")
    assert [
        (z.zona, z.a is not None, z.b is None) for z in confronto.istat_metrics
    ] == [
        ("Colosseo", True, True),
        ("Termini", True, True),
    ]
    md = to_markdown(confronto)
    assert "### Metriche ISTAT (affiancate, nessun vincitore)" in md
    # Versione 2: le frasi escluse da M1 (#369) non esistevano.
    assert (
        "| Roma | Colosseo | 2 | 1 | 2/3 | 2/2 | 0 | 1 | 1/1 | 1/2 | 0 | 0 | 0 | n/d "
        "| - | - | - | - | - | - | - | - | - | - | - | - |" in md
    )


def test_report_dice_che_m1_con_istat_e_su_un_testo_ridotto() -> None:
    """#369: il braccio con ISTAT e' gradato su un testo ridotto; il report lo
    dice, con quante frasi sono escluse e il limite del rischio inventato."""
    a, b = _bracci()
    a = [r.model_copy(update={"istat_metrics": _metriche_istat(4, 3)}) for r in a]
    md = to_markdown(compare_records(a, b, label_a="istat", label_b="base"))
    assert (
        "| Roma | Colosseo | 4 | 1 | 2/3 | 2/2 | 0 | 1 | 1/1 | 1/2 | 0 | 0 | 0 | 3 |"
        in md
    )
    assert ISTAT_M1_REDUCED_TEXT in md
    assert "`istat`: 6 frasi escluse" in md
    sezione = md.split("### Metriche ISTAT")[1]
    assert sezione.index(ISTAT_M1_REDUCED_TEXT) < sezione.index("Nota metodologica")


def _con_senza_voce(senza_voce: tuple[int | None, int | None]) -> Comparison:
    a, b = _bracci()
    a = [
        r.model_copy(update={"istat_metrics": _metriche_istat(4, 3, n)})
        for r, n in zip(a, senza_voce, strict=True)
    ]
    return compare_records(a, b, label_a="istat", label_b="base")


def test_report_conta_a_parte_le_escluse_senza_voce_del_prompt() -> None:
    """#378: accanto alle frasi escluse, quante non nominano una voce delle righe
    ISTAT del prompt; la nota dice che sono candidate da leggere a mano."""
    confronto = _con_senza_voce((1, 0))
    md = to_markdown(confronto)
    assert (
        "> Frasi escluse da M1 — `istat`: 6 frasi escluse, di cui 1 senza voce "
        "ISTAT del prompt." in md
    )
    assert ISTAT_ESCLUSE_SENZA_VOCE_TEXT in md
    sezione = md.split("### Metriche ISTAT")[1]
    assert (
        sezione.index(ISTAT_M1_REDUCED_TEXT)
        < sezione.index(ISTAT_ESCLUSE_SENZA_VOCE_TEXT)
        < sezione.index("Nota metodologica")
    )
    zone = json.loads(to_json(confronto))["istat_metrics"]
    assert [z["a"]["frasi_escluse_senza_voce"] for z in zone] == [1, 0]


def test_escluse_senza_voce_non_toccano_m1_ne_il_verdetto() -> None:
    con, senza = _con_senza_voce((2, 1)), _con_senza_voce((None, None))
    assert con.model_dump(exclude={"istat_metrics"}) == senza.model_dump(
        exclude={"istat_metrics"}
    )


def test_record_senza_il_conteggio_delle_escluse_senza_voce() -> None:
    """Basta una zona scritta prima di #378: il totale del braccio e' n/d."""
    md = to_markdown(_con_senza_voce((1, None)))
    assert (
        "`istat`: 6 frasi escluse, di cui n/d senza voce ISTAT del prompt (record "
        "senza il conteggio)." in md
    )


def test_la_nota_dichiara_i_pezzi_dello_splitter_di_m1() -> None:
    """#369, C1: i pezzi che M1 ricava da "d.lgs. 7/2016" o "134.169" restano
    misurati come non ancorati; la nota lo dice."""
    assert ISTAT_M1_SPLITTER_LIMIT in ISTAT_M1_REDUCED_TEXT
    a, b = _bracci()
    md = to_markdown(compare_records(a, b, label_a="istat", label_b="base"))
    assert "«d.lgs. 7/2016» o «134.169»" in md


def test_bracci_con_istat_di_versioni_diverse_hanno_un_avviso() -> None:
    """#369, D2: due bracci con ISTAT di versioni diverse si confrontano, ma il
    report avvisa prima delle tabelle che M1 e' gradato con regole diverse."""
    vecchio = [_rec("v3", z, istat=True) for z in ("Colosseo", "Termini")]
    vecchio = [
        r.model_copy(update={"istat_metrics": _metriche_istat(3)}) for r in vecchio
    ]
    nuovo = [
        _rec("v4", z, istat=True).model_copy(
            update={"istat_metrics": _metriche_istat(4, 1)}
        )
        for z in ("Colosseo", "Termini")
    ]
    confronto = compare_records(vecchio, nuovo, label_a="v3", label_b="v4")
    avviso = confronto.avviso_versioni_istat
    assert avviso.startswith(ISTAT_VERSIONS_DIFFER_HEAD)
    assert "`v3`: versione 3; `v4`: versione 4" in avviso
    md = to_markdown(confronto)
    assert md.index(ISTAT_VERSIONS_DIFFER_HEAD) < md.index("| citta |")
    # Campo del modello (punto 4 della review): il JSON porta lo stesso avviso.
    assert json.loads(to_json(confronto))["avviso_versioni_istat"] == avviso
    stessa = compare_records(nuovo, nuovo, label_a="x", label_b="y")
    assert stessa.avviso_versioni_istat == ""
    assert ISTAT_VERSIONS_DIFFER_HEAD not in to_markdown(stessa)
    assert json.loads(to_json(stessa))["avviso_versioni_istat"] == ""


def test_un_solo_braccio_con_istat_nessun_avviso_di_versione() -> None:
    a, b = _bracci()
    confronto = compare_records(a, b, label_a="istat", label_b="base")
    assert confronto.avviso_versioni_istat == ""


def test_json_vecchio_senza_avviso_si_legge() -> None:
    """Il campo nuovo ha un default: un JSON di confronto scritto prima si legge."""
    a, b = _bracci()
    dati = json.loads(to_json(compare_records(a, b, label_a="istat", label_b="base")))
    del dati["avviso_versioni_istat"]
    assert Comparison.model_validate(dati).avviso_versioni_istat == ""


def test_senza_istat_nessuna_nota_sul_testo_ridotto() -> None:
    a = [_rec("x", z, istat=False) for z in ("Colosseo", "Termini")]
    b = [_rec("y", z, istat=False) for z in ("Colosseo", "Termini")]
    assert ISTAT_M1_REDUCED_TEXT not in to_markdown(
        compare_records(a, b, label_a="x", label_b="y")
    )


@pytest.mark.parametrize("braccio", ["a", "b"])
def test_un_braccio_con_metriche_istat_di_versioni_diverse_e_rifiutato(
    braccio: str,
) -> None:
    """#369: M1 dei record ISTAT di versioni diverse e' gradato su testi diversi;
    mediarli nello stesso braccio darebbe un numero che non misura nulla."""
    con = [
        _rec("istat", "Colosseo", istat=True),
        _rec("istat", "Termini", istat=True).model_copy(
            update={"istat_metrics": _metriche_istat(4)}
        ),
    ]
    senza = [_rec("base", z, istat=False) for z in ("Colosseo", "Termini")]
    a, b = (con, senza) if braccio == "a" else (senza, con)
    with pytest.raises(ValueError, match=r"`istat`.*versioni.*\[2, 4\]"):
        compare_records(
            a,
            b,
            label_a="istat" if braccio == "a" else "base",
            label_b="base" if braccio == "a" else "istat",
        )


def test_record_senza_metriche_istat_non_contano_come_una_versione() -> None:
    """Una zona senza righe ISTAT nel prompt non ha metriche ISTAT: il braccio
    resta di una sola versione."""
    a, b = _bracci()
    a[1] = a[1].model_copy(update={"istat_metrics": None})
    confronto = compare_records(a, b, label_a="istat", label_b="base")
    assert len(confronto.istat_metrics) == 1


def test_confronti_senza_istat_restano_identici() -> None:
    a = [_rec("x", z, istat=False) for z in ("Colosseo", "Termini")]
    b = [_rec("y", z, istat=False, hallucination=0.4) for z in ("Colosseo", "Termini")]
    confronto = compare_records(a, b, label_a="x", label_b="y")
    assert confronto.isolated_variable == ""
    assert confronto.istat_metrics == []
    assert confronto.quality_verdict.applicable is True
    assert "Metriche ISTAT" not in to_markdown(confronto)


def _con_budget(
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


def test_budget_diverso_rende_la_coppia_istat_non_isolata() -> None:
    """F8 (review finale): un record vecchio (budget 10000, o non registrato)
    contro uno nuovo con ISTAT (8700) non isola ISTAT."""
    a, b = _bracci()
    for budget_b in (10000, None):
        confronto = compare_records(
            _con_budget(a, 8700),
            _con_budget(b, budget_b),
            label_a="istat",
            label_b="base",
        )
        assert confronto.isolated_variable.startswith(CONFOUNDED_VARIABLE_HEAD)
        assert "budget di token della richiesta" in confronto.isolated_variable


def test_max_tokens_diverso_rende_la_coppia_istat_non_isolata() -> None:
    a, b = _bracci()
    confronto = compare_records(
        _con_budget(a, 8700, 1536),
        _con_budget(b, 8700, 2048),
        label_a="istat",
        label_b="base",
    )
    assert confronto.isolated_variable.startswith(CONFOUNDED_VARIABLE_HEAD)
    assert "max_tokens" in confronto.isolated_variable


def test_stesso_budget_la_coppia_istat_resta_isolata() -> None:
    a, b = _bracci()
    confronto = compare_records(
        _con_budget(a, 8700), _con_budget(b, 8700), label_a="istat", label_b="base"
    )
    assert confronto.isolated_variable.startswith(ISTAT_ISOLATED_VARIABLE_HEAD)


def test_budget_diverso_rende_la_coppia_ontologica_non_isolata() -> None:
    """Lo stesso controllo vale per la coppia ontologia vs senza ontologia."""
    a = [_rec("con", z, istat=False) for z in ("Colosseo", "Termini")]
    b = [
        _rec("senza", z, istat=False, mode="no_ontology_prompt")
        for z in ("Colosseo", "Termini")
    ]
    confuso = compare_records(
        _con_budget(a, 10000), _con_budget(b, 8700), label_a="con", label_b="senza"
    )
    assert confuso.isolated_variable.startswith(CONFOUNDED_VARIABLE_HEAD)
    assert "budget di token della richiesta" in confuso.isolated_variable
    isolato = compare_records(
        _con_budget(a, 8700), _con_budget(b, 8700), label_a="con", label_b="senza"
    )
    assert not isolato.isolated_variable.startswith(CONFOUNDED_VARIABLE_HEAD)


def test_record_di_versione_1_senza_i_campi_nuovi() -> None:
    """#365: sui record scritti con #345 i campi della versione 2 sono n/d."""
    a, b = _bracci()
    vecchi = [
        r.model_copy(
            update={
                "istat_metrics": IstatMetrics.model_validate(
                    {
                        k: v
                        for k, v in _metriche_istat().model_dump().items()
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
    md = to_markdown(compare_records(vecchi, b, label_a="istat", label_b="base"))
    assert (
        "| Roma | Colosseo | 1 | n/d | 2/3 | 2/2 | n/d | 1 | 1/1 | n/d | 0 | 0 | n/d "
        "| n/d " in md
    )
