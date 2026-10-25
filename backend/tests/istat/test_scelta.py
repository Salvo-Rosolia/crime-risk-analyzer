"""Scelta dei dati ISTAT da parte del modello, frasi composte dall'app (#366)."""

from __future__ import annotations

from crime_risk_analyzer.istat.scelta import (
    INTESTAZIONE_SCELTA,
    ScartiScelta,
    SceltaGrezza,
    SceltaIstat,
    componi_frase,
    componi_frasi,
    estrai_scelta,
    inserisci_frasi,
    risolvi_scelta,
)
from crime_risk_analyzer.rag.generation import source_block_spans
from tests.istat._fattorie import collegamento, cornice, riga

_FURTI = riga(
    "THEFT",
    label="furti",
    collegamenti=(collegamento("Property_theft", "Furto di beni", "piu_larga"),),
)
_RAPINE = riga(
    "ROBBER",
    label="rapine",
    tasso=10.0,
    italia=10.0,
    variazione=20,
    collegamenti=(collegamento("Robbery", "Rapina", "esatta"),),
)


def _frase(scelta: SceltaIstat) -> str:
    frase = componi_frase(scelta)
    assert frase is not None
    return frase


def _testo(*linee: str) -> str:
    return "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nProsa.\n\n" + "\n".join(
        [INTESTAZIONE_SCELTA, *linee]
    )


def _righe_lette(grezze: list[SceltaGrezza]) -> list[tuple[str, str, str]]:
    return [(g.rischio, g.voce, g.peso) for g in grezze]


def test_estrai_toglie_il_blocco_e_legge_le_righe() -> None:
    testo, grezze, malformate = estrai_scelta(
        _testo("- Furto di beni | furti | alto", "Rapina | rapine | basso")
    )
    assert testo == "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nProsa."
    assert _righe_lette(grezze) == [
        ("Furto di beni", "furti", "alto"),
        ("Rapina", "rapine", "basso"),
    ]
    assert malformate == 0


def test_estrai_senza_blocco_non_tocca_il_testo() -> None:
    assert estrai_scelta("Sintesi.\n") == ("Sintesi.\n", [], 0)


def test_estrai_intestazione_decorata_e_righe_malformate_contate() -> None:
    testo, grezze, malformate = estrai_scelta(
        "Prosa.\n\n**Scelta dati ISTAT:**\nRapina | rapine\n"
        "Rapina | rapine | enorme\nRapina | rapine | Medio\n"
    )
    assert testo == "Prosa."
    assert _righe_lette(grezze) == [
        ("Rapina", "rapine", "enorme"),
        ("Rapina", "rapine", "Medio"),
    ]
    assert malformate == 1


def test_estrai_accetta_la_prima_riga_dopo_i_due_punti() -> None:
    testo, grezze, _ = estrai_scelta(
        "Prosa.\n\nSCELTA DATI ISTAT: Rapina | rapine | alto\n- Furto | furti | basso\n"
    )
    assert testo == "Prosa."
    assert _righe_lette(grezze) == [
        ("Rapina", "rapine", "alto"),
        ("Furto", "furti", "basso"),
    ]


def test_estrai_a_meta_risposta_conserva_i_blocchi_successivi() -> None:
    testo, grezze, _ = estrai_scelta(
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nProsa.\n\n"
        "SCELTA DATI ISTAT:\n- Rapina | rapine | alto\n\n"
        "Rischi dal contesto [CONTESTO]\nZona di transito.\n"
    )
    assert testo == (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nProsa.\n\n"
        "Rischi dal contesto [CONTESTO]\nZona di transito.\n"
    )
    assert _righe_lette(grezze) == [("Rapina", "rapine", "alto")]


def test_risolvi_ancora_alle_righe_e_scarta_il_resto() -> None:
    _, grezze, _ = estrai_scelta(
        _testo(
            "Furto di beni | furti | alto",
            "Rapina | furti | alto",  # rischio non collegato alla voce
            "Furto di beni | voce inventata | alto",
            "FURTO DI BENI | Furti | medio",  # doppione (maiuscole): una sola volta
        )
    )
    scelte, scarti = risolvi_scelta(grezze, [cornice(), _FURTI, _RAPINE])
    assert [(s.riga.voce, s.hazard, s.peso) for s in scelte] == [
        ("THEFT", "Property_theft", "alto")
    ]
    assert scarti == ScartiScelta(
        rischio_non_collegato=1, voce_non_nel_blocco=1, doppione=1
    )


def test_risolvi_non_sceglie_la_cornice_del_totale() -> None:
    _, grezze, _ = estrai_scelta(_testo("Furto di beni | totale | alto"))
    scelte, scarti = risolvi_scelta(grezze, [cornice(), _FURTI])
    assert scelte == []
    assert scarti.voce_non_nel_blocco == 1


def test_risolvi_conta_peso_fuori_vocabolario_e_malformate() -> None:
    _, grezze, malformate = estrai_scelta(
        _testo("Rapina | rapine | enorme", "Rapina | rapine", "Rapina | rapine | ALTO.")
    )
    scelte, scarti = risolvi_scelta(grezze, [_RAPINE], malformate=malformate)
    assert [s.peso for s in scelte] == ["alto"]
    assert scarti == ScartiScelta(peso_non_valido=1, malformate=1)


def test_risolvi_normalizza_apostrofo_tipografico_e_accenti() -> None:
    riga_apos = riga(
        "CARTHEFT",
        label="furti d'auto più gravi",
        collegamenti=(collegamento("Car_theft", "Furto d'auto", "esatta"),),
    )
    _, grezze, _ = estrai_scelta(
        _testo("Furto d’auto | Furti d’auto piu gravi | medio")
    )
    scelte, scarti = risolvi_scelta(grezze, [riga_apos])
    assert [s.hazard for s in scelte] == ["Car_theft"]
    assert scarti == ScartiScelta()


def test_frase_composta_dall_app_senza_pezzi_interni() -> None:
    scelta = SceltaIstat(
        riga=_RAPINE.model_copy(update={"variazione_pct": 20}),
        hazard="Robbery",
        rischio="Rapina",
        peso="alto",
    )
    frase = _frase(scelta)
    assert frase == (
        "Secondo i dati ISTAT del Comune di Roma (2024), la voce «rapine» (rischio: "
        "Rapina) ha un tasso simile a quello italiano e un andamento in crescita "
        "dal 2014."
    )
    for interno in ("corrispondenza esatta", "non calcolata", "più ampia"):
        assert interno not in frase


def test_frase_dichiara_la_voce_piu_larga_o_piu_stretta() -> None:
    larga = SceltaIstat(
        riga=_FURTI, hazard="Property_theft", rischio="Furto di beni", peso="alto"
    )
    assert _frase(larga).endswith(
        "in calo dal 2014; la voce comprende anche altri reati."
    )
    stretta_riga = _FURTI.model_copy(
        update={
            "collegamenti": (
                collegamento("Property_theft", "Furto di beni", "piu_stretta"),
            )
        }
    )
    stretta = SceltaIstat(
        riga=stretta_riga, hazard="Property_theft", rischio="Furto di beni", peso="alto"
    )
    assert "copre solo una parte del rischio" in _frase(stretta)


def test_frase_omette_tendenza_non_calcolata() -> None:
    senza = _FURTI.model_copy(
        update={"variazione_pct": None, "motivo_senza_variazione": "x"}
    )
    frase = _frase(
        SceltaIstat(
            riga=senza, hazard="Property_theft", rischio="Furto di beni", peso="alto"
        )
    )
    assert "andamento" not in frase
    assert "crescita" not in frase and "calo" not in frase
    assert "tasso più alto di quello italiano" in frase


def test_senza_confronto_ne_tendenza_nessuna_frase() -> None:
    vuota = _FURTI.model_copy(
        update={"variazione_pct": None, "tasso": None, "tasso_italia": None}
    )
    scelta = SceltaIstat(
        riga=vuota, hazard="Property_theft", rischio="Furto di beni", peso="alto"
    )
    assert componi_frase(scelta) is None
    assert componi_frasi([scelta]) == []


def test_frasi_ordinate_per_peso_e_stabili() -> None:
    basso = SceltaIstat(riga=_FURTI, hazard="h", rischio="Furto di beni", peso="basso")
    alto = SceltaIstat(riga=_RAPINE, hazard="r", rischio="Rapina", peso="alto")
    frasi = componi_frasi([basso, alto])
    assert "rapine" in frasi[0]
    assert "furti" in frasi[1]


def test_inserisci_in_fondo_al_blocco_ontologia() -> None:
    testo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nProsa.\n\n"
        "Rischi dal contesto [CONTESTO]\nZona.\n"
    )
    out = inserisci_frasi(testo, source_block_spans(testo), ["Frase A.", "Frase B."])
    assert out == (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nProsa.\nFrase A. Frase B.\n\n"
        "Rischi dal contesto [CONTESTO]\nZona.\n"
    )


def test_inserisci_senza_blocco_ontologia_ne_apre_uno() -> None:
    out = inserisci_frasi("Sintesi.", [], ["Frase A."])
    assert out == "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nFrase A."


def test_inserisci_senza_frasi_non_cambia() -> None:
    assert inserisci_frasi("Sintesi.", [], []) == "Sintesi."
