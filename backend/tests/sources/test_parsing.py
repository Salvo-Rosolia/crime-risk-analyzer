"""Lettura e controllo dei cinque file delle fonti (#415)."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from crime_risk_analyzer.istat.dati import CODICE_ITALIA, ValoreAnno
from crime_risk_analyzer.sources.parsing import (
    ParsedSources,
    UploadedFiles,
    check_sources,
    read_sources,
)
from crime_risk_analyzer.sources.report import (
    Problem,
    SourceValidationError,
    ValidationReport,
)
from crime_risk_analyzer.sources.vocabulary import OntologyVocabulary
from tests.sources._fattorie import (
    CONFINI,
    DATI_CSV,
    HAZARD_CSV,
    NS,
    ONTOLOGIA_TTL,
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


def _codici(problemi: list[Problem]) -> list[str]:
    return [p.code for p in problemi]


def _senza_righe_che_iniziano_con(testo: str, prefisso: str) -> bytes:
    righe = [r for r in testo.splitlines() if not r.startswith(prefisso)]
    return "\n".join(righe).encode("utf-8")


# --- caso valido ---


def test_caso_valido_restituisce_le_fonti_lette() -> None:
    parsed, report = read_sources(file_validi(), VOCABOLARIO)
    assert isinstance(parsed, ParsedSources)
    assert report.ok
    assert report.errors == []
    assert report.warnings == []
    assert parsed.vocabulary == VOCABOLARIO
    assert len(parsed.graph) > 0
    assert parsed.osm_to_class == {
        "amenity=bank": "Banca",
        "amenity=hospital": "Ospedale",
    }
    assert parsed.ordine_famiglie == ("amenity",)


def test_etichette_it_en_dalle_rdfs_label() -> None:
    parsed, _ = read_sources(file_validi(), VOCABOLARIO)
    assert parsed.labels["Banca"] == ("Banca", "Bank")
    assert parsed.labels["Rapina"] == ("Rapina", "Robbery")


def test_dati_stessa_logica_istat() -> None:
    parsed, _ = read_sources(file_validi(), VOCABOLARIO)
    delitti = parsed.istat.delitti
    assert delitti.anno == 2024
    assert delitti.anno_confronto == 2014
    assert delitti.voci == {"TOT": "totale", "ROB": "rapine", "THEFT": "furti"}
    assert delitti.valore("001", "ROB", 2024) == ValoreAnno(
        delitti=100, tasso=80.0, tasso_sotto_soglia=False
    )
    assert delitti.valore(CODICE_ITALIA, "ROB", 2014) is not None
    assert delitti.valore("001", "ROB", 1999) is None


def test_versione_e_hash_del_file_dei_dati() -> None:
    parsed, _ = read_sources(file_validi(), VOCABOLARIO)
    assert len(parsed.versione) == 12
    assert parsed.istat.versione == parsed.versione
    altra = con(data=DATI_CSV.replace("5000", "5001").encode("utf-8"))
    assert read_sources(altra, VOCABOLARIO)[0].versione != parsed.versione


def test_luoghi_con_confini_caricati() -> None:
    parsed, _ = read_sources(file_validi(), VOCABOLARIO)
    (luogo,) = parsed.istat.luoghi
    assert (luogo.codice, luogo.tipo) == ("001", "comune")
    assert luogo.nome == "Comune di Esempio"
    assert luogo.nome_breve == "Esempio"
    assert luogo.provincia is None
    assert luogo.bbox == (12.0, 41.0, 13.0, 42.0)
    lon, lat = luogo.punto_interno
    assert 12.0 < lon < 13.0
    assert 41.0 < lat < 42.0


def test_punto_interno_dentro_un_poligono_a_forma_di_c() -> None:
    # Il centro del riquadro cade nel "vuoto" della C: il punto interno no.
    c = [
        [10.0, 40.0],
        [14.0, 40.0],
        [14.0, 41.0],
        [11.0, 41.0],
        [11.0, 43.0],
        [14.0, 43.0],
        [14.0, 44.0],
        [10.0, 44.0],
        [10.0, 40.0],
    ]
    forma = json.loads(json.dumps(CONFINI))
    forma["features"][0]["geometry"]["coordinates"] = [c]
    parsed, report = read_sources(con(boundaries=confini_json(forma)), VOCABOLARIO)
    assert report.ok
    from crime_risk_analyzer.models.geo import point_in_multipolygon

    (luogo,) = parsed.istat.luoghi
    assert point_in_multipolygon(luogo.punto_interno, luogo.confine)


def test_mappatura_hazard_voce() -> None:
    parsed, _ = read_sources(file_validi(), VOCABOLARIO)
    rapina = parsed.mappatura["Rapina"]
    assert rapina.voce_istat == "ROB"
    assert rapina.corrispondenza == "esatta"
    assert rapina.rottura_2016 is False
    furto = parsed.mappatura["Furto"]
    assert (furto.voce_istat, furto.corrispondenza) == ("THEFT", "piu_larga")
    assert furto.rottura_2016 is True
    assert furto.nota == "Serie interrotta nel 2016"
    assert parsed.voci_rottura == frozenset({"THEFT"})


def test_hazard_senza_voce() -> None:
    hazard = "hazard,voce,corrispondenza\nRapina,,\nFurto,THEFT,esatta\n"
    parsed, report = read_sources(con(hazard_table=hazard.encode()), VOCABOLARIO)
    assert report.ok
    assert parsed.mappatura["Rapina"].voce_istat is None
    assert parsed.mappatura["Rapina"].corrispondenza is None
    assert parsed.voci_rottura == frozenset()


def test_colonna_serie_non_confrontabile_assente_la_tendenza_si_calcola() -> None:
    hazard = "hazard,voce,corrispondenza\nRapina,ROB,esatta\n"
    parsed, report = read_sources(con(hazard_table=hazard.encode()), VOCABOLARIO)
    assert report.ok
    assert parsed.voci_rottura == frozenset()
    assert parsed.mappatura["Rapina"].rottura_2016 is False
    assert parsed.mappatura["Rapina"].nota == ""


def test_bom_e_crlf_accettati() -> None:
    def excel(testo: str) -> bytes:
        return b"\xef\xbb\xbf" + testo.replace("\n", "\r\n").encode("utf-8")

    files = con(
        osm_table=excel(OSM_CSV),
        data=excel(DATI_CSV),
        hazard_table=excel(HAZARD_CSV),
    )
    _, report = read_sources(files, VOCABOLARIO)
    assert report.ok
    assert report.warnings == []


def test_formati_owl_e_rdfxml() -> None:
    xml = f"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
    xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Class rdf:about="{NS}Banca">
    <rdfs:label xml:lang="it">Banca</rdfs:label>
    <rdfs:label xml:lang="en">Bank</rdfs:label>
    <rdfs:subClassOf><owl:Restriction>
      <owl:onProperty rdf:resource="{NS}hasRisk"/>
      <owl:someValuesFrom rdf:resource="{NS}Rapina"/>
    </owl:Restriction></rdfs:subClassOf>
  </owl:Class>
  <owl:Class rdf:about="{NS}Rapina"/>
  <owl:Class rdf:about="{NS}Furto"/>
  <owl:Class rdf:about="{NS}Ospedale"/>
</rdf:RDF>"""
    for nome in ("mini.owl", "mini.rdf", "mini.xml", "MINI.OWL"):
        parsed, report = read_sources(
            con(ontology=xml.encode(), ontology_name=nome), VOCABOLARIO
        )
        assert report.ok, nome
        assert parsed.labels["Banca"] == ("Banca", "Bank")


def test_confini_nostri_se_il_file_manca() -> None:
    base, _ = read_sources(file_validi(), VOCABOLARIO)
    parsed, report = read_sources(
        con(boundaries=None), VOCABOLARIO, fallback_luoghi=base.istat.luoghi
    )
    assert report.ok
    assert parsed.istat.luoghi == base.istat.luoghi


def test_luoghi_nostri_senza_dati_non_entrano_nel_set() -> None:
    base, _ = read_sources(file_validi(), VOCABOLARIO)
    (luogo,) = base.istat.luoghi
    altro = replace(luogo, codice="999")
    parsed, report = read_sources(
        con(boundaries=None), VOCABOLARIO, fallback_luoghi=(luogo, altro)
    )
    assert [x.codice for x in parsed.istat.luoghi] == ["001"]
    assert report.warnings == []


def test_confini_caricati_hanno_la_precedenza_sui_nostri() -> None:
    base, _ = read_sources(file_validi(), VOCABOLARIO)
    (luogo,) = base.istat.luoghi
    nostro = replace(luogo, nome="Nome nostro")
    parsed, _ = read_sources(file_validi(), VOCABOLARIO, fallback_luoghi=(nostro,))
    assert parsed.istat.luoghi[0].nome == "Comune di Esempio"


def test_read_sources_solleva_con_il_report() -> None:
    with pytest.raises(SourceValidationError) as exc:
        read_sources(con(osm_table=b""), VOCABOLARIO)
    assert not exc.value.report.ok
    assert "osm_table" in str(exc.value)


# --- bloccanti: ontologia ---


def test_turtle_malformato() -> None:
    report = _report(con(ontology=b"questo non e' turtle @@@"))
    assert _codici(report.errors) == ["ontologia_illeggibile"]
    assert report.errors[0].file == "ontology"


def test_ontologia_vuota() -> None:
    report = _report(con(ontology=b"# solo un commento\n"))
    assert "ontologia_vuota" in _codici(report.errors)


def test_estensione_ontologia_non_supportata() -> None:
    report = _report(con(ontology_name="mini.docx"))
    assert "ontologia_formato_non_supportato" in _codici(report.errors)


def test_ontologia_turtle_non_utf8() -> None:
    report = _report(con(ontology=b"\xff\xfe\x00bad"))
    assert "ontologia_illeggibile" in _codici(report.errors)


def test_vocabolario_non_valido_namespace_e_proprieta() -> None:
    brutto = OntologyVocabulary(
        namespace="non un iri",
        hazard="has Risk>",
        critical_event="hasEvent",
        performer="hasActor",
        vulnerability=("isFragileTo", ""),
    )
    parsed, report = check_sources(file_validi(), brutto)
    assert parsed is None
    assert _codici(report.errors).count("vocabolario_non_valido") == 3
    assert {p.file for p in report.errors} == {"ontology"}


def test_ontologia_senza_restrizioni_sulle_proprieta_configurate() -> None:
    altro = OntologyVocabulary(
        namespace=NS,
        hazard="altraProprieta",
        critical_event="a",
        performer="b",
        vulnerability=("c",),
    )
    parsed, report = check_sources(file_validi(), altro)
    assert parsed is None
    assert "ontologia_senza_restrizioni" in _codici(report.errors)


def test_namespace_sbagliato_non_trova_restrizioni() -> None:
    altro = replace(VOCABOLARIO, namespace="http://example.org/altro#")
    parsed, report = check_sources(file_validi(), altro)
    assert parsed is None
    assert "ontologia_senza_restrizioni" in _codici(report.errors)


# --- bloccanti: tabella OSM ---


def test_classe_osm_assente_dall_ontologia() -> None:
    osm = OSM_CSV + "amenity=cafe,Bar\n"
    report = _report(con(osm_table=osm.encode()))
    (p,) = report.errors
    assert p.code == "classe_assente_dall_ontologia"
    assert p.file == "osm_table"
    assert p.line == 4
    assert "Bar" in p.message


def test_osm_intestazione_mancante() -> None:
    report = _report(con(osm_table=b"amenity=bank,Banca\n"))
    assert "colonna_mancante" in _codici(report.errors)
    assert all(p.file == "osm_table" for p in report.errors)


def test_osm_colonna_mancante_nomina_la_colonna() -> None:
    report = _report(con(osm_table=b"osm_tag\namenity=bank\n"))
    (p,) = report.errors
    assert p.code == "colonna_mancante"
    assert "classe" in p.message


def test_osm_tag_non_valido() -> None:
    osm = OSM_CSV + 'amenity="bank,Banca\nsenza_uguale,Banca\n'
    report = _report(con(osm_table=osm.encode()))
    assert _codici(report.errors) == ["osm_tag_non_valido"] * 2
    assert [p.line for p in report.errors] == [4, 5]


def test_osm_chiave_duplicata_indica_la_riga() -> None:
    osm = OSM_CSV + "amenity=bank,Ospedale\n"
    report = _report(con(osm_table=osm.encode()))
    (p,) = report.errors
    assert p.code == "chiave_duplicata"
    assert p.line == 4


def test_osm_senza_righe() -> None:
    report = _report(con(osm_table=b"osm_tag,classe\n"))
    assert "file_senza_righe" in _codici(report.errors)


def test_osm_file_vuoto() -> None:
    report = _report(con(osm_table=b""))
    assert "file_vuoto" in _codici(report.errors)


def test_separatore_punto_e_virgola_errore_chiaro() -> None:
    report = _report(con(osm_table=b"osm_tag;classe\namenity=bank;Banca\n"))
    (p,) = report.errors
    assert p.code == "separatore_non_valido"
    assert ";" in p.message
    assert "virgola" in p.message
    assert p.file == "osm_table"


def test_csv_non_utf8() -> None:
    contenuto = "osm_tag,classe\nè=è,è\n".encode("latin-1")
    report = _report(con(osm_table=contenuto))
    assert "codifica_non_valida" in _codici(report.errors)


def test_riga_con_troppe_o_poche_celle() -> None:
    osm = OSM_CSV + "amenity=cafe\namenity=bar,Banca,extra\n"
    report = _report(con(osm_table=osm.encode()))
    assert _codici(report.errors) == ["riga_malformata"] * 2
    assert [p.line for p in report.errors] == [4, 5]


# --- bloccanti: tabella hazard ---


def test_hazard_assente_dall_ontologia() -> None:
    hazard = HAZARD_CSV + "Scippo,ROB,esatta,no,\n"
    report = _report(con(hazard_table=hazard.encode()))
    (p,) = report.errors
    assert p.code == "hazard_assente_dall_ontologia"
    assert p.file == "hazard_table"
    assert p.line == 4


def test_voce_della_tabella_assente_dai_dati() -> None:
    hazard = HAZARD_CSV.replace("ROB", "XYZ")
    report = _report(con(hazard_table=hazard.encode()))
    (p,) = report.errors
    assert p.code == "voce_assente_dai_dati"
    assert p.line == 2
    assert "XYZ" in p.message


def test_corrispondenza_non_valida() -> None:
    hazard = "hazard,voce,corrispondenza\nRapina,ROB,quasi\nFurto,THEFT,esatta\n"
    report = _report(con(hazard_table=hazard.encode()))
    (p,) = report.errors
    assert p.code == "corrispondenza_non_valida"
    assert p.line == 2


def test_voce_e_corrispondenza_vuote_insieme() -> None:
    hazard = "hazard,voce,corrispondenza\nRapina,ROB,\nFurto,,esatta\n"
    report = _report(con(hazard_table=hazard.encode()))
    assert _codici(report.errors) == ["voce_corrispondenza_incoerenti"] * 2


def test_serie_non_confrontabile_valore_non_valido() -> None:
    hazard = (
        "hazard,voce,corrispondenza,serie_non_confrontabile\nRapina,ROB,esatta,forse\n"
    )
    report = _report(con(hazard_table=hazard.encode()))
    assert _codici(report.errors) == ["valore_non_valido"]


def test_hazard_duplicato() -> None:
    hazard = HAZARD_CSV + "Furto,THEFT,esatta,no,\n"
    report = _report(con(hazard_table=hazard.encode()))
    (p,) = report.errors
    assert p.code == "chiave_duplicata"
    assert p.line == 4


# --- bloccanti: dati ---


def test_riga_nazionale_mancante() -> None:
    dati = _senza_righe_che_iniziano_con(DATI_CSV, "IT,")
    report = _report(con(data=dati))
    assert "riga_nazionale_mancante" in _codici(report.errors)
    assert all(p.file == "data" for p in report.errors)


def test_dati_chiave_duplicata() -> None:
    dati = DATI_CSV + "001,ROB,rapine,2024,1,1.0,no\n"
    report = _report(con(data=dati.encode()))
    (p,) = report.errors
    assert p.code == "chiave_duplicata"
    assert p.line == 14


def test_dati_valori_non_numerici() -> None:
    dati = (
        DATI_CSV + "001,ROB,rapine,20x4,1,1.0,no\n001,THEFT,furti,2023,tanti,1.0,no\n"
    )
    report = _report(con(data=dati.encode()))
    assert _codici(report.errors) == ["valore_non_valido"] * 2
    assert [p.line for p in report.errors] == [14, 15]


def test_dati_delitti_e_tasso_negativi() -> None:
    dati = DATI_CSV + "001,ROB,rapine,2023,-1,-2.0,no\n"
    report = _report(con(data=dati.encode()))
    assert _codici(report.errors) == ["valore_non_valido"] * 2


def test_dati_tasso_non_finito() -> None:
    dati = DATI_CSV + "001,ROB,rapine,2023,1,nan,no\n001,ROB,rapine,2022,1,inf,no\n"
    report = _report(con(data=dati.encode()))
    assert _codici(report.errors) == ["valore_non_valido"] * 2


def test_dati_sotto_soglia_senza_tasso() -> None:
    dati = DATI_CSV + "001,ROB,rapine,2023,3,,si\n"
    parsed, report = check_sources(con(data=dati.encode()), VOCABOLARIO)
    assert report.ok
    assert parsed is not None
    assert parsed.istat.delitti.valore("001", "ROB", 2023) == ValoreAnno(
        delitti=3, tasso=None, tasso_sotto_soglia=True
    )


def test_dati_sotto_soglia_con_tasso_incoerente() -> None:
    dati = DATI_CSV + "001,ROB,rapine,2023,3,0.1,si\n"
    report = _report(con(data=dati.encode()))
    assert _codici(report.errors) == ["valore_non_valido"]


def test_dati_dato_mancante_diventa_none() -> None:
    dati = DATI_CSV + "001,ROB,rapine,2023,,,\n"
    parsed, report = check_sources(con(data=dati.encode()), VOCABOLARIO)
    assert report.ok
    assert parsed is not None
    assert parsed.istat.delitti.valori["001"]["ROB"]["2023"] is None


def test_dati_delitti_vuoti_con_tasso_incoerente() -> None:
    dati = DATI_CSV + "001,ROB,rapine,2023,,5.0,no\n"
    report = _report(con(data=dati.encode()))
    assert _codici(report.errors) == ["valore_non_valido"]


def test_dati_etichetta_voce_incoerente() -> None:
    dati = DATI_CSV + "001,ROB,altro nome,2023,1,1.0,no\n"
    report = _report(con(data=dati.encode()))
    assert _codici(report.errors) == ["etichetta_voce_incoerente"]


def test_dati_colonne_mancanti_una_per_colonna() -> None:
    dati = "luogo,voce,anno,delitti\nIT,TOT,2024,1\n"
    report = _report(con(data=dati.encode()))
    assert _codici(report.errors) == ["colonna_mancante"] * 2
    messaggi = " ".join(p.message for p in report.errors)
    assert "voce_etichetta" in messaggi
    assert "tasso" in messaggi


def test_dati_tasso_sotto_soglia_colonna_opzionale() -> None:
    dati = "\n".join(",".join(r.split(",")[:6]) for r in DATI_CSV.splitlines()).encode()
    parsed, report = check_sources(con(data=dati), VOCABOLARIO)
    assert report.ok
    assert parsed is not None
    assert parsed.istat.delitti.valore("001", "ROB", 2024) == ValoreAnno(
        delitti=100, tasso=80.0, tasso_sotto_soglia=False
    )


def test_dati_codici_non_ammessi() -> None:
    dati = DATI_CSV + "00 1,ROB,rapine,2023,1,1.0,no\n001,R O B,rapine,2023,1,1.0,no\n"
    report = _report(con(data=dati.encode()))
    assert "codice_non_valido" in _codici(report.errors)


def test_report_con_tutti_i_problemi_di_un_file() -> None:
    osm = (
        "osm_tag,classe\n"
        "amenity=bank,Inesistente\n"
        "amenity=bank,Banca\n"
        "senza_uguale,Banca\n"
        "amenity=hospital,Altra\n"
    )
    report = _report(con(osm_table=osm.encode()))
    assert sorted(_codici(report.errors)) == sorted(
        [
            "classe_assente_dall_ontologia",
            "chiave_duplicata",
            "osm_tag_non_valido",
            "classe_assente_dall_ontologia",
        ]
    )


def test_report_con_problemi_di_file_diversi_in_una_volta() -> None:
    report = _report(
        con(
            ontology=b"@@@",
            osm_table=b"osm_tag;classe\n",
            hazard_table=b"",
            data=b"luogo\n",
        )
    )
    assert {p.file for p in report.errors} == {
        "ontology",
        "osm_table",
        "hazard_table",
        "data",
    }


# --- confini ---


def test_nessun_luogo_con_confini() -> None:
    report = _report(con(boundaries=None))
    assert _codici(report.errors) == ["nessun_luogo_con_confini"]


def test_confini_json_illeggibile() -> None:
    report = _report(con(boundaries=b"{non json"))
    assert "confini_illeggibili" in _codici(report.errors)
    assert all(p.file == "boundaries" for p in report.errors)


def test_confini_non_feature_collection() -> None:
    report = _report(con(boundaries=confini_json({"type": "Feature"})))
    assert "confini_non_validi" in _codici(report.errors)


def test_confini_proprieta_mancanti_e_tipo_errato() -> None:
    brutti = json.loads(json.dumps(CONFINI))
    brutti["features"][0]["properties"] = {"codice": "001", "tipo": "regione"}
    report = _report(con(boundaries=confini_json(brutti)))
    assert "confini_non_validi" in _codici(report.errors)
    messaggi = " ".join(p.message for p in report.errors)
    assert "tipo" in messaggi
    assert "nome" in messaggi


def test_confini_geometria_non_supportata() -> None:
    brutti = json.loads(json.dumps(CONFINI))
    brutti["features"][0]["geometry"] = {"type": "Point", "coordinates": [1, 2]}
    report = _report(con(boundaries=confini_json(brutti)))
    assert "confini_non_validi" in _codici(report.errors)


def test_confini_coordinate_fuori_range() -> None:
    brutti = json.loads(json.dumps(CONFINI))
    brutti["features"][0]["geometry"]["coordinates"][0][1] = [999.0, 41.0]
    report = _report(con(boundaries=confini_json(brutti)))
    assert "confini_non_validi" in _codici(report.errors)


def test_confini_anello_troppo_corto() -> None:
    brutti = json.loads(json.dumps(CONFINI))
    brutti["features"][0]["geometry"]["coordinates"] = [[[1.0, 1.0], [2.0, 2.0]]]
    report = _report(con(boundaries=confini_json(brutti)))
    assert "confini_non_validi" in _codici(report.errors)


def test_confini_codice_duplicato() -> None:
    doppio = json.loads(json.dumps(CONFINI))
    doppio["features"].append(doppio["features"][0])
    report = _report(con(boundaries=confini_json(doppio)))
    assert "chiave_duplicata" in _codici(report.errors)


def test_confini_multipolygon_accettato() -> None:
    multi = json.loads(json.dumps(CONFINI))
    anello = multi["features"][0]["geometry"]["coordinates"]
    multi["features"][0]["geometry"] = {
        "type": "MultiPolygon",
        "coordinates": [anello],
    }
    parsed, report = check_sources(con(boundaries=confini_json(multi)), VOCABOLARIO)
    assert report.ok
    assert parsed is not None


def test_avviso_luogo_senza_confini_se_altri_ne_hanno() -> None:
    dati = DATI_CSV + "002,TOT,totale,2024,10,1.0,no\n"
    parsed, report = check_sources(con(data=dati.encode()), VOCABOLARIO)
    assert report.ok
    assert parsed is not None
    assert _codici(report.warnings) == ["luogo_senza_confini"]
    assert [x.codice for x in parsed.istat.luoghi] == ["001"]
    assert "002" in report.warnings[0].message


def test_avviso_confini_di_luogo_senza_dati() -> None:
    extra = json.loads(json.dumps(CONFINI))
    secondo = json.loads(json.dumps(CONFINI["features"][0]))
    secondo["properties"]["codice"] = "777"
    extra["features"].append(secondo)
    parsed, report = check_sources(con(boundaries=confini_json(extra)), VOCABOLARIO)
    assert report.ok
    assert parsed is not None
    assert _codici(report.warnings) == ["luogo_senza_dati"]
    assert [x.codice for x in parsed.istat.luoghi] == ["001"]


# --- avvisi ---


def test_avviso_colonna_in_piu() -> None:
    osm = "osm_tag,classe,commento\namenity=bank,Banca,ok\namenity=hospital,Ospedale,\n"
    parsed, report = check_sources(con(osm_table=osm.encode()), VOCABOLARIO)
    assert report.ok
    assert parsed is not None
    (w,) = report.warnings
    assert w.code == "colonna_in_piu"
    assert w.file == "osm_table"
    assert "commento" in w.message


def test_avviso_etichette_mancanti_non_blocca() -> None:
    ttl = ONTOLOGIA_TTL.replace(' rdfs:label "Rapina"@it, "Robbery"@en', "")
    ttl = ttl.replace(', "Bank"@en', "")
    parsed, report = check_sources(con(ontology=ttl.encode()), VOCABOLARIO)
    assert report.ok
    assert parsed is not None
    assert set(_codici(report.warnings)) == {"etichetta_mancante"}
    assert {p.file for p in report.warnings} == {"ontology"}
    # ripiego: nome della classe con l'underscore sostituito da uno spazio
    assert parsed.labels["Rapina"] == ("Rapina", "Rapina")
    assert parsed.labels["Banca"] == ("Banca", "Banca")


def test_ripiego_etichetta_sostituisce_underscore() -> None:
    ttl = ONTOLOGIA_TTL.replace("m:Rapina a", "m:Rapina_a_mano_armata a").replace(
        "owl:someValuesFrom m:Rapina ]", "owl:someValuesFrom m:Rapina_a_mano_armata ]"
    )
    ttl = ttl.replace(' rdfs:label "Rapina"@it, "Robbery"@en', "")
    hazard = HAZARD_CSV.replace("Rapina,", "Rapina_a_mano_armata,")
    parsed, report = check_sources(
        con(ontology=ttl.encode(), hazard_table=hazard.encode()), VOCABOLARIO
    )
    assert report.ok
    assert parsed is not None
    assert parsed.labels["Rapina_a_mano_armata"] == (
        "Rapina a mano armata",
        "Rapina a mano armata",
    )


def test_avviso_anno_di_confronto_assente() -> None:
    righe = [r for r in DATI_CSV.splitlines() if ",2014," not in r]
    parsed, report = check_sources(con(data="\n".join(righe).encode()), VOCABOLARIO)
    assert report.ok
    assert parsed is not None
    assert "anno_confronto_assente" in _codici(report.warnings)


def test_avviso_totale_mancante_per_un_luogo() -> None:
    dati = _senza_righe_che_iniziano_con(DATI_CSV, "001,TOT")
    parsed, report = check_sources(con(data=dati), VOCABOLARIO)
    assert report.ok
    assert parsed is not None
    assert "totale_mancante" in _codici(report.warnings)


def test_avviso_serie_non_confrontabile_incoerente_nella_stessa_voce() -> None:
    hazard = (
        "hazard,voce,corrispondenza,serie_non_confrontabile\n"
        "Rapina,ROB,esatta,si\nFurto,ROB,piu_larga,no\n"
    )
    parsed, report = check_sources(con(hazard_table=hazard.encode()), VOCABOLARIO)
    assert report.ok
    assert parsed is not None
    assert "serie_non_confrontabile_incoerente" in _codici(report.warnings)
    assert parsed.voci_rottura == frozenset({"ROB"})
    assert parsed.mappatura["Furto"].rottura_2016 is True
