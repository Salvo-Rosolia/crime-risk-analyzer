"""Synthetic ISTAT rows for the tests (#345): no dependency on the real data."""

from __future__ import annotations

from crime_risk_analyzer.istat.data import PlaceType
from crime_risk_analyzer.istat.mapping import MatchKind
from crime_risk_analyzer.istat.rows import (
    REASON_BELOW_THRESHOLD,
    REASON_BREAK_2016,
    IstatPoi,
    IstatRow,
    Link,
)


def make_link(
    hazard: str = "Property_theft",
    label: str = "Furto di beni",
    match_kind: MatchKind = "piu_larga",
) -> Link:
    return Link(hazard=hazard, hazard_label_it=label, corrispondenza=match_kind)


def make_row(
    item: str = "THEFT",
    *,
    label: str = "furti",
    place: str = "058091",
    name: str = "Comune di Roma",
    short: str = "Roma",
    kind: PlaceType = "comune",
    offences: int | None = 134169,
    comparison: int | None = 148910,
    rate: float | None = 4876.4,
    below_threshold: bool = False,
    italy: float | None = 1788.7,
    variation: int | None = -10,
    reason: str | None = None,
    rottura_2016: bool = False,
    links: tuple[Link, ...] | None = None,
) -> IstatRow:
    return IstatRow(
        luogo_codice=place,
        luogo_nome=name,
        luogo_breve=short,
        luogo_tipo=kind,
        voce=item,
        voce_label=label,
        anno=2024,
        anno_confronto=2014,
        delitti=offences,
        delitti_confronto=comparison,
        tasso=rate,
        tasso_sotto_soglia=below_threshold,
        tasso_italia=italy,
        variazione_pct=variation,
        motivo_senza_variazione=reason,
        rottura_2016=rottura_2016,
        collegamenti=(make_link(),) if links is None else links,
    )


def make_frame(
    *,
    place: str = "058091",
    name: str = "Comune di Roma",
    short: str = "Roma",
    kind: PlaceType = "comune",
) -> IstatRow:
    return make_row(
        "TOT",
        label="totale",
        place=place,
        name=name,
        short=short,
        kind=kind,
        offences=217536,
        comparison=216750,
        rate=7906.3,
        italy=4069.6,
        # The total includes facts decriminalised in 2016: no variation (#353).
        variation=None,
        reason=REASON_BREAK_2016,
        rottura_2016=True,
        links=(),
    )


def istat_poi(*rows: IstatRow) -> IstatPoi:
    first = rows[0]
    return IstatPoi(
        cornice=make_frame(
            place=first.luogo_codice,
            name=first.luogo_nome,
            short=first.luogo_breve,
            kind=first.luogo_tipo,
        ),
        righe=rows,
    )


BANKROB = make_row(
    "BANKROB",
    label="rapine in banca",
    offences=3,
    comparison=46,
    rate=0.1,
    italy=0.1,
    variation=None,
    reason=REASON_BELOW_THRESHOLD,
    links=(make_link("Bank_robbery", "Rapina in banca", "esatta"),),
)

#: Same item above the threshold of 20 offences (#365 D2): it enters the block.
BANK_ROBBERIES = make_row(
    "BANKROB",
    label="rapine in banca",
    offences=46,
    comparison=120,
    rate=1.7,
    italy=0.5,
    variation=-62,
    links=(make_link("Bank_robbery", "Rapina in banca", "esatta"),),
)
