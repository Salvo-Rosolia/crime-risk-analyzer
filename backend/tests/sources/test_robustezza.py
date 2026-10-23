"""Robustezza del controllo delle fonti (#415): input ostili non sollevano mai.

``check_sources`` deve sempre rispondere con un report: nessuna eccezione, nessun
blocco della CPU, nessun report di milioni di righe.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace

import pytest

from crime_risk_analyzer.sources import parsing
from crime_risk_analyzer.sources.csv_reader import MAX_ERRORI_RIGA, MAX_RIGHE, read_csv
from crime_risk_analyzer.sources.parsing import UploadedFiles, check_sources
from crime_risk_analyzer.sources.report import (
    CODE_OTHER_PROBLEMS,
    MAX_PROBLEMS_PER_FILE,
    ValidationReport,
)
from tests.sources._fattorie import (
    CONFINI,
    DATI_CSV,
    NS,
    OSM_CSV,
    VOCABOLARIO,
    con,
    confini_json,
    file_validi,
)


def _report(files: UploadedFiles) -> ValidationReport:
    parsed, report = check_sources(files, VOCABOLARIO)
    assert parsed is None
    assert not report.ok
    return report


def _codici(report: ValidationReport) -> list[str]:
    return [p.code for p in report.errors]


# --- 1. entita' XML annidate (billion laughs) ---


def _xml_con_entita(dichiarazioni: str, corpo: str = "") -> bytes:
    return f"""<?xml version="1.0"?>
<!DOCTYPE rdf:RDF [{dichiarazioni}]>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Class rdf:about="{NS}Banca">{corpo}</owl:Class>
</rdf:RDF>""".encode()


def test_billion_laughs_rifiutato_subito() -> None:
    dichiarazioni = '<!ENTITY l0 "ha">' + "".join(
        f'<!ENTITY l{n} "{f"&l{n - 1};" * 10}">' for n in range(1, 8)
    )
    xml = _xml_con_entita(dichiarazioni, "&l7;")
    inizio = time.monotonic()
    report = _report(con(ontology=xml, ontology_name="x.owl"))
    assert time.monotonic() - inizio < 2
    assert _codici(report) == ["entita_xml_annidata"]
    assert report.errors[0].file == "ontology"


def test_troppe_entita_rifiutate() -> None:
    dichiarazioni = "".join(f'<!ENTITY e{n} "x">' for n in range(101))
    report = _report(
        con(ontology=_xml_con_entita(dichiarazioni), ontology_name="x.owl")
    )
    assert _codici(report) == ["entita_xml_troppe"]


def test_entita_troppo_grandi_in_totale_rifiutate() -> None:
    dichiarazioni = "".join(f'<!ENTITY e{n} "{"x" * 3000}">' for n in range(4))
    report = _report(
        con(ontology=_xml_con_entita(dichiarazioni), ontology_name="x.owl")
    )
    assert _codici(report) == ["entita_xml_troppe"]


def test_dichiarazione_di_entita_non_semplice_rifiutata() -> None:
    report = _report(
        con(
            ontology=_xml_con_entita("<!ENTITY e1 x>"),
            ontology_name="x.owl",
        )
    )
    assert _codici(report) == ["entita_xml_non_ammessa"]


# --- 2. GeoJSON ostile: mai eccezioni ---


def _con_geometria(geometria: object) -> UploadedFiles:
    brutti = json.loads(json.dumps(CONFINI))
    brutti["features"][0]["geometry"] = geometria
    return con(boundaries=confini_json(brutti))


def test_json_annidato_profondo() -> None:
    report = _report(con(boundaries=b"[" * 100_000))
    assert "confini_illeggibili" in _codici(report)


def test_multipolygon_senza_coordinate() -> None:
    report = _report(_con_geometria({"type": "MultiPolygon", "coordinates": []}))
    assert "confini_non_validi" in _codici(report)


def test_punto_dell_anello_e_un_oggetto() -> None:
    report = _report(
        _con_geometria({"type": "Polygon", "coordinates": [[{"a": 1}] * 4]})
    )
    assert "confini_non_validi" in _codici(report)


def test_coordinata_intera_enorme() -> None:
    enorme = int("9" * 400)
    anello = [[12.0, 41.0], [enorme, 41.0], [13.0, 42.0], [12.0, 41.0]]
    base = json.loads(json.dumps(CONFINI))
    base["features"][0]["geometry"] = {"type": "Polygon", "coordinates": [anello]}
    contenuto = json.dumps(base)
    report = _report(con(boundaries=contenuto.encode()))
    assert "confini_non_validi" in _codici(report)


def test_anello_non_chiuso() -> None:
    anello = [[12.0, 41.0], [13.0, 41.0], [13.0, 42.0], [12.0, 42.0]]
    report = _report(_con_geometria({"type": "Polygon", "coordinates": [anello]}))
    assert "confini_non_validi" in _codici(report)
    assert "chiuso" in report.errors[0].message


def test_anello_con_area_zero() -> None:
    anello = [[12.0, 41.0]] * 4
    report = _report(_con_geometria({"type": "Polygon", "coordinates": [anello]}))
    assert "area zero" in report.errors[0].message


def test_nessun_punto_interno_e_un_errore(monkeypatch: pytest.MonkeyPatch) -> None:

    def nessun_incrocio(_poligono: object, _y: float) -> list[float]:
        return []

    monkeypatch.setattr(parsing, "_incroci_orizzontali", nessun_incrocio)
    anello = [[0.0, 0.0], [4.0, 0.0], [4.0, 1.0], [1.0, 1.0], [1.0, 3.0]]
    anello += [[4.0, 3.0], [4.0, 4.0], [0.0, 4.0], [0.0, 0.0]]
    report = _report(_con_geometria({"type": "Polygon", "coordinates": [anello]}))
    assert "punto interno" in report.errors[0].message


# --- 3. numeri enormi o strani ---


def test_delitti_con_cella_da_5000_cifre() -> None:
    dati = DATI_CSV + f"001,ROB,rapine,2023,{'9' * 5000},1.0,no\n"
    report = _report(con(data=dati.encode()))
    assert _codici(report) == ["valore_non_valido"]


@pytest.mark.parametrize("tasso", ["1_0", "١٢", "1e5", "9" * 5000, "1.5.2", "+3"])
def test_tasso_con_forme_non_ammesse(tasso: str) -> None:
    dati = DATI_CSV + f"001,ROB,rapine,2023,1,{tasso},no\n"
    report = _report(con(data=dati.encode()))
    assert _codici(report) == ["valore_non_valido"]


def test_delitti_con_cifre_unicode() -> None:
    dati = DATI_CSV + "001,ROB,rapine,2023,١٢,1.0,no\n"
    report = _report(con(data=dati.encode()))
    assert _codici(report) == ["valore_non_valido"]


# --- 4. tetto del report ---


def test_report_con_tetto_per_file_e_conteggio_reale() -> None:
    righe = 20_000
    osm = OSM_CSV + "amenity=cafe\n" * righe
    report = _report(con(osm_table=osm.encode()))
    assert len(report.errors) <= MAX_PROBLEMS_PER_FILE + 1
    assert report.errors[-1].code == "lettura_interrotta"
    assert report.errors[-1].file == "osm_table"
    assert len(report.errors) == MAX_ERRORI_RIGA + 1


def test_tetto_per_file_con_codici_diversi() -> None:
    righe = "".join(f"amenity=x{n},Inesistente{n}\n" for n in range(300))
    report = _report(con(osm_table=(OSM_CSV + righe).encode()))
    assert len(report.errors) <= MAX_PROBLEMS_PER_FILE + 1
    assert report.errors[-1].code == CODE_OTHER_PROBLEMS


def test_il_tetto_e_separato_per_file_e_per_avvisi() -> None:
    osm = OSM_CSV + "amenity=cafe\n" * 200
    dati = DATI_CSV + "001,ROB,rapine,20x4,1,1.0,no\n"
    report = _report(con(osm_table=osm.encode(), data=dati.encode()))
    assert any(
        p.file == "data" and p.code == "valore_non_valido" for p in report.errors
    )


# --- 6. intestazione CSV ---


def test_riga_iniziale_vuota() -> None:
    report = _report(con(osm_table=b"\n" + OSM_CSV.encode()))
    assert _codici(report) == ["intestazione_mancante"]
    assert report.errors[0].line == 1


def test_intestazione_gigante_non_e_file_vuoto() -> None:
    report = _report(con(osm_table=b"x" * 200_000 + b"\n1\n"))
    assert _codici(report) == ["intestazione_non_leggibile"]


def test_separatori_unicode_non_spezzano_l_intestazione() -> None:
    # \x0c e \x0b non sono fine riga per csv: restano dentro la cella.
    contenuto = b"osm_tag,cla\x0bsse\namenity=bank,Banca\n"
    report = _report(con(osm_table=contenuto))
    assert _codici(report) == ["colonna_mancante"]


def test_punto_e_virgola_dentro_un_campo_tra_virgolette_non_e_il_separatore() -> None:
    contenuto = b'"osm_tag;x",classe\namenity=bank,Banca\n'
    report = _report(con(osm_table=contenuto))
    assert "separatore_non_valido" not in _codici(report)


# --- 7. codifiche ---


@pytest.mark.parametrize("campo", ["osm_table", "data", "hazard_table"])
def test_csv_utf16_rifiutato(campo: str) -> None:
    testo = getattr(file_validi(), campo).decode("utf-8")
    report = _report(replace(file_validi(), **{campo: testo.encode("utf-16")}))
    assert _codici(report) == ["codifica_non_valida"]
    assert report.errors[0].file == campo


def test_ontologia_e_confini_utf16_rifiutati() -> None:
    files = con(
        ontology=file_validi().ontology.decode().encode("utf-16"),
        boundaries=confini_json().decode().encode("utf-16"),
    )
    report = _report(files)
    codici = _codici(report)
    assert "ontologia_illeggibile" in codici
    assert "confini_illeggibili" in codici


# --- secondo giro ---


def _laughs(livelli: int) -> str:
    dichiarazioni = '<!ENTITY l0 "ha">' + "".join(
        f'<!ENTITY l{n} "{f"&l{n - 1};" * 10}">' for n in range(1, livelli + 1)
    )
    return _xml_con_entita(dichiarazioni, f"&l{livelli};").decode()


@pytest.mark.parametrize("codifica", ["utf-16-le", "utf-16-be", "utf-16", "utf-32"])
def test_billion_laughs_in_utf16_senza_bom_rifiutato_subito(codifica: str) -> None:
    xml = _laughs(7).encode(codifica)
    inizio = time.monotonic()
    report = _report(con(ontology=xml, ontology_name="x.owl"))
    assert time.monotonic() - inizio < 2
    assert _codici(report) == ["codifica_non_ammessa"]


def test_protege_utf8_con_entita_semplici_passa() -> None:
    xml = _xml_con_entita('<!ENTITY owl "http://www.w3.org/2002/07/owl#">')
    _, report = check_sources(con(ontology=xml, ontology_name="x.owl"), VOCABOLARIO)
    assert "codifica_non_ammessa" not in [p.code for p in report.errors]
    assert "entita_xml_annidata" not in [p.code for p in report.errors]


def test_csv_4mb_di_righe_malformate_si_ferma_subito() -> None:
    osm = OSM_CSV + "x\n" * 2_000_000
    inizio = time.monotonic()
    report = _report(con(osm_table=osm.encode()))
    assert time.monotonic() - inizio < 5
    assert "lettura_interrotta" in _codici(report)
    assert len(report.errors) <= MAX_PROBLEMS_PER_FILE + 1


def test_molte_righe_valide_con_errore_semantico_restano_veloci() -> None:
    osm = OSM_CSV + "".join(f"amenity=a{n},Inesistente\n" for n in range(150_000))
    inizio = time.monotonic()
    report = _report(con(osm_table=osm.encode()))
    assert time.monotonic() - inizio < 30
    assert len(report.errors) <= MAX_PROBLEMS_PER_FILE + 1


# --- terzo giro: intestazione larga ---


def test_intestazione_con_milioni_di_colonne_rifiutata_subito() -> None:
    contenuto = b"osm_tag,classe" + b",c" * 2_500_000 + b"\n"
    inizio = time.monotonic()
    report = _report(con(osm_table=contenuto))
    assert time.monotonic() - inizio < 2
    assert _codici(report) == ["troppe_colonne"]


def test_intestazione_con_51_colonne_rifiutata_e_con_50_accettata() -> None:
    extra50 = ",".join(f"x{n}" for n in range(48))
    ok = f"osm_tag,classe,{extra50}\namenity=bank,Banca" + "," * 48 + "\n"
    _, report = check_sources(
        con(osm_table=(ok + "amenity=hospital,Ospedale" + "," * 48 + "\n").encode()),
        VOCABOLARIO,
    )
    assert "troppe_colonne" not in [p.code for p in report.errors]
    report = _report(con(osm_table=f"osm_tag,classe,{extra50},y,z\n".encode()))
    assert _codici(report) == ["troppe_colonne"]


def test_colonne_duplicate_e_in_piu_ancora_segnalate() -> None:
    osm = "osm_tag,classe,classe,zeta,alfa\namenity=bank,Banca,Banca,1,2\n"
    parsed, report = check_sources(con(osm_table=osm.encode()), VOCABOLARIO)
    assert parsed is None
    assert _codici(report) == ["colonna_duplicata"]
    (w,) = report.warnings
    assert w.code == "colonna_in_piu"
    assert w.message.index("zeta") < w.message.index("alfa")


# --- quarto giro: coordinate numeriche e tetto righe ---


@pytest.mark.parametrize(
    "punto", [["1", "1"], ["x", "y"], [True, False], [None, 1], ["1", 2]]
)
def test_coordinate_non_numeriche_rifiutate(punto: list[object]) -> None:
    anello = [[12.0, 41.0], [13.0, 41.0], punto, [12.0, 41.0]]
    for geometria in (
        {"type": "Polygon", "coordinates": [anello]},
        {"type": "MultiPolygon", "coordinates": [[anello]]},
    ):
        report = _report(_con_geometria(geometria))
        assert _codici(report) == ["confini_non_validi"]
        assert "numeri" in report.errors[0].message


def test_coordinate_numeriche_valide_passano() -> None:
    parsed, report = check_sources(file_validi(), VOCABOLARIO)
    assert report.ok
    assert parsed is not None


def test_tetto_righe_confine_n_e_n_piu_uno() -> None:
    contenuto = b"osm_tag,classe\n" + b"amenity=a,Banca\n" * 5
    ok = ValidationReport()
    assert (
        len(
            read_csv(
                contenuto,
                "osm_table",
                required=("osm_tag", "classe"),
                report=ok,
                max_rows=5,
            )
            or []
        )
        == 5
    )
    ko = ValidationReport()
    assert (
        read_csv(
            contenuto,
            "osm_table",
            required=("osm_tag", "classe"),
            report=ko,
            max_rows=4,
        )
        is None
    )
    assert [p.code for p in ko.errors] == ["troppe_righe"]


def test_file_con_200001_righe_rifiutato_subito() -> None:
    assert MAX_RIGHE == 200_000
    osm = "osm_tag,classe\n" + "".join(
        f"amenity=a{n},Banca\n" for n in range(MAX_RIGHE + 1)
    )
    inizio = time.monotonic()
    report = _report(con(osm_table=osm.encode()))
    assert time.monotonic() - inizio < 5
    assert _codici(report) == ["troppe_righe"]


def test_file_con_200000_righe_valide_accettato() -> None:
    osm = "osm_tag,classe\n" + "".join(
        f"amenity=a{n},Banca\n" for n in range(MAX_RIGHE)
    )
    parsed, report = check_sources(con(osm_table=osm.encode()), VOCABOLARIO)
    assert report.ok
    assert parsed is not None
    assert len(parsed.osm_to_class) == MAX_RIGHE
