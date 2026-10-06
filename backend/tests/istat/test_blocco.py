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
from tests.istat._fattorie import BANKROB, collegamento, istat_poi, riga


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
        BANKROB,
    ),
)


def test_zona_una_riga_per_luogo_e_voce_con_i_poi_coinvolti() -> None:
    blocco = blocco_istat_zona([_A, _B], stima_token=len, limite_token=None)
    righe = blocco.testo.split("\n")
    assert righe[0] == INTESTAZIONE_DATI_ISTAT
    assert "totale dei delitti denunciati" in righe[1]
    assert righe[2].startswith("- [Comune di Roma, 2024] furti (voce ISTAT THEFT)")
    assert righe[2].endswith(
        "Collegata a: Asportazione del bancomat, Furto di beni (voce più ampia del "
        "rischio). POI coinvolti: 2."
    )
    assert righe[3].startswith(
        "- [Comune di Roma, 2024] rapine in banca (voce ISTAT BANKROB)"
    )
    assert righe[3].endswith("POI coinvolti: 1.")
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
    assert righe[1].startswith("- [Comune di Roma, 2024] totale")
    assert righe[2].startswith("- [Provincia di Roma, 2024] totale")
    assert righe[3].startswith("- [Comune di Roma, 2024] furti")
    assert righe[4].startswith("- [Provincia di Roma, 2024] furti")


def test_poi_senza_istat_non_contano() -> None:
    blocco = blocco_istat_zona(
        [_poi("node/9", None), _A], stima_token=len, limite_token=None
    )
    assert "POI coinvolti: 1." in blocco.testo
    assert blocco_istat_zona(
        [_poi("node/9", None)], stima_token=len, limite_token=None
    ) == (BloccoIstat())


def test_taglio_toglie_prima_le_voci_con_meno_poi_e_lo_dichiara() -> None:
    pieno = blocco_istat_zona([_A, _B], stima_token=len, limite_token=None)
    limite = len(pieno.testo) - 1
    tagliato = blocco_istat_zona([_A, _B], stima_token=len, limite_token=limite)
    assert "BANKROB" not in tagliato.testo and "THEFT" in tagliato.testo
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
    blocco = blocco_istat_poi(istat_poi(riga(), BANKROB))
    righe = blocco.testo.split("\n")
    assert righe[0] == INTESTAZIONE_DATI_ISTAT
    assert "totale dei delitti denunciati" in righe[1]
    assert len(righe) == 4
    assert "POI coinvolti" not in blocco.testo
    assert blocco_istat_poi(None) == BloccoIstat()


def test_ha_righe_istat() -> None:
    assert ha_righe_istat([_poi("node/9", None), _A])
    assert not ha_righe_istat([_poi("node/9", None), {"poi_id": "x", "istat": None}])
