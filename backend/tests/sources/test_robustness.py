"""Robustness of the source check (#415): hostile inputs never raise.

``check_sources`` must always answer with a report: no exception, no CPU
blocking, no report of millions of rows.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace

import pytest

from crime_risk_analyzer.sources import parsing
from crime_risk_analyzer.sources.csv_reader import MAX_ROW_ERRORS, MAX_ROWS, read_csv
from crime_risk_analyzer.sources.parsing import UploadedFiles, check_sources
from crime_risk_analyzer.sources.report import (
    CODE_OTHER_PROBLEMS,
    MAX_PROBLEMS_PER_FILE,
    ValidationReport,
)
from tests.sources._factories import (
    BOUNDARIES,
    DATA_CSV,
    NS,
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


def _codes(report: ValidationReport) -> list[str]:
    return [p.code for p in report.errors]


# --- 1. nested XML entities (billion laughs) ---


def _xml_with_entities(declarations: str, body: str = "") -> bytes:
    return f"""<?xml version="1.0"?>
<!DOCTYPE rdf:RDF [{declarations}]>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Class rdf:about="{NS}Banca">{body}</owl:Class>
</rdf:RDF>""".encode()


def test_billion_laughs_rejected_immediately() -> None:
    declarations = '<!ENTITY l0 "ha">' + "".join(
        f'<!ENTITY l{n} "{f"&l{n - 1};" * 10}">' for n in range(1, 8)
    )
    xml = _xml_with_entities(declarations, "&l7;")
    start = time.monotonic()
    report = _report(with_fields(ontology=xml, ontology_name="x.owl"))
    assert time.monotonic() - start < 2
    assert _codes(report) == ["entita_xml_annidata"]
    assert report.errors[0].file == "ontology"


def test_too_many_entities_rejected() -> None:
    declarations = "".join(f'<!ENTITY e{n} "x">' for n in range(101))
    report = _report(
        with_fields(ontology=_xml_with_entities(declarations), ontology_name="x.owl")
    )
    assert _codes(report) == ["entita_xml_troppe"]


def test_entities_too_large_in_total_rejected() -> None:
    declarations = "".join(f'<!ENTITY e{n} "{"x" * 3000}">' for n in range(4))
    report = _report(
        with_fields(ontology=_xml_with_entities(declarations), ontology_name="x.owl")
    )
    assert _codes(report) == ["entita_xml_troppe"]


def test_non_simple_entity_declaration_rejected() -> None:
    report = _report(
        with_fields(
            ontology=_xml_with_entities("<!ENTITY e1 x>"),
            ontology_name="x.owl",
        )
    )
    assert _codes(report) == ["entita_xml_non_ammessa"]


# --- 2. hostile GeoJSON: never exceptions ---


def _with_geometry(geometry: object) -> UploadedFiles:
    bad = json.loads(json.dumps(BOUNDARIES))
    bad["features"][0]["geometry"] = geometry
    return with_fields(boundaries=boundaries_json(bad))


def test_deeply_nested_json() -> None:
    report = _report(with_fields(boundaries=b"[" * 100_000))
    assert "confini_illeggibili" in _codes(report)


def test_multipolygon_without_coordinates() -> None:
    report = _report(_with_geometry({"type": "MultiPolygon", "coordinates": []}))
    assert "confini_non_validi" in _codes(report)


def test_ring_point_is_an_object() -> None:
    report = _report(
        _with_geometry({"type": "Polygon", "coordinates": [[{"a": 1}] * 4]})
    )
    assert "confini_non_validi" in _codes(report)


def test_huge_integer_coordinate() -> None:
    huge = int("9" * 400)
    ring = [[12.0, 41.0], [huge, 41.0], [13.0, 42.0], [12.0, 41.0]]
    base = json.loads(json.dumps(BOUNDARIES))
    base["features"][0]["geometry"] = {"type": "Polygon", "coordinates": [ring]}
    content = json.dumps(base)
    report = _report(with_fields(boundaries=content.encode()))
    assert "confini_non_validi" in _codes(report)


def test_unclosed_ring() -> None:
    ring = [[12.0, 41.0], [13.0, 41.0], [13.0, 42.0], [12.0, 42.0]]
    report = _report(_with_geometry({"type": "Polygon", "coordinates": [ring]}))
    assert "confini_non_validi" in _codes(report)
    assert "chiuso" in report.errors[0].message


def test_zero_area_ring() -> None:
    ring = [[12.0, 41.0]] * 4
    report = _report(_with_geometry({"type": "Polygon", "coordinates": [ring]}))
    assert "area zero" in report.errors[0].message


def test_no_interior_point_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:

    def no_crossing(_polygon: object, _y: float) -> list[float]:
        return []

    monkeypatch.setattr(parsing, "_horizontal_crossings", no_crossing)
    ring = [[0.0, 0.0], [4.0, 0.0], [4.0, 1.0], [1.0, 1.0], [1.0, 3.0]]
    ring += [[4.0, 3.0], [4.0, 4.0], [0.0, 4.0], [0.0, 0.0]]
    report = _report(_with_geometry({"type": "Polygon", "coordinates": [ring]}))
    assert "punto interno" in report.errors[0].message


# --- 3. huge or odd numbers ---


def test_crimes_with_5000_digit_cell() -> None:
    data_csv = DATA_CSV + f"001,ROB,rapine,2023,{'9' * 5000},1.0,no\n"
    report = _report(with_fields(data=data_csv.encode()))
    assert _codes(report) == ["valore_non_valido"]


@pytest.mark.parametrize("rate", ["1_0", "١٢", "1e5", "9" * 5000, "1.5.2", "+3"])
def test_rate_with_disallowed_forms(rate: str) -> None:
    data_csv = DATA_CSV + f"001,ROB,rapine,2023,1,{rate},no\n"
    report = _report(with_fields(data=data_csv.encode()))
    assert _codes(report) == ["valore_non_valido"]


def test_crimes_with_unicode_digits() -> None:
    data_csv = DATA_CSV + "001,ROB,rapine,2023,١٢,1.0,no\n"
    report = _report(with_fields(data=data_csv.encode()))
    assert _codes(report) == ["valore_non_valido"]


# --- 4. report cap ---


def test_report_with_per_file_cap_and_real_count() -> None:
    rows = 20_000
    osm = OSM_CSV + "amenity=cafe\n" * rows
    report = _report(with_fields(osm_table=osm.encode()))
    assert len(report.errors) <= MAX_PROBLEMS_PER_FILE + 1
    assert report.errors[-1].code == "lettura_interrotta"
    assert report.errors[-1].file == "osm_table"
    assert len(report.errors) == MAX_ROW_ERRORS + 1


def test_per_file_cap_with_different_codes() -> None:
    rows = "".join(f"amenity=x{n},Inesistente{n}\n" for n in range(140))
    report = _report(with_fields(osm_table=(OSM_CSV + rows).encode()))
    assert len(report.errors) <= MAX_PROBLEMS_PER_FILE + 1
    assert report.errors[-1].code == CODE_OTHER_PROBLEMS


def test_the_cap_is_separate_per_file_and_for_warnings() -> None:
    osm = OSM_CSV + "amenity=cafe\n" * 200
    data_csv = DATA_CSV + "001,ROB,rapine,20x4,1,1.0,no\n"
    report = _report(with_fields(osm_table=osm.encode(), data=data_csv.encode()))
    assert any(
        p.file == "data" and p.code == "valore_non_valido" for p in report.errors
    )


# --- 6. CSV header ---


def test_empty_initial_row() -> None:
    report = _report(with_fields(osm_table=b"\n" + OSM_CSV.encode()))
    assert _codes(report) == ["intestazione_mancante"]
    assert report.errors[0].line == 1


def test_giant_header_is_not_an_empty_file() -> None:
    report = _report(with_fields(osm_table=b"x" * 200_000 + b"\n1\n"))
    assert _codes(report) == ["intestazione_non_leggibile"]


def test_unicode_separators_do_not_split_the_header() -> None:
    # \x0c and \x0b are not line endings for csv: they stay inside the cell.
    content = b"osm_tag,cla\x0bsse\namenity=bank,Banca\n"
    report = _report(with_fields(osm_table=content))
    assert _codes(report) == ["colonna_mancante"]


def test_semicolon_inside_a_quoted_field_is_not_the_separator() -> None:
    content = b'"osm_tag;x",classe\namenity=bank,Banca\n'
    report = _report(with_fields(osm_table=content))
    assert "separatore_non_valido" not in _codes(report)


# --- 7. encodings ---


@pytest.mark.parametrize("field_name", ["osm_table", "data", "hazard_table"])
def test_utf16_csv_rejected(field_name: str) -> None:
    text = getattr(valid_files(), field_name).decode("utf-8")
    report = _report(replace(valid_files(), **{field_name: text.encode("utf-16")}))
    assert _codes(report) == ["codifica_non_valida"]
    assert report.errors[0].file == field_name


def test_utf16_ontology_and_boundaries_rejected() -> None:
    files = with_fields(
        ontology=valid_files().ontology.decode().encode("utf-16"),
        boundaries=boundaries_json().decode().encode("utf-16"),
    )
    report = _report(files)
    codes = _codes(report)
    assert "ontologia_illeggibile" in codes
    assert "confini_illeggibili" in codes


# --- second round ---


def _laughs(levels: int) -> str:
    declarations = '<!ENTITY l0 "ha">' + "".join(
        f'<!ENTITY l{n} "{f"&l{n - 1};" * 10}">' for n in range(1, levels + 1)
    )
    return _xml_with_entities(declarations, f"&l{levels};").decode()


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be", "utf-16", "utf-32"])
def test_billion_laughs_in_utf16_without_bom_rejected_immediately(
    encoding: str,
) -> None:
    xml = _laughs(7).encode(encoding)
    start = time.monotonic()
    report = _report(with_fields(ontology=xml, ontology_name="x.owl"))
    assert time.monotonic() - start < 2
    assert _codes(report) == ["codifica_non_ammessa"]


def test_protege_utf8_with_simple_entities_passes() -> None:
    xml = _xml_with_entities('<!ENTITY owl "http://www.w3.org/2002/07/owl#">')
    _, report = check_sources(
        with_fields(ontology=xml, ontology_name="x.owl"), VOCABULARY
    )
    assert "codifica_non_ammessa" not in [p.code for p in report.errors]
    assert "entita_xml_annidata" not in [p.code for p in report.errors]


def test_4mb_csv_of_malformed_rows_stops_immediately() -> None:
    osm = OSM_CSV + "x\n" * 2_000_000
    start = time.monotonic()
    report = _report(with_fields(osm_table=osm.encode()))
    assert time.monotonic() - start < 5
    assert "lettura_interrotta" in _codes(report)
    assert len(report.errors) <= MAX_PROBLEMS_PER_FILE + 1


def test_many_valid_rows_with_semantic_error_stay_fast() -> None:
    osm = OSM_CSV + "".join(f"amenity=a{n},Inesistente\n" for n in range(150_000))
    start = time.monotonic()
    report = _report(with_fields(osm_table=osm.encode()))
    assert time.monotonic() - start < 30
    assert len(report.errors) <= MAX_PROBLEMS_PER_FILE + 1


# --- third round: wide header ---


def test_header_with_millions_of_columns_rejected_immediately() -> None:
    content = b"osm_tag,classe" + b",c" * 2_500_000 + b"\n"
    start = time.monotonic()
    report = _report(with_fields(osm_table=content))
    assert time.monotonic() - start < 2
    assert _codes(report) == ["troppe_colonne"]


def test_header_with_51_columns_rejected_and_with_50_accepted() -> None:
    extra_50 = ",".join(f"x{n}" for n in range(48))
    ok = f"osm_tag,classe,{extra_50}\namenity=bank,Banca" + "," * 48 + "\n"
    _, report = check_sources(
        with_fields(
            osm_table=(ok + "amenity=hospital,Ospedale" + "," * 48 + "\n").encode()
        ),
        VOCABULARY,
    )
    assert "troppe_colonne" not in [p.code for p in report.errors]
    report = _report(with_fields(osm_table=f"osm_tag,classe,{extra_50},y,z\n".encode()))
    assert _codes(report) == ["troppe_colonne"]


def test_duplicate_and_extra_columns_still_reported() -> None:
    osm = "osm_tag,classe,classe,zeta,alfa\namenity=bank,Banca,Banca,1,2\n"
    parsed, report = check_sources(with_fields(osm_table=osm.encode()), VOCABULARY)
    assert parsed is None
    assert _codes(report) == ["colonna_duplicata"]
    (w,) = report.warnings
    assert w.code == "colonna_in_piu"
    assert w.message.index("zeta") < w.message.index("alfa")


# --- fourth round: numeric coordinates and row cap ---


@pytest.mark.parametrize(
    "point", [["1", "1"], ["x", "y"], [True, False], [None, 1], ["1", 2]]
)
def test_non_numeric_coordinates_rejected(point: list[object]) -> None:
    ring = [[12.0, 41.0], [13.0, 41.0], point, [12.0, 41.0]]
    for geometry in (
        {"type": "Polygon", "coordinates": [ring]},
        {"type": "MultiPolygon", "coordinates": [[ring]]},
    ):
        report = _report(_with_geometry(geometry))
        assert _codes(report) == ["confini_non_validi"]
        assert "numeri" in report.errors[0].message


def test_valid_numeric_coordinates_pass() -> None:
    parsed, report = check_sources(valid_files(), VOCABULARY)
    assert report.ok
    assert parsed is not None


def test_row_cap_boundary_n_and_n_plus_one() -> None:
    content = b"osm_tag,classe\n" + b"amenity=a,Banca\n" * 5
    ok = ValidationReport()
    assert (
        len(
            read_csv(
                content,
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
            content,
            "osm_table",
            required=("osm_tag", "classe"),
            report=ko,
            max_rows=4,
        )
        is None
    )
    assert [p.code for p in ko.errors] == ["troppe_righe"]


def test_file_with_200001_rows_rejected_immediately() -> None:
    assert MAX_ROWS == 200_000
    osm = "osm_tag,classe\n" + "".join(
        f"amenity=a{n},Banca\n" for n in range(MAX_ROWS + 1)
    )
    start = time.monotonic()
    report = _report(with_fields(osm_table=osm.encode()))
    assert time.monotonic() - start < 5
    assert _codes(report) == ["troppe_righe"]


def test_csv_with_200000_valid_rows_accepted_by_the_reader() -> None:
    """The generic row cap; the OSM table has its own, tighter one (#498)."""
    rows_csv = "".join(f"a{n},Banca\n" for n in range(MAX_ROWS))
    content = ("osm_tag,classe\n" + rows_csv).encode()
    report = ValidationReport()
    rows = read_csv(content, "osm_table", required=("osm_tag", "classe"), report=report)
    assert report.ok
    assert rows is not None
    assert len(rows) == MAX_ROWS
