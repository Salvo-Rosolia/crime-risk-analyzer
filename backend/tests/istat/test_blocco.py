"""Blocco DATI ISTAT (#345, spec 4.4-4.5): dedupe, ordine, taglio, cornici."""

from __future__ import annotations

from typing import Any

from crime_risk_analyzer.istat.blocco import (
    INTESTAZIONE_DATI_ISTAT,
    BloccoIstat,
    blocco_istat_poi,
    blocco_istat_zona,
    ha_righe_istat,
    nota_taglio,
)
from crime_risk_analyzer.istat.righe import IstatPoi
from tests.istat._fattorie import (
    BANKROB,
    RAPINE_IN_BANCA,
    collegamento,
    istat_poi,
    riga,
)


def _poi(poi_id: str, istat: IstatPoi | None) -> dict[str, Any]:
    p: dict[str, Any] = {"poi_id": poi_id, "poi": poi_id}
    if istat is not None:
        p["istat"] = istat
    return p


_A = _poi("node/1", istat_poi(riga(collegamenti=(collegamento(),))))
_B = _poi(
    "node/2",
    istat_poi(
        riga(collegamenti=(collegamento("ATM_removal", "Asportazione del bancomat"),)),
        RAPINE_IN_BANCA,
    ),
)


def test_zona_una_riga_per_luogo_e_voce_ordinate_per_poi_coinvolti() -> None:
    """I furti (2 POI) prima delle rapine in banca (1 POI), anche se BANKROB viene
    prima in ordine alfabetico; il numero non compare nel testo (#365 D7)."""
    blocco = blocco_istat_zona([_A, _B], stima_token=len, limite_token=None)
    righe = blocco.testo.split("\n")
    assert righe[0] == INTESTAZIONE_DATI_ISTAT
    assert "totale dei delitti denunciati" in righe[1]
    assert righe[2].startswith("- Comune di Roma, 2024: furti: ")
    assert righe[2].endswith(
        "Collegata a: Asportazione del bancomat, Furto di beni (voce più ampia del "
        "rischio)."
    )
    assert righe[3].startswith("- Comune di Roma, 2024: rapine in banca: ")
    assert "POI coinvolti" not in blocco.testo
    assert len(righe) == 4
    assert [r.voce for r in blocco.righe] == ["TOT", "THEFT", "BANKROB"]
    assert blocco.voci_tagliate == 0


def test_zona_con_due_luoghi_dice_il_luogo_di_ogni_riga() -> None:
    provincia = _poi(
        "node/3",
        istat_poi(riga(luogo="ITE43", nome="Provincia di Roma", tipo="provincia")),
    )
    blocco = blocco_istat_zona([_A, provincia], stima_token=len, limite_token=None)
    righe = blocco.testo.split("\n")
    assert righe[1].startswith("- Comune di Roma, 2024: totale")
    assert righe[2].startswith("- Provincia di Roma, 2024: totale")
    assert righe[3].startswith("- Comune di Roma, 2024: furti")
    assert righe[4].startswith("- Provincia di Roma, 2024: furti")


def test_poi_senza_istat_non_contano() -> None:
    blocco = blocco_istat_zona(
        [_poi("node/9", None), _A], stima_token=len, limite_token=None
    )
    assert blocco == blocco_istat_zona([_A], stima_token=len, limite_token=None)
    assert blocco_istat_zona(
        [_poi("node/9", None)], stima_token=len, limite_token=None
    ) == (BloccoIstat())


def test_taglio_toglie_prima_le_voci_con_meno_poi_e_lo_dichiara() -> None:
    pieno = blocco_istat_zona([_A, _B], stima_token=len, limite_token=None)
    limite = len(pieno.testo) - 1
    tagliato = blocco_istat_zona([_A, _B], stima_token=len, limite_token=limite)
    assert "rapine in banca" not in tagliato.testo and "furti" in tagliato.testo
    assert tagliato.voci_tagliate == 1
    assert tagliato.testo.endswith(nota_taglio(1))
    assert len(tagliato.testo) <= limite
    assert [r.voce for r in tagliato.righe] == ["TOT", "THEFT"]


def test_cornici_per_ultime_blocco_vuoto_se_non_ci_sta_nulla() -> None:
    assert blocco_istat_zona([_A, _B], stima_token=len, limite_token=10) == BloccoIstat(
        voci_tagliate=2
    )


def test_nota_di_taglio() -> None:
    assert (
        nota_taglio(1) == "NB: per limiti di lunghezza 1 voce ISTAT non e' riportata."
    )
    assert (
        nota_taglio(3) == "NB: per limiti di lunghezza 3 voci ISTAT non sono riportate."
    )


def test_blocco_del_poi_senza_poi_coinvolti() -> None:
    blocco = blocco_istat_poi(istat_poi(riga(), RAPINE_IN_BANCA))
    righe = blocco.testo.split("\n")
    assert righe[0] == INTESTAZIONE_DATI_ISTAT
    assert "totale dei delitti denunciati" in righe[1]
    assert len(righe) == 4
    assert "POI coinvolti" not in blocco.testo
    assert blocco_istat_poi(None) == BloccoIstat()


def test_ha_righe_istat() -> None:
    assert ha_righe_istat([_poi("node/9", None), _A])
    assert not ha_righe_istat([_poi("node/9", None), {"poi_id": "x", "istat": None}])


def test_voci_sotto_i_20_delitti_restano_fuori_dal_blocco() -> None:
    """#365 D2: 3 rapine in banca o un conteggio assente non entrano in narrativa
    (stessa soglia del Dettaglio); la cornice resta, con le voci che restano."""
    senza_conteggio = riga("SHOPROB", label="rapine in negozio", delitti=None)
    venti = riga("SNATCH", label="scippi", delitti=20)
    zona = blocco_istat_zona(
        [_poi("node/1", istat_poi(riga(), BANKROB, senza_conteggio, venti))],
        stima_token=len,
        limite_token=None,
    )
    poi = blocco_istat_poi(istat_poi(riga(), BANKROB, senza_conteggio, venti))
    for blocco in (zona, poi):
        assert {r.voce for r in blocco.righe} == {"TOT", "THEFT", "SNATCH"}
        assert "rapine in banca" not in blocco.testo
        assert "rapine in negozio" not in blocco.testo
    assert zona.voci_tagliate == 0  # escluse per soglia, non tagliate per budget


def test_solo_voci_sotto_soglia_nessun_blocco() -> None:
    assert blocco_istat_poi(istat_poi(BANKROB)) == BloccoIstat()
    assert (
        blocco_istat_zona(
            [_poi("node/1", istat_poi(BANKROB))], stima_token=len, limite_token=None
        )
        == BloccoIstat()
    )
