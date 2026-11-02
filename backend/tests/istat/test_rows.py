"""ISTAT rows (#345, spec 4.4): variation, format, real data, rows of a POI."""

from __future__ import annotations

import re

import pytest

from crime_risk_analyzer.istat import rows as rows_mod
from crime_risk_analyzer.istat.data import istat_data
from crime_risk_analyzer.istat.places import place_of
from crime_risk_analyzer.istat.rows import (
    REASON_BELOW_THRESHOLD,
    REASON_BREAK_2016,
    REASON_MISSING_YEAR,
    IstatRow,
    ItalyComparison,
    compare_to_italy,
    format_row,
    istat_for_poi,
    istat_row,
    variation,
)
from tests.istat._factories import make_frame, make_link, make_row


@pytest.mark.parametrize(
    ("current", "past", "break_", "expected"),
    [
        (134169, 148910, False, (-10, None)),
        (812, 701, False, (16, None)),
        (20, 20, False, (0, None)),
        (1005, 1000, False, (1, None)),  # +0.5% -> 1: half rounds away from zero
        (995, 1000, False, (-1, None)),
        (19, 100, False, (None, REASON_BELOW_THRESHOLD)),
        (100, 19, False, (None, REASON_BELOW_THRESHOLD)),
        (None, 100, False, (None, REASON_MISSING_YEAR)),
        (100, None, False, (None, REASON_MISSING_YEAR)),
        (19843, 16417, True, (None, REASON_BREAK_2016)),
    ],
)
def test_variation_on_the_counts(
    current: int | None,
    past: int | None,
    break_: bool,
    expected: tuple[int | None, str | None],
) -> None:
    assert variation(current, past, break_2016=break_) == expected


def test_format_of_an_item_row() -> None:
    """#365 D7: in words, no figures, codes, square brackets, involved POIs."""
    assert format_row(make_row()) == (
        "- Comune di Roma, 2024: furti: tasso più alto di quello italiano; in calo "
        "dal 2014. Collegata a: Furto di beni (voce più ampia del rischio)."
    )


def test_frame_format() -> None:
    assert format_row(make_frame()) == (
        "- Comune di Roma, 2024: totale dei delitti denunciati: tasso più alto di "
        "quello italiano; contesto generale, non legato a un rischio."
    )


@pytest.mark.parametrize(
    ("variazione_pct", "reason", "expected"),
    [
        (-10, None, "; in calo dal 2014."),
        (16, None, "; in crescita dal 2014."),
        (0, None, "; stabile dal 2014."),
        (
            None,
            REASON_BELOW_THRESHOLD,
            f"; tendenza non calcolata: {REASON_BELOW_THRESHOLD}.",
        ),
        (None, None, "; tendenza non calcolata."),
    ],
)
def test_trend_in_words(
    variazione_pct: int | None, reason: str | None, expected: str
) -> None:
    assert expected in format_row(make_row(variation=variazione_pct, reason=reason))


@pytest.mark.parametrize(
    "r",
    [
        make_row(),
        make_row(variation=16),
        make_row(
            rate=None, below_threshold=True, variation=None, reason=REASON_MISSING_YEAR
        ),
        make_frame(),
    ],
)
def test_no_figure_nor_code_in_the_row(r: IstatRow) -> None:
    """The model cannot report figures it does not see (D7): only the years remain
    (and the legal reference in the reason of the broken series)."""
    text = format_row(r).replace("d.lgs. 7/2016", "")
    assert set(re.findall(r"\d+", text)) <= {"2014", "2016", "2024"}
    assert r.voce not in text and "[" not in text and "%" not in text
    assert "POI coinvolti" not in text


def test_links_grouped_by_match_kind() -> None:
    r = make_row(
        links=(
            make_link("Vehicle_Theft", "Furto di veicolo", "piu_stretta"),
            make_link("Property_theft", "Furto di beni", "piu_larga"),
            make_link("ATM_removal", "Asportazione del bancomat", "piu_larga"),
            make_link("Purse_snatching", "Scippo", "esatta"),
        )
    )
    expected = (
        "Collegata a: Scippo (corrispondenza esatta); Asportazione del "
        "bancomat, Furto di beni (voce più ampia del rischio); Furto di veicolo "
        "(voce che copre solo una parte del rischio)."
    )
    assert expected in format_row(r)


def test_format_without_comparison() -> None:
    assert "confronto con il tasso italiano non disponibile" in format_row(
        make_row(rate=None, italy=None)
    )


def test_real_row_thefts_comune_di_roma() -> None:
    """ISTAT values extracted on 2026-10-06: a data update may change them."""
    data = istat_data()
    roma = place_of(41.8902, 12.4922, data=data)
    assert roma is not None
    r = istat_row(data, roma, "THEFT", links=(make_link(),))
    values = (r.delitti, r.delitti_confronto, r.tasso, r.tasso_italia, r.variazione_pct)
    assert values == (
        134169,
        148910,
        4876.4,
        1788.7,
        -10,
    )
    assert format_row(r) == format_row(make_row())


def test_real_row_rate_below_threshold_and_break() -> None:
    data = istat_data()
    rho = place_of(45.5306, 9.0402, data=data)  # Rho, Provincia di Milano
    assert rho is not None and rho.codice == "ITC45"
    fires = istat_row(data, rho, "FOREARS")
    assert fires.tasso is None and fires.tasso_sotto_soglia
    assert fires.motivo_senza_variazione == REASON_BELOW_THRESHOLD
    roma = place_of(41.8902, 12.4922, data=data)
    assert roma is not None
    damages = istat_row(data, roma, "DAMAGE")
    assert damages.rottura_2016 and damages.variazione_pct is None
    assert damages.motivo_senza_variazione == REASON_BREAK_2016


def test_rows_of_a_poi_group_the_hazards_by_item() -> None:
    istat = istat_for_poi(
        41.8902, 12.4922, ["Bank_robbery", "Property_theft", "ATM_removal", "Landslide"]
    )
    assert istat is not None
    assert [r.voce for r in istat.righe] == ["BANKROB", "THEFT"]
    thefts = istat.righe[1]
    assert {c.hazard for c in thefts.collegamenti} == {"Property_theft", "ATM_removal"}
    assert {c.hazard_label_it for c in thefts.collegamenti} == {
        "Furto di beni",
        "Asportazione del bancomat",
    }
    assert (istat.cornice.voce, istat.cornice.luogo_codice) == ("TOT", "058091")
    assert istat.cornice.collegamenti == ()


def test_no_row_outside_the_polygons_or_without_items() -> None:
    assert istat_for_poi(41.0, 12.0, ["Bank_robbery"]) is None  # sea
    assert istat_for_poi(41.8902, 12.4922, ["Landslide", "Crime_explosion"]) is None
    assert istat_for_poi(41.8902, 12.4922, []) is None


def test_no_row_without_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rows_mod, "istat_data_or_none", lambda: None)
    assert istat_for_poi(41.8902, 12.4922, ["Bank_robbery"]) is None


def test_the_frame_does_not_compute_the_variation_for_the_2016_break() -> None:
    """The total includes facts decriminalised by d.lgs. 7/2016 (insults,
    simple damage, ...): as for damage the ten-year variation is not
    computed and the row says why (#353). The rule comes from the
    catalog, not from a separate list."""
    data = istat_data()
    milano = place_of(45.4642, 9.19, data=data)
    assert milano is not None
    total = istat_row(data, milano, "TOT")
    # The case is not vacuous: without the break the variation would be computable.
    assert variation(total.delitti, total.delitti_confronto, break_2016=False) == (
        -13,
        None,
    )
    assert total.rottura_2016
    assert total.variazione_pct is None
    assert total.motivo_senza_variazione == REASON_BREAK_2016

    istat = istat_for_poi(45.4642, 9.19, ["Property_theft"])
    assert istat is not None
    assert istat.cornice.variazione_pct is None
    assert istat.cornice.motivo_senza_variazione == REASON_BREAK_2016


@pytest.mark.parametrize(
    ("rate", "below_threshold", "italy", "italy_below_threshold", "expected"),
    [
        (110.0, False, 100.0, False, "piu_alto"),  # edge 1.10 included
        (109.9, False, 100.0, False, "simile"),
        (3.3, False, 3.0, False, "piu_alto"),  # 1.1 exact even though not in float
        (90.0, False, 100.0, False, "piu_basso"),  # edge 0.90 included
        (90.1, False, 100.0, False, "simile"),
        (100.0, False, 100.0, False, "simile"),
        (None, False, 100.0, False, None),  # missing rate
        (100.0, False, None, False, None),  # missing national
        (100.0, False, 0.0, False, None),  # national 0
        (None, True, 100.0, False, "piu_basso"),  # "meno di 0,1" counts as 0
        (100.0, False, None, True, None),  # national "meno di 0,1" counts as 0
        (None, True, None, True, None),
    ],
)
def test_comparison_with_the_italian_rate(
    rate: float | None,
    below_threshold: bool,
    italy: float | None,
    italy_below_threshold: bool,
    expected: ItalyComparison | None,
) -> None:
    """#365 D2: a single classification, reused by the block and by the check."""
    r = make_row(rate=rate, below_threshold=below_threshold, italy=italy).model_copy(
        update={"tasso_italia_sotto_soglia": italy_below_threshold}
    )
    assert compare_to_italy(r) == expected


@pytest.mark.parametrize(
    ("rate", "italy", "sentence"),
    [
        (4876.4, 1788.7, ": tasso più alto di quello italiano;"),
        (100.0, 200.0, ": tasso più basso di quello italiano;"),
        (100.0, 105.0, ": tasso simile a quello italiano;"),
    ],
)
def test_the_item_row_carries_the_comparison(
    rate: float, italy: float, sentence: str
) -> None:
    assert sentence in format_row(make_row(rate=rate, italy=italy))


def test_the_total_has_the_comparison_too() -> None:
    """D7: the total row states the comparison, so the check verifies it."""
    assert compare_to_italy(make_frame()) == "piu_alto"
