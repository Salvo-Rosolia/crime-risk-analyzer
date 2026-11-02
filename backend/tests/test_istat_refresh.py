"""Pure functions of scripts/istat_refresh.py (#345): no network."""

from __future__ import annotations

from scripts.istat_refresh import (
    PROVINCE_NUTS,
    SARDINIA_2001,
    check_completeness,
    codelist,
    is_municipality,
    is_province,
    requested_items,
    values_from_csv,
)

_HEADER = "REF_AREA,DATA_TYPE,TYPE_CRIME,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"


def test_values_from_csv_keeps_only_relevant_areas_and_years() -> None:
    text = _HEADER + "\n".join(
        [
            "058091,CRIMEN,THEFT,2024,134169,",
            "058091,CRIMET,THEFT,2024,4876.4,",
            "058091,CRIMEN,THEFT,2014,148910,",
            "058091,CRIMEN,THEFT,2015,1,",  # year not requested
            "ITE4,CRIMEN,THEFT,2024,9,",  # region: dropped
            "ITE43,CRIMEN,THEFT,2024,155538,",
            "ITE43,CRIMET,THEFT,2024,,0",  # rate below threshold
            "IT,CRIMEN,THEFT,2024,1054599,",
            "IT,CRIMET,THEFT,2024,,",  # missing rate without flag
            "IT,CRIMEN,ARSON,2024,5,",  # item not requested
        ]
    )
    values = values_from_csv(text, years=(2024, 2014), items=["THEFT"])
    assert set(values) == {"058091", "ITE43", "IT"}
    assert values["058091"]["THEFT"]["2024"] == {
        "delitti": 134169,
        "tasso": 4876.4,
        "tasso_sotto_soglia": False,
    }
    assert values["058091"]["THEFT"]["2014"] == {
        "delitti": 148910,
        "tasso": None,
        "tasso_sotto_soglia": False,
    }
    assert values["ITE43"]["THEFT"]["2024"] == {
        "delitti": 155538,
        "tasso": None,
        "tasso_sotto_soglia": True,
    }
    assert values["ITE43"]["THEFT"]["2014"] is None
    italy = values["IT"]["THEFT"]["2024"]
    assert italy is not None and italy["tasso_sotto_soglia"] is False


def test_check_completeness_reports_missing_territories_and_years() -> None:
    problems = check_completeness({"058091": {"THEFT": {"2024": None}}}, ["THEFT"])
    assert "expected 106 provinces, found 0" in problems
    assert "expected 108 capital municipalities, found 1" in problems
    assert "the Italy row is missing" in problems
    assert "058091/THEFT: the 2024 datum is missing" in problems


def test_codelist_reads_the_italian_names() -> None:
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


def test_territorial_codes() -> None:
    assert is_province("ITE43") and is_province("IT108")
    assert not is_province("ITE4") and not is_province("IT")
    assert is_municipality("058091") and not is_municipality("58091")


def test_province_table_covers_the_106_of_the_dataset() -> None:
    assert len(PROVINCE_NUTS) == 102
    assert set(SARDINIA_2001.values()) == {"ITG25", "ITG26", "ITG27", "ITG28"}
    assert not set(PROVINCE_NUTS.values()) & set(SARDINIA_2001.values())
    assert len(set(PROVINCE_NUTS.values()) | set(SARDINIA_2001.values())) == 106
    assert PROVINCE_NUTS[58] == "ITE43" and PROVINCE_NUTS[108] == "IT108"
    assert PROVINCE_NUTS[19] == "ITC4A" and PROVINCE_NUTS[53] == "ITE1A"


def test_requested_items_are_the_mapped_ones_plus_the_total() -> None:
    items = requested_items()
    assert "TOT" in items and "THEFT" in items and "DAMAGE" in items
    assert len(items) == 19
