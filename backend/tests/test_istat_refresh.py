"""Funzioni pure di scripts/istat_refresh.py (#345): nessuna rete."""

from __future__ import annotations

from scripts.istat_refresh import (
    PROVINCIA_NUTS,
    SARDEGNA_2001,
    codelist,
    is_comune,
    is_provincia,
    valori_da_csv,
    verifica_completezza,
    voci_richieste,
)

_TESTA = "REF_AREA,DATA_TYPE,TYPE_CRIME,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"


def test_valori_da_csv_tiene_solo_province_comuni_italia_e_anni_richiesti() -> None:
    testo = _TESTA + "\n".join(
        [
            "058091,CRIMEN,THEFT,2024,134169,",
            "058091,CRIMET,THEFT,2024,4876.4,",
            "058091,CRIMEN,THEFT,2014,148910,",
            "058091,CRIMEN,THEFT,2015,1,",  # anno non richiesto
            "ITE4,CRIMEN,THEFT,2024,9,",  # regione: scartata
            "ITE43,CRIMEN,THEFT,2024,155538,",
            "ITE43,CRIMET,THEFT,2024,,0",  # tasso sotto soglia
            "IT,CRIMEN,THEFT,2024,1054599,",
            "IT,CRIMET,THEFT,2024,,",  # tasso mancante senza flag
            "IT,CRIMEN,ARSON,2024,5,",  # voce non richiesta
        ]
    )
    valori = valori_da_csv(testo, anni=(2024, 2014), voci=["THEFT"])
    assert set(valori) == {"058091", "ITE43", "IT"}
    assert valori["058091"]["THEFT"]["2024"] == {
        "delitti": 134169,
        "tasso": 4876.4,
        "tasso_sotto_soglia": False,
    }
    assert valori["058091"]["THEFT"]["2014"] == {
        "delitti": 148910,
        "tasso": None,
        "tasso_sotto_soglia": False,
    }
    assert valori["ITE43"]["THEFT"]["2024"] == {
        "delitti": 155538,
        "tasso": None,
        "tasso_sotto_soglia": True,
    }
    assert valori["ITE43"]["THEFT"]["2014"] is None
    italia = valori["IT"]["THEFT"]["2024"]
    assert italia is not None and italia["tasso_sotto_soglia"] is False


def test_verifica_completezza_segnala_territori_e_anni_mancanti() -> None:
    problemi = verifica_completezza({"058091": {"THEFT": {"2024": None}}}, ["THEFT"])
    assert "attese 106 province, trovate 0" in problemi
    assert "attesi 108 comuni capoluogo, trovati 1" in problemi
    assert "manca la riga Italia" in problemi
    assert "058091/THEFT: manca il dato 2024" in problemi


def test_codelist_legge_i_nomi_italiani() -> None:
    xml = (
        b'<m:Structure xmlns:m="urn:x" '
        b'xmlns:s="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure" '
        b'xmlns:c="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common">'
        b'<s:Codelist id="CL_REATI_PS"><s:Code id="THEFT">'
        b'<c:Name xml:lang="en">thefts</c:Name><c:Name xml:lang="it">furti</c:Name>'
        b"</s:Code></s:Codelist></m:Structure>"
    )
    assert codelist(xml, "CL_REATI_PS") == {"THEFT": "furti"}
    assert codelist(xml, "CL_ALTRA") == {}


def test_codici_territoriali() -> None:
    assert is_provincia("ITE43") and is_provincia("IT108")
    assert not is_provincia("ITE4") and not is_provincia("IT")
    assert is_comune("058091") and not is_comune("58091")


def test_tabella_province_copre_le_106_del_dataset() -> None:
    assert len(PROVINCIA_NUTS) == 102
    assert set(SARDEGNA_2001.values()) == {"ITG25", "ITG26", "ITG27", "ITG28"}
    assert not set(PROVINCIA_NUTS.values()) & set(SARDEGNA_2001.values())
    assert len(set(PROVINCIA_NUTS.values()) | set(SARDEGNA_2001.values())) == 106
    assert PROVINCIA_NUTS[58] == "ITE43" and PROVINCIA_NUTS[108] == "IT108"
    assert PROVINCIA_NUTS[19] == "ITC4A" and PROVINCIA_NUTS[53] == "ITE1A"


def test_voci_richieste_sono_le_mappate_piu_il_totale() -> None:
    voci = voci_richieste()
    assert "TOT" in voci and "THEFT" in voci and "DAMAGE" in voci
    assert len(voci) == 19
