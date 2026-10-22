"""Sezione «Ancoraggio ai rischi (esplorativo)» dei report di confronto (#359).

Calcolata al momento del report dai dati gia' nei record (narrativa,
``risk_models``): si applica anche ai record scritti prima di #359.
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
    assert (
        colosseo.a.frasi_ancorate_poi_e_rischio,
        termini.a.frasi_ancorate_poi_e_rischio,
    ) == (0, 1)
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
    assert sez.a.frasi_ancorate_poi_e_rischio == 1
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
    # Le frasi ancorate di M1 sono solo POI + POI e rischio: il testo li somma.
    assert (
        "`con`: 4 misurate, 2 da rischio, 1 solo POI, 1 POI e rischio; "
        "`senza`: 2 misurate, 0 da rischio, 1 solo POI, 0 POI e rischio." in md
    )
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
        "> Per «senza» le frasi ancorate solo da un nome di punto superano "
        "quelle che nominano un punto e un rischio: vedi la sezione «Ancoraggio ai "
        "rischi (esplorativo)»."
    )
    pari = compare_records(con, con, label_a="con", label_b="con2")
    assert risk_anchoring_pointer(pari) == ""


def test_parita_non_fa_scattare_il_rimando() -> None:
    # 1 frase solo POI e 1 con punto e rischio: "supera" e' stretto.
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


def test_frase_da_rischio_senza_punto_non_conta_contro_il_solo_poi() -> None:
    # #408: «da rischio» include frasi senza POI, che M1 non conta come ancorate.
    # Con 1 sola frase solo POI e nessuna con punto e rischio, il solo POI prevale
    # fra le frasi ancorate anche se ci sono molte frasi da rischio senza punto.
    a = [
        _rec(
            "a",
            "Colosseo",
            _onto("Rapina in banca. Possibile rapina in banca. La Banca X e' aperta."),
            mode="analyze",
        )
    ]
    cmp = compare_records(a, a, label_a="a", label_b="b")
    sez = cmp.ancoraggio_rischi
    assert sez is not None
    assert sez.a.frasi_ancorate_rischio == 2
    assert sez.a.frasi_ancorate_poi_e_rischio == 0
    assert sez.solo_poi_prevale == ["a", "b"]


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
    assert righe[0].startswith("> Per «s1» le frasi ancorate")
    assert righe[1].startswith("> Per «s2» le frasi ancorate")


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
    # Versione 2: da questi record il testo misurato da M1 non si ricostruisce.
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
    assert sez.a.run_istat_incluse == 0
    assert sez.b.run_istat_escluse == 0
    assert sez.b.narrative_gradabili == 2
    md = to_markdown(cmp)
    assert f"> {RISK_ANCHORING_ISTAT_EXCLUDED} (run escluse — `istat`: 2)." in md
    assert "versione 4" in RISK_ANCHORING_ISTAT_EXCLUDED
    assert "misurato dal `grounding`" in RISK_ANCHORING_ISTAT_EXCLUDED
    assert "`narrativa_grezza`" in RISK_ANCHORING_ISTAT_EXCLUDED
    assert "`frasi_escluse_m1`" in RISK_ANCHORING_ISTAT_EXCLUDED
    assert RISK_ANCHORING_ISTAT_INCLUDED not in md


def test_tutte_le_run_con_istat_la_sezione_lo_dice() -> None:
    rec = _rec("i", "Colosseo", _onto("Rapina in banca."), mode="analyze", istat=True)
    cmp = compare_records([rec], [rec], label_a="a", label_b="b")
    assert cmp.ancoraggio_rischi is not None
    assert cmp.ancoraggio_rischi.a.run_istat_escluse == 1
    assert RISK_ANCHORING_ISTAT_EXCLUDED in to_markdown(cmp)


def test_senza_istat_nessuna_frase_sulle_run_istat() -> None:
    con, senza = _arms()
    cmp = compare_records(con, senza, label_a="con", label_b="senza")
    md = to_markdown(cmp)
    assert RISK_ANCHORING_ISTAT_EXCLUDED not in md
    assert RISK_ANCHORING_ISTAT_INCLUDED not in md
    assert cmp.ancoraggio_rischi is not None
    assert cmp.ancoraggio_rischi.a.run_istat_incluse == 0
    assert cmp.ancoraggio_rischi.a.frasi_istat_escluse == 0


# --- Run con ISTAT di versione 4: incluse dal testo misurato da M1 (#377) --------

_ISTAT_V4 = _ISTAT.model_copy(update={"versione": 4})

#: Frase ISTAT senza POI ne' rischio: M1 la esclude e il record la salva.
_FRASE_ISTAT = "Secondo l'ISTAT i furti sono in calo"

#: Grezzo del modello: 1 frase da rischio, 1 solo POI, 1 non ancorata, 1 ISTAT.
_GREZZO = _onto(
    f"Rapina in banca alla Banca X. La Banca X e' aperta. Folla. {_FRASE_ISTAT}."
)

#: Narrativa filtrata (mostrata all'operatore): diversa dal grezzo, cosi' i
#: test vedono quale testo la sezione misura.
_FILTRATA = _onto("Rapina in banca alla Banca X. Folla.")


def _rec_istat_v4(
    zona: str = "Colosseo",
    *,
    experiment: str = "i4",
    rep: int = 0,
    grezzo: str | None = _GREZZO,
    escluse: list[str] | None = None,
) -> RunRecord:
    rec = _rec(experiment, zona, _FILTRATA, mode="analyze", rep=rep, istat=True)
    frasi = [_FRASE_ISTAT] if escluse is None else escluse
    # Come l'harness: il conteggio delle metriche ISTAT e' la lunghezza della lista.
    metriche = _ISTAT_V4.model_copy(update={"frasi_escluse_m1": len(frasi)})
    return rec.model_copy(
        update={
            "istat_metrics": metriche,
            "narrativa_grezza": grezzo,
            "frasi_escluse_m1": frasi,
        }
    )


def test_run_istat_v4_incluse_sul_testo_misurato_da_m1() -> None:
    rec = _rec_istat_v4()
    cmp = compare_records([rec], [rec], label_a="a", label_b="b")
    sez = cmp.ancoraggio_rischi
    assert sez is not None
    zona = sez.zones[0].a
    # Grezzo senza la frase ISTAT esclusa: 3 frasi, non le 2 della filtrata
    # ne' le 4 del grezzo intero.
    assert zona.narrative_gradabili == 1
    assert zona.frasi_misurate == 3
    assert zona.frasi_ancorate_rischio == 1
    assert zona.frasi_ancorate_solo_poi == 1
    assert zona.ancoraggio_rischi == pytest.approx(1 / 3)
    assert zona.run_istat_incluse == 1
    assert zona.run_istat_escluse == 0
    assert zona.frasi_istat_escluse == 1
    assert sez.a.run_istat_incluse == 1
    assert sez.a.frasi_istat_escluse == 1


def test_braccio_misto_somma_solo_le_run_ricostruibili() -> None:
    senza_istat = _rec("i4", "Colosseo", _onto("Rapina in banca."), mode="analyze")
    v4 = _rec_istat_v4(rep=1)
    v2 = _rec("i4", "Colosseo", _onto("Folla."), mode="analyze", rep=2, istat=True)
    # v4 senza il grezzo o senza le frasi escluse: non si ricostruisce.
    senza_grezzo = _rec_istat_v4(rep=3, grezzo=None)
    senza_escluse = _rec_istat_v4(rep=4).model_copy(update={"frasi_escluse_m1": None})
    runs = [senza_istat, v4, v2, senza_grezzo, senza_escluse]
    cmp = compare_records(
        [senza_istat],
        [senza_istat],
        label_a="a",
        label_b="b",
        anchoring_records=(runs, [senza_istat]),
    )
    sez = cmp.ancoraggio_rischi
    assert sez is not None
    assert sez.a.narrative_gradabili == 2
    assert sez.a.frasi_misurate == 1 + 3
    assert sez.a.frasi_ancorate_rischio == 1 + 1
    assert sez.a.frasi_ancorate_solo_poi == 0 + 1
    assert sez.a.run_istat_incluse == 1
    assert sez.a.run_istat_escluse == 3
    assert sez.a.frasi_istat_escluse == 1
    assert sez.b.run_istat_incluse == 0
    md = to_markdown(cmp)
    assert RISK_ANCHORING_ISTAT_INCLUDED in md
    assert f"> {RISK_ANCHORING_ISTAT_EXCLUDED} (run escluse — `a`: 3)." in md


def test_markdown_avviso_run_istat_incluse_con_frasi_escluse_per_braccio() -> None:
    a = [_rec_istat_v4(), _rec_istat_v4("Termini")]
    b = [
        _rec_istat_v4(experiment="i4b"),
        _rec_istat_v4("Termini", experiment="i4b", grezzo=_onto("Rapina."), escluse=[]),
    ]
    cmp = compare_records(a, b, label_a="a", label_b="b")
    md = to_markdown(cmp)
    assert RISK_ANCHORING_ISTAT_INCLUDED in md
    assert (
        "> Run con dati ISTAT nella sezione — `a`: 2 run, 2 frasi ISTAT escluse; "
        "`b`: 2 run, 1 frase ISTAT esclusa."
    ) in md
    # La tabella ISTAT conta le stesse frasi escluse dei record.
    # Il fixture non ha il conteggio delle escluse senza voce (#378): n/d.
    senza_conteggio = (
        "di cui n/d senza voce ISTAT del prompt (record senza il conteggio)"
    )
    assert (
        f"> Frasi escluse da M1 — `a`: 2 frasi escluse, {senza_conteggio}; "
        f"`b`: 1 frasi escluse, {senza_conteggio}."
    ) in md
    assert RISK_ANCHORING_ISTAT_EXCLUDED not in md
    # L'avviso dice che il testo misurato ha accenni ISTAT a parole, e che le
    # righe ISTAT del prompt portano le etichette dei rischi collegati.
    assert "a parole" in RISK_ANCHORING_ISTAT_INCLUDED
    assert "«Collegata a: ...»" in RISK_ANCHORING_ISTAT_INCLUDED
    assert "da rischio" in RISK_ANCHORING_ISTAT_INCLUDED
    sezione = md[md.index(RISK_ANCHORING_HEAD) :]
    assert sezione.index(RISK_ANCHORING_ISTAT_INCLUDED) < sezione.index(
        "Come leggere questa sezione"
    )


def test_json_porta_run_istat_incluse_e_frasi_escluse() -> None:
    rec = _rec_istat_v4()
    cmp = compare_records([rec], [rec], label_a="a", label_b="b")
    data = json.loads(cmp.model_dump_json())
    sez = data["ancoraggio_rischi"]
    assert sez["a"]["run_istat_incluse"] == 1
    assert sez["a"]["frasi_istat_escluse"] == 1
    assert sez["zones"][0]["b"]["frasi_misurate"] == 3


def test_run_istat_v4_verdetto_e_m1_invariati() -> None:
    rec = _rec_istat_v4()
    vecchio = rec.model_copy(update={"istat_metrics": _ISTAT})
    nuovo = compare_records([rec], [rec], label_a="a", label_b="b")
    prima = compare_records([vecchio], [vecchio], label_a="a", label_b="b")
    assert nuovo.mean_a == prima.mean_a
    assert nuovo.mean_delta == prima.mean_delta
    assert nuovo.quality_verdict == prima.quality_verdict


def test_record_istat_v4_letto_da_json() -> None:
    raw = json.loads(_rec_istat_v4().model_dump_json())
    rec = RunRecord.model_validate(raw)
    cmp = compare_records([rec], [rec], label_a="a", label_b="b")
    assert cmp.ancoraggio_rischi is not None
    assert cmp.ancoraggio_rischi.a.frasi_misurate == 3


def test_report_ripetuto_include_le_run_istat_v4(tmp_path: Path) -> None:
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
    sez = data["comparison"]["ancoraggio_rischi"]
    assert sez["a"]["run_istat_incluse"] == 2
    assert sez["a"]["frasi_istat_escluse"] == 2
    assert sez["a"]["frasi_misurate"] == 6
    assert RISK_ANCHORING_ISTAT_INCLUDED in md_path.read_text(encoding="utf-8")


def test_run_istat_v3_esclusa_anche_con_grezzo_e_frasi_escluse() -> None:
    """Prima della versione 4 M1 escludeva altre frasi: anche se il record ha i
    due campi, il testo misurato allora non e' grezzo meno queste frasi."""
    v3 = _rec_istat_v4().model_copy(
        update={"istat_metrics": _ISTAT_V4.model_copy(update={"versione": 3})}
    )
    cmp = compare_records([v3], [v3], label_a="a", label_b="b")
    assert cmp.ancoraggio_rischi is not None
    assert cmp.ancoraggio_rischi.a.run_istat_escluse == 1
    assert cmp.ancoraggio_rischi.a.run_istat_incluse == 0
    assert cmp.ancoraggio_rischi.a.narrative_gradabili == 0


def test_run_istat_v4_incoerente_esclusa_senza_far_fallire_il_report(
    tmp_path: Path,
) -> None:
    """Una frase esclusa che non e' fra le frasi del grezzo (record incoerente):
    la run resta fuori dalla sezione come le altre non ricostruibili, il report
    si genera."""
    alterata = _FRASE_ISTAT.replace("calo", "aumento")
    rotto = _rec_istat_v4(rep=1, escluse=[alterata])
    buono = _rec_istat_v4(rep=0)
    cmp = compare_records(
        [buono],
        [buono],
        label_a="a",
        label_b="b",
        anchoring_records=([buono, rotto], [buono]),
    )
    sez = cmp.ancoraggio_rischi
    assert sez is not None
    assert sez.a.run_istat_escluse == 1
    assert sez.a.run_istat_incluse == 1
    assert sez.a.narrative_gradabili == 1
    assert sez.a.frasi_istat_escluse == 1
    md = to_markdown(cmp)
    assert f"> {RISK_ANCHORING_ISTAT_EXCLUDED} (run escluse — `a`: 1)." in md
    # Anche il report ripetuto si genera.
    for rec in (rotto, buono, _rec_istat_v4(experiment="i4b")):
        write_record(tmp_path, rec)
    md_path, json_path = build_repeated_report(
        tmp_path, "i4", "i4b", label_a="a", label_b="b"
    )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["comparison"]["ancoraggio_rischi"]["a"]["run_istat_escluse"] == 1
    assert RISK_ANCHORING_ISTAT_EXCLUDED in md_path.read_text(encoding="utf-8")


def _versione_m1(rec: RunRecord, versione: int | None) -> RunRecord:
    metrics = rec.metrics.model_copy(update={"versione": versione})
    return rec.model_copy(update={"metrics": metrics})


def test_metriche_senza_versione_valgono_non_registrata() -> None:
    # Record scritti prima di #408: la versione di M1 non e' nota (era 1, 2 o 3).
    assert (
        Metrics(grounding=1.0, hallucination=0.0, latency_ms=0, cost_usd=0.0).versione
        is None
    )


def test_bracci_con_versioni_m1_diverse_hanno_un_avviso() -> None:
    con, senza = _arms()
    con = [_versione_m1(r, 2) for r in con]
    senza = [_versione_m1(r, 3) for r in senza]
    cmp = compare_records(con, senza, label_a="con", label_b="senza")
    assert cmp.avviso_versioni_m1.startswith(M1_VERSIONS_DIFFER_HEAD)
    assert "`con`: versione 2; `senza`: versione 3" in cmp.avviso_versioni_m1
    md = to_markdown(cmp)
    assert md.index(M1_VERSIONS_DIFFER_HEAD) < md.index("| citta |")
    assert json.loads(to_json(cmp))["avviso_versioni_m1"] == cmp.avviso_versioni_m1


def test_stessa_versione_m1_nessun_avviso() -> None:
    con, senza = _arms()
    con = [_versione_m1(r, 3) for r in con]
    senza = [_versione_m1(r, 3) for r in senza]
    cmp = compare_records(con, senza, label_a="con", label_b="senza")
    assert cmp.avviso_versioni_m1 == ""
    assert M1_VERSIONS_DIFFER_HEAD not in to_markdown(cmp)
    # Anche se nessuna e' registrata (record tutti pre-#408): niente da segnalare.
    assert compare_records(*_arms(), label_a="a", label_b="b").avviso_versioni_m1 == ""


def test_versione_m1_non_registrata_contro_registrata_e_segnalata() -> None:
    con, senza = _arms()
    senza = [_versione_m1(r, 3) for r in senza]
    cmp = compare_records(con, senza, label_a="con", label_b="senza")
    assert "`con`: versione n/d; `senza`: versione 3" in cmp.avviso_versioni_m1


def test_versioni_m1_miste_dentro_un_braccio_si_segnalano_senza_rifiutare() -> None:
    # A differenza di ISTAT (#369) il confronto non rifiuta: avvisa.
    con, senza = _arms()
    extra = _versione_m1(
        _rec("con", "Colosseo", _onto("Rapina in banca."), mode="analyze", rep=1), 2
    )
    con = [_versione_m1(r, 3) for r in con]
    cmp = compare_records(
        con,
        senza,
        label_a="con",
        label_b="senza",
        anchoring_records=([*con, extra], senza),
    )
    assert "`con`: versione 2, 3" in cmp.avviso_versioni_m1


def test_versione_dei_record_esclusi_non_conta() -> None:
    con, senza = _arms()
    fallback = _versione_m1(
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
        con,
        senza,
        label_a="con",
        label_b="senza",
        anchoring_records=(con, [*senza, fallback]),
    )
    assert cmp.avviso_versioni_m1 == ""


def test_zona_scartata_in_un_braccio_non_conta_per_le_versioni_m1() -> None:
    # Colosseo: v2 in A ma FALLBACK in B -> zona in `failed`, non confrontata.
    con, senza = _arms()
    con = [
        _versione_m1(r, 3) if r.zona != "Colosseo" else _versione_m1(r, 2) for r in con
    ]
    senza = [
        _versione_m1(r, 3)
        if r.zona != "Colosseo"
        else _versione_m1(r.model_copy(update={"status": RunStatus.FALLBACK}), 3)
        for r in senza
    ]
    cmp = compare_records(con, senza, label_a="con", label_b="senza")
    assert [f.zona for f in cmp.failed] == ["Colosseo"]
    assert cmp.avviso_versioni_m1 == ""


def test_zona_scartata_con_ripetizioni_non_conta_per_le_versioni_m1() -> None:
    con, senza = _arms()
    con = [
        _versione_m1(r, 3) if r.zona != "Colosseo" else _versione_m1(r, 2) for r in con
    ]
    senza = [
        _versione_m1(r, 3)
        if r.zona != "Colosseo"
        else _versione_m1(r.model_copy(update={"status": RunStatus.FALLBACK}), 3)
        for r in senza
    ]
    # Ripetizione extra OK della zona scartata, a v2: resta fuori dall'insieme.
    extra = _versione_m1(
        _rec("con", "Colosseo", _onto("Rapina in banca."), mode="analyze", rep=1), 2
    )
    cmp = compare_records(
        con,
        senza,
        label_a="con",
        label_b="senza",
        anchoring_records=([*con, extra], senza),
    )
    assert cmp.avviso_versioni_m1 == ""


def _vacuo(rec: RunRecord) -> RunRecord:
    metrics = rec.metrics.model_copy(update={"quality_vacuous": True})
    return rec.model_copy(update={"metrics": metrics})


def test_baseline_vacuo_a_versione_vecchia_non_fa_scattare_l_avviso() -> None:
    con, senza = _arms()
    con = [_vacuo(_versione_m1(r, 2)) for r in con]
    senza = [_versione_m1(r, 3) for r in senza]
    cmp = compare_records(con, senza, label_a="con", label_b="senza")
    assert cmp.avviso_versioni_m1 == ""


def test_record_vacuo_escluso_non_nasconde_un_vero_disaccordo() -> None:
    con, senza = _arms()
    con = [_versione_m1(r, 2) for r in con]
    con[0] = _vacuo(_versione_m1(con[0], 1))
    senza = [_versione_m1(r, 3) for r in senza]
    cmp = compare_records(con, senza, label_a="con", label_b="senza")
    assert "`con`: versione 2; `senza`: versione 3" in cmp.avviso_versioni_m1


def test_avviso_n_d_dice_che_non_si_sa_se_le_versioni_differiscano() -> None:
    con, senza = _arms()
    senza = [_versione_m1(r, 3) for r in senza]
    avviso = compare_records(
        con, senza, label_a="con", label_b="senza"
    ).avviso_versioni_m1
    assert "non si sa se le versioni differiscano davvero" in avviso
    assert "falso allarme" in avviso
    assert "rigirare" not in avviso


def test_avviso_con_versioni_note_e_diverse_suggerisce_di_rigirare() -> None:
    con, senza = _arms()
    con = [_versione_m1(r, 2) for r in con]
    senza = [_versione_m1(r, 3) for r in senza]
    avviso = compare_records(
        con, senza, label_a="con", label_b="senza"
    ).avviso_versioni_m1
    assert "rigirare i bracci con lo stesso codice" in avviso
    assert "falso allarme" not in avviso


def test_json_vecchio_senza_avviso_m1_si_legge() -> None:
    con, senza = _arms()
    dati = json.loads(to_json(compare_records(con, senza, label_a="a", label_b="b")))
    del dati["avviso_versioni_m1"]
    assert Comparison.model_validate(dati).avviso_versioni_m1 == ""
