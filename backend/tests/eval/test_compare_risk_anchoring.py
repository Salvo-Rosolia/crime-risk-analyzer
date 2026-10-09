"""Sezione «Ancoraggio ai rischi (esplorativo)» dei report di confronto (#359).

Calcolata al momento del report dai dati gia' nei record (narrativa,
``risk_models``): si applica anche ai record scritti prima di #359.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crime_risk_analyzer.eval.compare import (
    RISK_ANCHORING_HEAD,
    compare_records,
    risk_anchoring_pointer,
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


_POINTER_MARK = "il grounding poggia soprattutto sui nomi dei punti"


_ISTAT = IstatMetrics(
    cifre_totali=0,
    cifre_istat_corrette=0,
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
    con = [
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
    senza = [
        _rec(
            "senza",
            "Colosseo",
            _synth("La Banca X attira persone. Folla."),
            mode="no_ontology_prompt",
        ),
        # Narrativa piena senza il blocco misurato: non conforme al formato.
        _rec("senza", "Termini", "Testo senza blocco.", mode="no_ontology_prompt"),
    ]
    return con, senza


def test_sezione_per_zona_e_braccio() -> None:
    con, senza = _arms()
    cmp = compare_records(con, senza, label_a="con", label_b="senza")
    sez = cmp.ancoraggio_rischi
    assert sez is not None
    colosseo, termini = sez.zones
    assert (colosseo.zona, termini.zona) == ("Colosseo", "Termini")
    assert colosseo.a.frasi_misurate == 2
    assert colosseo.a.frasi_ancorate_rischio == 1
    assert colosseo.a.frasi_ancorate_solo_poi == 0
    assert colosseo.a.ancoraggio_rischi == pytest.approx(0.5)
    assert termini.a.frasi_ancorate_rischio == 1
    assert termini.a.frasi_ancorate_solo_poi == 1
    assert colosseo.b.quota_solo_poi == pytest.approx(0.5)
    assert colosseo.b.quota_rischio == 0.0
    # Non conforme: contato a parte, 0 frasi, ancoraggio 0.0, quote non definite.
    assert termini.b.non_conformi == 1
    assert termini.b.frasi_misurate == 0
    assert termini.b.ancoraggio_rischi == 0.0
    assert termini.b.quota_rischio is None
    # Braccio intero: totali sommati, quote sulle frasi, medie sulle zone.
    assert sez.a.frasi_misurate == 4
    assert sez.a.frasi_ancorate_rischio == 2
    assert sez.a.frasi_ancorate_solo_poi == 1
    assert sez.a.quota_rischio == pytest.approx(0.5)
    assert sez.a.quota_solo_poi == pytest.approx(0.25)
    assert sez.a.ancoraggio_rischi == pytest.approx(0.5)
    assert sez.a.frasi_misurate_media == pytest.approx(2.0)
    assert sez.b.frasi_misurate_media == pytest.approx(1.0)
    assert sez.b.non_conformi == 1
    assert sez.b.ancoraggio_rischi == 0.0
    assert sez.solo_poi_prevale == ["senza"]


def test_markdown_porta_sezione_numeri_e_nota() -> None:
    con, senza = _arms()
    md = to_markdown(compare_records(con, senza, label_a="con", label_b="senza"))
    assert RISK_ANCHORING_HEAD in md
    assert "ancoraggio_rischi solo conformi" in md
    assert (
        "| Roma | Colosseo | con | 1 | 2.0 | 50.0% | 0.0% | 0.500 | 0.500 | 0 |" in md
    )
    assert "| Roma | Termini | senza | 1 | 0.0 | n/d | n/d | 0.000 | n/d | 1 |" in md
    assert "| MEDIA |  | con | 2 | 2.0 | 50.0% | 25.0% | 0.500 | 0.500 | 0 |" in md
    assert "| MEDIA |  | senza | 2 | 1.0 | 0.0% | 50.0% | 0.000 | 0.000 | 1 |" in md
    assert "nomi dei POI" in md
    # Come si aggrega, detto in una frase.
    assert "frasi del braccio messe insieme, narrative non conformi escluse" in md
    assert "narrative gradabili, comprese le non conformi" in md
    # Il caveat sbagliato (i POI senza rischi ci sono in risk_models) non c'e' piu'.
    assert "un punto senza rischi non conta" not in md
    assert "circolare" in md
    assert "annotazione umana" in md
    # La sezione precede la nota metodologica sui proxy.
    assert md.index(RISK_ANCHORING_HEAD) < md.index("Nota metodologica")


def test_json_porta_la_sezione() -> None:
    con, senza = _arms()
    cmp = compare_records(con, senza, label_a="con", label_b="senza")
    data = json.loads(cmp.model_dump_json())
    assert data["ancoraggio_rischi"]["b"]["non_conformi"] == 1
    assert data["ancoraggio_rischi"]["solo_poi_prevale"] == ["senza"]


def test_m1_e_verdetto_invariati() -> None:
    con, senza = _arms()
    cmp = compare_records(con, senza, label_a="con", label_b="senza")
    assert cmp.mean_a.grounding == 0.5
    assert cmp.quality_verdict.applicable is True


def test_riga_di_rimando_solo_quando_il_solo_poi_prevale() -> None:
    con, senza = _arms()
    cmp = compare_records(con, senza, label_a="con", label_b="senza")
    riga = risk_anchoring_pointer(cmp)
    assert riga == (
        "> Per «senza» il grounding poggia soprattutto sui nomi dei punti e non "
        "sui rischi della base di conoscenza: vedi la sezione «Ancoraggio ai "
        "rischi (esplorativo)»."
    )
    pari = compare_records(con, con, label_a="con", label_b="con2")
    assert risk_anchoring_pointer(pari) == ""


def test_parita_non_fa_scattare_il_rimando() -> None:
    # 1 frase da rischio e 1 solo POI: "supera" e' stretto.
    a = [
        _rec(
            "a",
            "Colosseo",
            _onto("Rapina in banca. La Banca X e' aperta."),
            mode="analyze",
        )
    ]
    cmp = compare_records(a, a, label_a="a", label_b="b")
    assert cmp.ancoraggio_rischi is not None
    assert cmp.ancoraggio_rischi.solo_poi_prevale == []


def test_record_non_ok_esclusi() -> None:
    con, senza = _arms()
    extra = _rec(
        "senza",
        "Colosseo",
        _synth("La Banca X. La Banca X. La Banca X."),
        mode="no_ontology_prompt",
        rep=1,
        status=RunStatus.FALLBACK,
    )
    cmp = compare_records(
        con,
        senza,
        label_a="con",
        label_b="senza",
        anchoring_records=(con, [*senza, extra]),
    )
    assert cmp.ancoraggio_rischi is not None
    assert cmp.ancoraggio_rischi.zones[0].b.frasi_misurate == 2


def test_record_vecchi_senza_campi_nuovi() -> None:
    # Record scritto prima di #349/#345 e senza etichette #77: dizionario minimo.
    vecchio = _rec("v", "Colosseo", _onto("Rapina in banca."), mode="analyze")
    raw = json.loads(vecchio.model_dump_json())
    for chiave in ("poi_nel_prompt", "narrativa_grezza", "istat_metrics"):
        raw.pop(chiave)
    for risk in raw["risk_models"][0]["risks"]:
        risk.pop("hazard_label_it")
        risk.pop("hazard_label_en")
    legacy = RunRecord.model_validate(raw)
    cmp = compare_records([legacy], [legacy], label_a="a", label_b="b")
    assert cmp.ancoraggio_rischi is not None
    # Le etichette mancanti sono ricostruite dal vocabolario (#77) alla lettura.
    assert cmp.ancoraggio_rischi.zones[0].a.frasi_ancorate_rischio == 1
    assert cmp.ancoraggio_rischi.zones[0].a.frasi_misurate == 1


def test_record_senza_ancoraggi_non_gradabili() -> None:
    senza_rischi = [
        _rec("x", "Colosseo", _onto("Testo."), mode="analyze", risk_models=[])
    ]
    cmp = compare_records(senza_rischi, senza_rischi, label_a="a", label_b="b")
    # Nessuna narrativa gradabile in nessun braccio: niente sezione.
    assert cmp.ancoraggio_rischi is None
    assert RISK_ANCHORING_HEAD not in to_markdown(cmp)


def _repeated(tmp_path: Path, senza_body: str) -> str:
    records = [
        _rec(
            "con", "Colosseo", _onto("Possibile rapina in banca. Zona."), mode="analyze"
        ),
        _rec("con", "Colosseo", _onto("Rapina in banca."), mode="analyze", rep=1),
        _rec("senza", "Colosseo", _synth(senza_body), mode="no_ontology_prompt"),
        _rec("senza", "Colosseo", _synth(senza_body), mode="no_ontology_prompt", rep=1),
    ]
    for rec in records:
        write_record(tmp_path, rec)
    md_path, json_path = build_repeated_report(
        tmp_path, "con", "senza", label_a="con", label_b="senza"
    )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    sez = data["comparison"]["ancoraggio_rischi"]
    # Calcolata sulle ripetizioni, non sul record-media (che non ha i rischi).
    assert sez["zones"][0]["a"]["narrative_gradabili"] == 2
    assert sez["zones"][0]["a"]["frasi_misurate"] == 3
    assert sez["zones"][0]["a"]["ancoraggio_rischi"] == pytest.approx(0.75)
    return md_path.read_text(encoding="utf-8")


def test_report_ripetuto_rimanda_alla_sezione_vicino_al_verdetto(
    tmp_path: Path,
) -> None:
    md = _repeated(tmp_path, "La Banca X attira persone. Folla.")
    assert RISK_ANCHORING_HEAD in md
    verdetto = md.index("### Esito del criterio proxy")
    riga = md.index(_POINTER_MARK)
    assert riga > verdetto
    # Una sola volta: nel report ripetuto il rimando sta solo vicino al verdetto.
    assert md.count(_POINTER_MARK) == 1


def test_report_ripetuto_senza_rimando(tmp_path: Path) -> None:
    md = _repeated(tmp_path, "Rapina in banca alla Banca X. Folla.")
    assert RISK_ANCHORING_HEAD in md
    assert _POINTER_MARK not in md


def test_rimando_una_riga_per_braccio() -> None:
    _, senza = _arms()
    cmp = compare_records(senza, senza, label_a="s1", label_b="s2")
    righe = [r for r in risk_anchoring_pointer(cmp).splitlines() if r]
    assert len(righe) == 2
    assert righe[0].startswith("> Per «s1» il grounding")
    assert righe[1].startswith("> Per «s2» il grounding")


def test_ancoraggio_solo_conformi_esclude_le_non_conformi() -> None:
    # Due ripetizioni: una conforme (1 frase da rischio su 2), una non conforme.
    conforme = _rec("c", "Colosseo", _onto("Rapina in banca. Folla."), mode="analyze")
    non_conforme = _rec("c", "Colosseo", "Testo libero.", mode="analyze", rep=1)
    cmp = compare_records(
        [conforme],
        [conforme],
        label_a="a",
        label_b="b",
        anchoring_records=([conforme, non_conforme], [conforme]),
    )
    sez = cmp.ancoraggio_rischi
    assert sez is not None
    zona = sez.zones[0].a
    assert zona.ancoraggio_rischi == pytest.approx(0.25)
    assert zona.ancoraggio_rischi_conformi == pytest.approx(0.5)
    assert sez.a.ancoraggio_rischi_conformi == pytest.approx(0.5)
    assert sez.b.ancoraggio_rischi_conformi == pytest.approx(0.5)


def test_solo_non_conformi_colonna_conformi_non_definita() -> None:
    _, senza = _arms()
    cmp = compare_records(senza, senza, label_a="a", label_b="b")
    assert cmp.ancoraggio_rischi is not None
    assert cmp.ancoraggio_rischi.zones[1].a.ancoraggio_rischi_conformi is None


def test_run_con_istat_escluse_dalla_sezione() -> None:
    con, senza = _arms()
    con_istat = [r.model_copy(update={"istat_metrics": _ISTAT}) for r in con]
    cmp = compare_records(
        con,
        senza,
        label_a="istat",
        label_b="senza",
        anchoring_records=(con_istat, senza),
    )
    sez = cmp.ancoraggio_rischi
    assert sez is not None
    assert sez.a.narrative_gradabili == 0
    assert sez.a.run_istat_escluse == 2
    assert sez.b.run_istat_escluse == 0
    assert sez.b.narrative_gradabili == 2
    md = to_markdown(cmp)
    assert "Sezione non calcolata per le run con dati ISTAT" in md
    assert "la metrica attuale misura un testo diverso" in md


def test_tutte_le_run_con_istat_la_sezione_lo_dice() -> None:
    rec = _rec("i", "Colosseo", _onto("Rapina in banca."), mode="analyze", istat=True)
    cmp = compare_records([rec], [rec], label_a="a", label_b="b")
    assert cmp.ancoraggio_rischi is not None
    assert cmp.ancoraggio_rischi.a.run_istat_escluse == 1
    assert "Sezione non calcolata per le run con dati ISTAT" in to_markdown(cmp)


def test_senza_istat_nessuna_frase_sulle_run_istat() -> None:
    con, senza = _arms()
    md = to_markdown(compare_records(con, senza, label_a="con", label_b="senza"))
    assert "Sezione non calcolata per le run con dati ISTAT" not in md
