"""Confronto ontologia vs ontologia + ISTAT (#345, spec 4.9 / D12)."""

from __future__ import annotations

from crime_risk_analyzer.eval.compare import (
    CONFOUNDED_VARIABLE_HEAD,
    ISTAT_ISOLATED_VARIABLE_HEAD,
    ISTAT_NO_WINNER_REASON,
    compare_records,
    is_istat_isolating_pair,
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


def _metriche_istat() -> IstatMetrics:
    return IstatMetrics(
        cifre_totali=4,
        cifre_istat_corrette=3,
        precisione_cifre=0.75,
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
    assert (
        "| Roma | Colosseo | 0.75 | 2/3 | 1 | 1/1 | 0 | 0 | - | - | - | - | - | - |"
        in md
    )


def test_confronti_senza_istat_restano_identici() -> None:
    a = [_rec("x", z, istat=False) for z in ("Colosseo", "Termini")]
    b = [_rec("y", z, istat=False, hallucination=0.4) for z in ("Colosseo", "Termini")]
    confronto = compare_records(a, b, label_a="x", label_b="y")
    assert confronto.isolated_variable == ""
    assert confronto.istat_metrics == []
    assert confronto.quality_verdict.applicable is True
    assert "Metriche ISTAT" not in to_markdown(confronto)
