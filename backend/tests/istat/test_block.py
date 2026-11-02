"""ISTAT DATA block (#345, spec 4.4-4.5): dedupe, order, cut, frames."""

from __future__ import annotations

from typing import Any

from crime_risk_analyzer.istat.block import (
    ISTAT_DATA_HEADER,
    IstatBlock,
    has_istat_rows,
    istat_block_for_poi,
    istat_block_for_zone,
    truncation_note,
)
from crime_risk_analyzer.istat.rows import IstatPoi
from tests.istat._factories import (
    BANK_ROBBERIES,
    BANKROB,
    istat_poi,
    make_link,
    make_row,
)


def _poi(poi_id: str, istat: IstatPoi | None) -> dict[str, Any]:
    p: dict[str, Any] = {"poi_id": poi_id, "poi": poi_id}
    if istat is not None:
        p["istat"] = istat
    return p


_A = _poi("node/1", istat_poi(make_row(links=(make_link(),))))
_B = _poi(
    "node/2",
    istat_poi(
        make_row(links=(make_link("ATM_removal", "Asportazione del bancomat"),)),
        BANK_ROBBERIES,
    ),
)


def test_zone_one_row_per_place_and_item_sorted_by_involved_pois() -> None:
    """Thefts (2 POIs) before bank robberies (1 POI), even though BANKROB comes
    first alphabetically; the number does not appear in the text (#365 D7)."""
    block = istat_block_for_zone([_A, _B], estimate_tokens=len, token_limit=None)
    rows = block.testo.split("\n")
    assert rows[0] == ISTAT_DATA_HEADER
    assert "totale dei delitti denunciati" in rows[1]
    assert rows[2].startswith("- Comune di Roma, 2024: furti: ")
    assert rows[2].endswith(
        "Collegata a: Asportazione del bancomat, Furto di beni (voce più ampia del "
        "rischio)."
    )
    assert rows[3].startswith("- Comune di Roma, 2024: rapine in banca: ")
    assert "POI coinvolti" not in block.testo
    assert len(rows) == 4
    assert [r.voce for r in block.righe] == ["TOT", "THEFT", "BANKROB"]
    assert block.voci_tagliate == 0


def test_zone_with_two_places_states_the_place_of_each_row() -> None:
    province = _poi(
        "node/3",
        istat_poi(make_row(place="ITE43", name="Provincia di Roma", kind="provincia")),
    )
    block = istat_block_for_zone([_A, province], estimate_tokens=len, token_limit=None)
    rows = block.testo.split("\n")
    assert rows[1].startswith("- Comune di Roma, 2024: totale")
    assert rows[2].startswith("- Provincia di Roma, 2024: totale")
    assert rows[3].startswith("- Comune di Roma, 2024: furti")
    assert rows[4].startswith("- Provincia di Roma, 2024: furti")


def test_pois_without_istat_do_not_count() -> None:
    block = istat_block_for_zone(
        [_poi("node/9", None), _A], estimate_tokens=len, token_limit=None
    )
    assert block == istat_block_for_zone([_A], estimate_tokens=len, token_limit=None)
    assert istat_block_for_zone(
        [_poi("node/9", None)], estimate_tokens=len, token_limit=None
    ) == (IstatBlock())


def test_cut_removes_first_the_items_with_fewer_pois_and_declares_it() -> None:
    full = istat_block_for_zone([_A, _B], estimate_tokens=len, token_limit=None)
    limit = len(full.testo) - 1
    truncated = istat_block_for_zone([_A, _B], estimate_tokens=len, token_limit=limit)
    assert "rapine in banca" not in truncated.testo and "furti" in truncated.testo
    assert truncated.voci_tagliate == 1
    assert truncated.testo.endswith(truncation_note(1))
    assert len(truncated.testo) <= limit
    assert [r.voce for r in truncated.righe] == ["TOT", "THEFT"]


def test_frames_last_empty_block_if_nothing_fits() -> None:
    assert istat_block_for_zone(
        [_A, _B], estimate_tokens=len, token_limit=10
    ) == IstatBlock(voci_tagliate=2)


def test_truncation_note() -> None:
    assert (
        truncation_note(1)
        == "NB: per limiti di lunghezza 1 voce ISTAT non e' riportata."
    )
    assert (
        truncation_note(3)
        == "NB: per limiti di lunghezza 3 voci ISTAT non sono riportate."
    )


def test_poi_block_without_involved_pois() -> None:
    block = istat_block_for_poi(istat_poi(make_row(), BANK_ROBBERIES))
    rows = block.testo.split("\n")
    assert rows[0] == ISTAT_DATA_HEADER
    assert "totale dei delitti denunciati" in rows[1]
    assert len(rows) == 4
    assert "POI coinvolti" not in block.testo
    assert istat_block_for_poi(None) == IstatBlock()


def test_has_istat_rows() -> None:
    assert has_istat_rows([_poi("node/9", None), _A])
    assert not has_istat_rows([_poi("node/9", None), {"poi_id": "x", "istat": None}])


def test_items_under_20_offences_stay_out_of_the_block() -> None:
    """#365 D2: 3 bank robberies or a missing count do not enter the narrative
    (same threshold as the Detail); the frame stays, with the items that stay."""
    without_count = make_row("SHOPROB", label="rapine in negozio", offences=None)
    twenty = make_row("SNATCH", label="scippi", offences=20)
    zone = istat_block_for_zone(
        [_poi("node/1", istat_poi(make_row(), BANKROB, without_count, twenty))],
        estimate_tokens=len,
        token_limit=None,
    )
    poi = istat_block_for_poi(istat_poi(make_row(), BANKROB, without_count, twenty))
    for block in (zone, poi):
        assert {r.voce for r in block.righe} == {"TOT", "THEFT", "SNATCH"}
        assert "rapine in banca" not in block.testo
        assert "rapine in negozio" not in block.testo
    assert zone.voci_tagliate == 0  # excluded by threshold, not cut by budget


def test_only_items_below_threshold_no_block() -> None:
    assert istat_block_for_poi(istat_poi(BANKROB)) == IstatBlock()
    assert (
        istat_block_for_zone(
            [_poi("node/1", istat_poi(BANKROB))], estimate_tokens=len, token_limit=None
        )
        == IstatBlock()
    )
