"""Reading and checking of the five source files (#415)."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from crime_risk_analyzer.istat.data import ITALY_CODE, YearValue
from crime_risk_analyzer.sources.ontology_reader import _readable_cause  # pyright: ignore[reportPrivateUsage]
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
from tests.sources._factories import (
    BOUNDARIES,
    DATA_CSV,
    HAZARD_CSV,
    NS,
    ONTOLOGY_TTL,
    OSM_CSV,
    VOCABULARY,
    boundaries_json,
    valid_files,
    with_fields,
)


def _report(files: UploadedFiles) -> ValidationReport:
    parsed, report = check_sources(files, VOCABULARY)
    assert parsed is None
    assert not report.ok
    return report


def _codes(problems: list[Problem]) -> list[str]:
    return [p.code for p in problems]


def _without_lines_starting_with(text: str, prefix: str) -> bytes:
    lines = [r for r in text.splitlines() if not r.startswith(prefix)]
    return "\n".join(lines).encode("utf-8")


# --- valid case ---


def test_valid_case_returns_the_parsed_sources() -> None:
    parsed, report = read_sources(valid_files(), VOCABULARY)
    assert isinstance(parsed, ParsedSources)
    assert report.ok
    assert report.errors == []
    assert report.warnings == []
    assert parsed.vocabulary == VOCABULARY
    assert len(parsed.graph) > 0
    assert parsed.osm_to_class == {
        "amenity=bank": "Banca",
        "amenity=hospital": "Ospedale",
    }
    assert parsed.family_order == ("amenity",)


def test_it_en_labels_from_rdfs_label() -> None:
    parsed, _ = read_sources(valid_files(), VOCABULARY)
    assert parsed.labels["Banca"] == ("Banca", "Bank")
    assert parsed.labels["Rapina"] == ("Rapina", "Robbery")


def test_data_same_istat_logic() -> None:
    parsed, _ = read_sources(valid_files(), VOCABULARY)
    crimes = parsed.istat.delitti
    assert crimes.anno == 2024
    assert crimes.anno_confronto == 2014
    assert crimes.voci == {"TOT": "totale", "ROB": "rapine", "THEFT": "furti"}
    assert crimes.valore("001", "ROB", 2024) == YearValue(
        delitti=100, tasso=80.0, tasso_sotto_soglia=False
    )
    assert crimes.valore(ITALY_CODE, "ROB", 2014) is not None
    assert crimes.valore("001", "ROB", 1999) is None


def test_version_is_the_hash_of_the_data_file() -> None:
    parsed, _ = read_sources(valid_files(), VOCABULARY)
    assert len(parsed.versione) == 12
    assert parsed.istat.versione == parsed.versione
    other_files = with_fields(data=DATA_CSV.replace("5000", "5001").encode("utf-8"))
    assert read_sources(other_files, VOCABULARY)[0].versione != parsed.versione


def test_places_with_loaded_boundaries() -> None:
    parsed, _ = read_sources(valid_files(), VOCABULARY)
    (place,) = parsed.istat.luoghi
    assert (place.codice, place.tipo) == ("001", "comune")
    assert place.nome == "Comune di Esempio"
    assert place.nome_breve == "Esempio"
    assert place.provincia is None
    assert place.bbox == (12.0, 41.0, 13.0, 42.0)
    lon, lat = place.punto_interno
    assert 12.0 < lon < 13.0
    assert 41.0 < lat < 42.0


def test_interior_point_inside_a_c_shaped_polygon() -> None:
    # The center of the box falls in the "gap" of the C: the interior point does not.
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
    shape = json.loads(json.dumps(BOUNDARIES))
    shape["features"][0]["geometry"]["coordinates"] = [c]
    parsed, report = read_sources(
        with_fields(boundaries=boundaries_json(shape)), VOCABULARY
    )
    assert report.ok
    from crime_risk_analyzer.models.geo import point_in_multipolygon

    (place,) = parsed.istat.luoghi
    assert point_in_multipolygon(place.punto_interno, place.confine)


def test_hazard_item_mapping() -> None:
    parsed, _ = read_sources(valid_files(), VOCABULARY)
    robbery = parsed.mappatura["Rapina"]
    assert robbery.voce_istat == "ROB"
    assert robbery.corrispondenza == "esatta"
    assert robbery.rottura_2016 is False
    theft = parsed.mappatura["Furto"]
    assert (theft.voce_istat, theft.corrispondenza) == ("THEFT", "piu_larga")
    assert theft.rottura_2016 is True
    assert theft.nota == "Serie interrotta nel 2016"
    assert parsed.voci_rottura == frozenset({"THEFT"})


def test_hazard_without_item() -> None:
    hazard = "hazard,voce,corrispondenza\nRapina,,\nFurto,THEFT,esatta\n"
    parsed, report = read_sources(with_fields(hazard_table=hazard.encode()), VOCABULARY)
    assert report.ok
    assert parsed.mappatura["Rapina"].voce_istat is None
    assert parsed.mappatura["Rapina"].corrispondenza is None
    assert parsed.voci_rottura == frozenset()


def test_missing_non_comparable_series_column_trend_is_computed() -> None:
    hazard = "hazard,voce,corrispondenza\nRapina,ROB,esatta\n"
    parsed, report = read_sources(with_fields(hazard_table=hazard.encode()), VOCABULARY)
    assert report.ok
    assert parsed.voci_rottura == frozenset()
    assert parsed.mappatura["Rapina"].rottura_2016 is False
    assert parsed.mappatura["Rapina"].nota == ""


def test_bom_and_crlf_accepted() -> None:
    def excel(text: str) -> bytes:
        return b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8")

    files = with_fields(
        osm_table=excel(OSM_CSV),
        data=excel(DATA_CSV),
        hazard_table=excel(HAZARD_CSV),
    )
    _, report = read_sources(files, VOCABULARY)
    assert report.ok
    assert report.warnings == []


def test_owl_and_rdfxml_formats() -> None:
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
    for name in ("mini.owl", "mini.rdf", "mini.xml", "MINI.OWL"):
        parsed, report = read_sources(
            with_fields(ontology=xml.encode(), ontology_name=name), VOCABULARY
        )
        assert report.ok, name
        assert parsed.labels["Banca"] == ("Banca", "Bank")


def test_our_boundaries_if_the_file_is_missing() -> None:
    base, _ = read_sources(valid_files(), VOCABULARY)
    parsed, report = read_sources(
        with_fields(boundaries=None), VOCABULARY, fallback_places=base.istat.luoghi
    )
    assert report.ok
    assert parsed.istat.luoghi == base.istat.luoghi


def test_our_places_without_data_do_not_enter_the_set() -> None:
    base, _ = read_sources(valid_files(), VOCABULARY)
    (place,) = base.istat.luoghi
    other = replace(place, codice="999")
    parsed, report = read_sources(
        with_fields(boundaries=None), VOCABULARY, fallback_places=(place, other)
    )
    assert [x.codice for x in parsed.istat.luoghi] == ["001"]
    assert report.warnings == []


def test_loaded_boundaries_take_precedence_over_ours() -> None:
    base, _ = read_sources(valid_files(), VOCABULARY)
    (place,) = base.istat.luoghi
    ours = replace(place, nome="Nome nostro")
    parsed, _ = read_sources(valid_files(), VOCABULARY, fallback_places=(ours,))
    assert parsed.istat.luoghi[0].nome == "Comune di Esempio"


def test_read_sources_raises_with_the_report() -> None:
    with pytest.raises(SourceValidationError) as exc:
        read_sources(with_fields(osm_table=b""), VOCABULARY)
    assert not exc.value.report.ok
    assert "osm_table" in str(exc.value)


# --- blocking: ontology ---


def test_malformed_turtle() -> None:
    report = _report(with_fields(ontology=b"questo non e' turtle @@@"))
    assert _codes(report.errors) == ["ontologia_illeggibile"]
    assert report.errors[0].file == "ontology"


def test_malformed_turtle_message_without_file_fragment() -> None:
    """#439: line and cause yes, the dump of the file bytes no."""
    content = (
        b"@prefix a: <http://x/> .\na:b a:c a:d .\na:e a:f ;; SEGRETO-NEL-FILE @@@ .\n"
    )
    report = _report(with_fields(ontology=content))
    message = report.errors[0].message
    assert "riga 3" in message
    assert "objectList expected" in message
    assert "SEGRETO-NEL-FILE" not in message
    assert "prefix" not in message
    assert "\\n" not in message
    assert "b'" not in message


def test_turtle_unclosed_string_message_without_content() -> None:
    """#439: rdflib non-BadSyntax errors do not leak the file either."""
    exc = Exception(
        "at line 2 of <>:\nQuote expected in string at ^ in tp://x/> .\n"
        'a:e a:f "^SEGRETO'
    )
    message = _readable_cause(exc)
    assert message == "riga 2: Quote expected in string"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("\nfoo", "foo"),
        ("  \n  bar  \nbaz", "bar"),
        ("  ", "Exception"),
        ("", "Exception"),
        ("at line 4 of <>:\n", "riga 4: Exception"),
    ],
)
def test_readable_cause_first_non_empty_line(text: str, expected: str) -> None:
    assert _readable_cause(Exception(text)) == expected


def test_unicode_decode_error_message_without_file_bytes() -> None:
    with pytest.raises(UnicodeDecodeError) as exc_info:
        b"\xff\xfe\x00bad".decode("utf-8")
    assert _readable_cause(exc_info.value).startswith("'utf-8' codec can't decode byte")
    report = _report(with_fields(ontology=b"\xff\xfe\x00bad"))
    assert report.errors[0].message.startswith("ontologia non leggibile come turtle")


def test_malformed_xml_short_message_without_content() -> None:
    report = _report(
        with_fields(ontology=b"<rdf:RDF><SEGRETO", ontology_name="mini.owl")
    )
    message = report.errors[0].message
    assert "ontologia non leggibile come xml" in message
    assert "SEGRETO" not in message
    assert "\n" not in message


def test_empty_ontology() -> None:
    report = _report(with_fields(ontology=b"# solo un commento\n"))
    assert "ontologia_vuota" in _codes(report.errors)


def test_unsupported_ontology_extension() -> None:
    report = _report(with_fields(ontology_name="mini.docx"))
    assert "ontologia_formato_non_supportato" in _codes(report.errors)


def test_non_utf8_turtle_ontology() -> None:
    report = _report(with_fields(ontology=b"\xff\xfe\x00bad"))
    assert "ontologia_illeggibile" in _codes(report.errors)


def test_invalid_vocabulary_namespace_and_properties() -> None:
    bad_vocabulary = OntologyVocabulary(
        namespace="non un iri",
        hazard="has Risk>",
        critical_event="hasEvent",
        performer="hasActor",
        vulnerability=("isFragileTo", ""),
    )
    parsed, report = check_sources(valid_files(), bad_vocabulary)
    assert parsed is None
    assert _codes(report.errors).count("vocabolario_non_valido") == 3
    assert {p.file for p in report.errors} == {"ontology"}


def test_ontology_without_restrictions_on_the_configured_properties() -> None:
    other = OntologyVocabulary(
        namespace=NS,
        hazard="altraProprieta",
        critical_event="a",
        performer="b",
        vulnerability=("c",),
    )
    parsed, report = check_sources(valid_files(), other)
    assert parsed is None
    assert "ontologia_senza_restrizioni" in _codes(report.errors)


def test_wrong_namespace_finds_no_restrictions() -> None:
    other = replace(VOCABULARY, namespace="http://example.org/altro#")
    parsed, report = check_sources(valid_files(), other)
    assert parsed is None
    assert "ontologia_senza_restrizioni" in _codes(report.errors)


# --- blocking: OSM table ---


def test_osm_class_missing_from_the_ontology() -> None:
    osm = OSM_CSV + "amenity=cafe,Bar\n"
    report = _report(with_fields(osm_table=osm.encode()))
    (p,) = report.errors
    assert p.code == "classe_assente_dall_ontologia"
    assert p.file == "osm_table"
    assert p.line == 4
    assert "Bar" in p.message


def test_osm_missing_header() -> None:
    report = _report(with_fields(osm_table=b"amenity=bank,Banca\n"))
    assert "colonna_mancante" in _codes(report.errors)
    assert all(p.file == "osm_table" for p in report.errors)


def test_osm_missing_column_names_the_column() -> None:
    report = _report(with_fields(osm_table=b"osm_tag\namenity=bank\n"))
    (p,) = report.errors
    assert p.code == "colonna_mancante"
    assert "classe" in p.message


def test_invalid_osm_tag() -> None:
    osm = OSM_CSV + 'amenity="bank,Banca\nsenza_uguale,Banca\n'
    report = _report(with_fields(osm_table=osm.encode()))
    assert _codes(report.errors) == ["osm_tag_non_valido"] * 2
    assert [p.line for p in report.errors] == [4, 5]


def test_osm_duplicate_key_reports_the_line() -> None:
    osm = OSM_CSV + "amenity=bank,Ospedale\n"
    report = _report(with_fields(osm_table=osm.encode()))
    (p,) = report.errors
    assert p.code == "chiave_duplicata"
    assert p.line == 4


def test_osm_without_rows() -> None:
    report = _report(with_fields(osm_table=b"osm_tag,classe\n"))
    assert "file_senza_righe" in _codes(report.errors)


def test_osm_empty_file() -> None:
    report = _report(with_fields(osm_table=b""))
    assert "file_vuoto" in _codes(report.errors)


def test_semicolon_separator_clear_error() -> None:
    report = _report(with_fields(osm_table=b"osm_tag;classe\namenity=bank;Banca\n"))
    (p,) = report.errors
    assert p.code == "separatore_non_valido"
    assert ";" in p.message
    assert "virgola" in p.message
    assert p.file == "osm_table"


def test_non_utf8_csv() -> None:
    content = "osm_tag,classe\nè=è,è\n".encode("latin-1")
    report = _report(with_fields(osm_table=content))
    assert "codifica_non_valida" in _codes(report.errors)


def test_row_with_too_many_or_too_few_cells() -> None:
    osm = OSM_CSV + "amenity=cafe\namenity=bar,Banca,extra\n"
    report = _report(with_fields(osm_table=osm.encode()))
    assert _codes(report.errors) == ["riga_malformata"] * 2
    assert [p.line for p in report.errors] == [4, 5]


# --- blocking: hazard table ---


def test_hazard_missing_from_the_ontology() -> None:
    hazard = HAZARD_CSV + "Scippo,ROB,esatta,no,\n"
    report = _report(with_fields(hazard_table=hazard.encode()))
    (p,) = report.errors
    assert p.code == "hazard_assente_dall_ontologia"
    assert p.file == "hazard_table"
    assert p.line == 4


def test_table_item_missing_from_the_data() -> None:
    hazard = HAZARD_CSV.replace("ROB", "XYZ")
    report = _report(with_fields(hazard_table=hazard.encode()))
    (p,) = report.errors
    assert p.code == "voce_assente_dai_dati"
    assert p.line == 2
    assert "XYZ" in p.message


def test_invalid_match() -> None:
    hazard = "hazard,voce,corrispondenza\nRapina,ROB,quasi\nFurto,THEFT,esatta\n"
    report = _report(with_fields(hazard_table=hazard.encode()))
    (p,) = report.errors
    assert p.code == "corrispondenza_non_valida"
    assert p.line == 2


def test_item_and_match_empty_together() -> None:
    hazard = "hazard,voce,corrispondenza\nRapina,ROB,\nFurto,,esatta\n"
    report = _report(with_fields(hazard_table=hazard.encode()))
    assert _codes(report.errors) == ["voce_corrispondenza_incoerenti"] * 2


def test_non_comparable_series_invalid_value() -> None:
    hazard = (
        "hazard,voce,corrispondenza,serie_non_confrontabile\nRapina,ROB,esatta,forse\n"
    )
    report = _report(with_fields(hazard_table=hazard.encode()))
    assert _codes(report.errors) == ["valore_non_valido"]


def test_duplicate_hazard() -> None:
    hazard = HAZARD_CSV + "Furto,THEFT,esatta,no,\n"
    report = _report(with_fields(hazard_table=hazard.encode()))
    (p,) = report.errors
    assert p.code == "chiave_duplicata"
    assert p.line == 4


# --- blocking: data ---


def test_missing_national_row() -> None:
    data_csv = _without_lines_starting_with(DATA_CSV, "IT,")
    report = _report(with_fields(data=data_csv))
    assert "riga_nazionale_mancante" in _codes(report.errors)
    assert all(p.file == "data" for p in report.errors)


def test_data_duplicate_key() -> None:
    data_csv = DATA_CSV + "001,ROB,rapine,2024,1,1.0,no\n"
    report = _report(with_fields(data=data_csv.encode()))
    (p,) = report.errors
    assert p.code == "chiave_duplicata"
    assert p.line == 14


def test_data_non_numeric_values() -> None:
    data_csv = (
        DATA_CSV + "001,ROB,rapine,20x4,1,1.0,no\n001,THEFT,furti,2023,tanti,1.0,no\n"
    )
    report = _report(with_fields(data=data_csv.encode()))
    assert _codes(report.errors) == ["valore_non_valido"] * 2
    assert [p.line for p in report.errors] == [14, 15]


def test_data_negative_crimes_and_rate() -> None:
    data_csv = DATA_CSV + "001,ROB,rapine,2023,-1,-2.0,no\n"
    report = _report(with_fields(data=data_csv.encode()))
    assert _codes(report.errors) == ["valore_non_valido"] * 2


def test_data_non_finite_rate() -> None:
    data_csv = DATA_CSV + "001,ROB,rapine,2023,1,nan,no\n001,ROB,rapine,2022,1,inf,no\n"
    report = _report(with_fields(data=data_csv.encode()))
    assert _codes(report.errors) == ["valore_non_valido"] * 2


def test_data_below_threshold_without_rate() -> None:
    data_csv = DATA_CSV + "001,ROB,rapine,2023,3,,si\n"
    parsed, report = check_sources(with_fields(data=data_csv.encode()), VOCABULARY)
    assert report.ok
    assert parsed is not None
    assert parsed.istat.delitti.valore("001", "ROB", 2023) == YearValue(
        delitti=3, tasso=None, tasso_sotto_soglia=True
    )


def test_data_below_threshold_with_inconsistent_rate() -> None:
    data_csv = DATA_CSV + "001,ROB,rapine,2023,3,0.1,si\n"
    report = _report(with_fields(data=data_csv.encode()))
    assert _codes(report.errors) == ["valore_non_valido"]


def test_data_missing_value_becomes_none() -> None:
    data_csv = DATA_CSV + "001,ROB,rapine,2023,,,\n"
    parsed, report = check_sources(with_fields(data=data_csv.encode()), VOCABULARY)
    assert report.ok
    assert parsed is not None
    assert parsed.istat.delitti.valori["001"]["ROB"]["2023"] is None


def test_data_empty_crimes_with_inconsistent_rate() -> None:
    data_csv = DATA_CSV + "001,ROB,rapine,2023,,5.0,no\n"
    report = _report(with_fields(data=data_csv.encode()))
    assert _codes(report.errors) == ["valore_non_valido"]


def test_data_inconsistent_item_label() -> None:
    data_csv = DATA_CSV + "001,ROB,altro nome,2023,1,1.0,no\n"
    report = _report(with_fields(data=data_csv.encode()))
    assert _codes(report.errors) == ["etichetta_voce_incoerente"]


def test_data_missing_columns_one_per_column() -> None:
    data_csv = "luogo,voce,anno,delitti\nIT,TOT,2024,1\n"
    report = _report(with_fields(data=data_csv.encode()))
    assert _codes(report.errors) == ["colonna_mancante"] * 2
    messages = " ".join(p.message for p in report.errors)
    assert "voce_etichetta" in messages
    assert "tasso" in messages


def test_data_below_threshold_rate_column_optional() -> None:
    data_csv = "\n".join(
        ",".join(r.split(",")[:6]) for r in DATA_CSV.splitlines()
    ).encode()
    parsed, report = check_sources(with_fields(data=data_csv), VOCABULARY)
    assert report.ok
    assert parsed is not None
    assert parsed.istat.delitti.valore("001", "ROB", 2024) == YearValue(
        delitti=100, tasso=80.0, tasso_sotto_soglia=False
    )


def test_data_disallowed_codes() -> None:
    data_csv = (
        DATA_CSV + "00 1,ROB,rapine,2023,1,1.0,no\n001,R O B,rapine,2023,1,1.0,no\n"
    )
    report = _report(with_fields(data=data_csv.encode()))
    assert "codice_non_valido" in _codes(report.errors)


def test_report_with_all_the_problems_of_a_file() -> None:
    osm = (
        "osm_tag,classe\n"
        "amenity=bank,Inesistente\n"
        "amenity=bank,Banca\n"
        "senza_uguale,Banca\n"
        "amenity=hospital,Altra\n"
    )
    report = _report(with_fields(osm_table=osm.encode()))
    assert sorted(_codes(report.errors)) == sorted(
        [
            "classe_assente_dall_ontologia",
            "chiave_duplicata",
            "osm_tag_non_valido",
            "classe_assente_dall_ontologia",
        ]
    )


def test_report_with_problems_of_different_files_at_once() -> None:
    report = _report(
        with_fields(
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


# --- boundaries ---


def test_no_place_with_boundaries() -> None:
    report = _report(with_fields(boundaries=None))
    assert _codes(report.errors) == ["nessun_luogo_con_confini"]


def test_unreadable_boundaries_json() -> None:
    report = _report(with_fields(boundaries=b"{non json"))
    assert "confini_illeggibili" in _codes(report.errors)
    assert all(p.file == "boundaries" for p in report.errors)


def test_boundaries_not_a_feature_collection() -> None:
    report = _report(with_fields(boundaries=boundaries_json({"type": "Feature"})))
    assert "confini_non_validi" in _codes(report.errors)


def test_boundaries_missing_properties_and_wrong_type() -> None:
    bad = json.loads(json.dumps(BOUNDARIES))
    bad["features"][0]["properties"] = {"codice": "001", "tipo": "regione"}
    report = _report(with_fields(boundaries=boundaries_json(bad)))
    assert "confini_non_validi" in _codes(report.errors)
    messages = " ".join(p.message for p in report.errors)
    assert "tipo" in messages
    assert "nome" in messages


def test_boundaries_unsupported_geometry() -> None:
    bad = json.loads(json.dumps(BOUNDARIES))
    bad["features"][0]["geometry"] = {"type": "Point", "coordinates": [1, 2]}
    report = _report(with_fields(boundaries=boundaries_json(bad)))
    assert "confini_non_validi" in _codes(report.errors)


def test_boundaries_coordinates_out_of_range() -> None:
    bad = json.loads(json.dumps(BOUNDARIES))
    bad["features"][0]["geometry"]["coordinates"][0][1] = [999.0, 41.0]
    report = _report(with_fields(boundaries=boundaries_json(bad)))
    assert "confini_non_validi" in _codes(report.errors)


def test_boundaries_ring_too_short() -> None:
    bad = json.loads(json.dumps(BOUNDARIES))
    bad["features"][0]["geometry"]["coordinates"] = [[[1.0, 1.0], [2.0, 2.0]]]
    report = _report(with_fields(boundaries=boundaries_json(bad)))
    assert "confini_non_validi" in _codes(report.errors)


def test_boundaries_duplicate_code() -> None:
    doubled = json.loads(json.dumps(BOUNDARIES))
    doubled["features"].append(doubled["features"][0])
    report = _report(with_fields(boundaries=boundaries_json(doubled)))
    assert "chiave_duplicata" in _codes(report.errors)


def test_boundaries_multipolygon_accepted() -> None:
    multi = json.loads(json.dumps(BOUNDARIES))
    ring = multi["features"][0]["geometry"]["coordinates"]
    multi["features"][0]["geometry"] = {
        "type": "MultiPolygon",
        "coordinates": [ring],
    }
    parsed, report = check_sources(
        with_fields(boundaries=boundaries_json(multi)), VOCABULARY
    )
    assert report.ok
    assert parsed is not None


def test_warning_place_without_boundaries_if_others_have_them() -> None:
    data_csv = DATA_CSV + "002,TOT,totale,2024,10,1.0,no\n"
    parsed, report = check_sources(with_fields(data=data_csv.encode()), VOCABULARY)
    assert report.ok
    assert parsed is not None
    assert _codes(report.warnings) == ["luogo_senza_confini"]
    assert [x.codice for x in parsed.istat.luoghi] == ["001"]
    assert "002" in report.warnings[0].message


def test_warning_boundaries_of_place_without_data() -> None:
    extra = json.loads(json.dumps(BOUNDARIES))
    second = json.loads(json.dumps(BOUNDARIES["features"][0]))
    second["properties"]["codice"] = "777"
    extra["features"].append(second)
    parsed, report = check_sources(
        with_fields(boundaries=boundaries_json(extra)), VOCABULARY
    )
    assert report.ok
    assert parsed is not None
    assert _codes(report.warnings) == ["luogo_senza_dati"]
    assert [x.codice for x in parsed.istat.luoghi] == ["001"]


# --- warnings ---


def test_warning_extra_column() -> None:
    osm = "osm_tag,classe,commento\namenity=bank,Banca,ok\namenity=hospital,Ospedale,\n"
    parsed, report = check_sources(with_fields(osm_table=osm.encode()), VOCABULARY)
    assert report.ok
    assert parsed is not None
    (w,) = report.warnings
    assert w.code == "colonna_in_piu"
    assert w.file == "osm_table"
    assert "commento" in w.message


def test_warning_missing_labels_does_not_block() -> None:
    ttl = ONTOLOGY_TTL.replace(' rdfs:label "Rapina"@it, "Robbery"@en', "")
    ttl = ttl.replace(', "Bank"@en', "")
    parsed, report = check_sources(with_fields(ontology=ttl.encode()), VOCABULARY)
    assert report.ok
    assert parsed is not None
    assert set(_codes(report.warnings)) == {"etichetta_mancante"}
    assert {p.file for p in report.warnings} == {"ontology"}
    # fallback: class name with the underscore replaced by a space
    assert parsed.labels["Rapina"] == ("Rapina", "Rapina")
    assert parsed.labels["Banca"] == ("Banca", "Banca")


def test_label_fallback_replaces_underscore() -> None:
    ttl = ONTOLOGY_TTL.replace("m:Rapina a", "m:Rapina_a_mano_armata a").replace(
        "owl:someValuesFrom m:Rapina ]", "owl:someValuesFrom m:Rapina_a_mano_armata ]"
    )
    ttl = ttl.replace(' rdfs:label "Rapina"@it, "Robbery"@en', "")
    hazard = HAZARD_CSV.replace("Rapina,", "Rapina_a_mano_armata,")
    parsed, report = check_sources(
        with_fields(ontology=ttl.encode(), hazard_table=hazard.encode()), VOCABULARY
    )
    assert report.ok
    assert parsed is not None
    assert parsed.labels["Rapina_a_mano_armata"] == (
        "Rapina a mano armata",
        "Rapina a mano armata",
    )


def test_warning_missing_comparison_year() -> None:
    lines = [r for r in DATA_CSV.splitlines() if ",2014," not in r]
    parsed, report = check_sources(
        with_fields(data="\n".join(lines).encode()), VOCABULARY
    )
    assert report.ok
    assert parsed is not None
    assert "anno_confronto_assente" in _codes(report.warnings)


def test_warning_missing_total_for_a_place() -> None:
    data_csv = _without_lines_starting_with(DATA_CSV, "001,TOT")
    parsed, report = check_sources(with_fields(data=data_csv), VOCABULARY)
    assert report.ok
    assert parsed is not None
    assert "totale_mancante" in _codes(report.warnings)


def test_warning_inconsistent_non_comparable_series_in_the_same_item() -> None:
    hazard = (
        "hazard,voce,corrispondenza,serie_non_confrontabile\n"
        "Rapina,ROB,esatta,si\nFurto,ROB,piu_larga,no\n"
    )
    parsed, report = check_sources(
        with_fields(hazard_table=hazard.encode()), VOCABULARY
    )
    assert report.ok
    assert parsed is not None
    assert "serie_non_confrontabile_incoerente" in _codes(report.warnings)
    assert parsed.voci_rottura == frozenset({"ROB"})
    assert parsed.mappatura["Furto"].rottura_2016 is True
