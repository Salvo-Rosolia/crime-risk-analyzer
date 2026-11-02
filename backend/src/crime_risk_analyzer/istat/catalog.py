"""Catalog of the 56 items of the ISTAT 73_67 dataset (#353).

Source: codelist CL_REATI_PS v1.0 (dimension TYPE_CRIME) of the IT1/73_67 dataflow,
codes actually available in the dataset, downloaded via SDMX on 2026-10-08.
For each item: ``codice``, ``etichetta`` (Italian, from the codelist), ``madre``
(Parent field of the codelist, ``None`` for the roots), ``legata_al_luogo`` and
``rottura_2016``.

The USE of an item is not written here: :func:`hazards_by_item` derives it from
:data:`~crime_risk_analyzer.istat.mapping.HAZARD_MAPPING`, so catalog and mapping
cannot diverge. An item is *used* if at least one hazard references it; the others
carry a ``stato``:

- ``usabile``: a compatible TERMINUS risk exists, but the mapping (D3: one item
  per risk, no sums) chose another item;
- ``esclusa``: no compatible TERMINUS risk; ``motivo`` says why;
- ``cornice``: the total, which only enters as the frame of the place (D10).

``legata_al_luogo``: sub-item of thefts or robberies that indicates the place of
the fact (dwelling, shop, parked car, bank, post office, public road). The
sub-items that indicate the stolen object (cars, mopeds, motorcycles, heavy
vehicles with goods, works of art) or the modality (snatching, sleight of hand)
are not. The place sub-items match the place categories of the police forces' SDI
(Ministry of the Interior, *Rapporto intersettoriale sulla criminalita' predatoria
2024*): they count the facts at the institution or place, not at the customers, and
keep pharmacies, public premises and fuel stations separate from shops. ISTAT does
not publish a formal definition of the sub-items: these readings are by clues
(comparison of totals and SDI categories).

Uses not made, to be declared: «Furto di merci» in a shopping centre and jeweller's
would find in ``SHOPTHEF`` an item more precise than thefts in general, but the
``Theft_of_goods`` risk is a single one for all classes and the mapping does not go
down by POI class (spec #353 §3): it stays on ``THEFT``.

``rottura_2016``: the item includes facts decriminalised by d.lgs. 7/2016 (simple
damage, insult, forgery of private documents, appropriation of lost things and
others): the ten-year variation is not comparable and is not computed, neither for
the risk items nor for the frame of the total. :data:`BREAK_ITEMS_2016` derives the
set from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from crime_risk_analyzer.istat.mapping import HAZARD_MAPPING

__all__ = [
    "BREAK_ITEMS_2016",
    "CATALOG",
    "Item",
    "Status",
    "hazards_by_item",
    "is_used",
]

#: Status of an item that no hazard uses (see the module docstring).
Status = Literal["usabile", "esclusa", "cornice"]


@dataclass(frozen=True)
class Item:
    """An item of the 73_67 dataset; ``stato``/``motivo`` only if not used."""

    codice: str
    etichetta: str
    madre: str | None = None
    legata_al_luogo: bool = False
    rottura_2016: bool = False
    stato: Status | None = None
    motivo: str = ""


# --- Recurring reasons ---

_OUTSIDE_ONTOLOGY = (
    "Fuori dall'ontologia TERMINUS, che descrive rischi per luoghi e "
    "infrastrutture; coerente con i vincoli del progetto (niente profilazione)."
)
_PERSON = (
    "Reato contro la persona: nessun rischio TERMINUS corrispondente. "
    + _OUTSIDE_ONTOLOGY
)
_HOMICIDE = (
    "Omicidio: e' un esito sulla persona, non un rischio per un luogo. "
    + _OUTSIDE_ONTOLOGY
)
_SEXUAL = (
    "Reato sessuale o sui minori: nessun rischio TERMINUS corrispondente "
    "(Child_abuse riguarda i maltrattamenti, non pubblicati in 73_67). "
    + _OUTSIDE_ONTOLOGY
)
_ECONOMIC = (
    "Reato economico-finanziario senza luogo fisico: nessun rischio TERMINUS "
    "corrispondente. " + _OUTSIDE_ONTOLOGY
)
_ORGANISED = (
    "Reato associativo o di traffico: nessun rischio TERMINUS corrispondente. "
    + _OUTSIDE_ONTOLOGY
)
_VEHICLES = (
    "Usabile in principio per Vehicle_Theft, che pero' usa gia' i furti di "
    "autovetture (corrispondenza piu' stretta): D3 non somma voci, quindi una "
    "seconda voce per lo stesso rischio non entra."
)
_NO_DWELLINGS = (
    "nessuna classe OSM del progetto corrisponde a un'abitazione e nessun "
    "rischio TERMINUS riguarda le abitazioni."
)

_ITEMS: tuple[Item, ...] = (
    # --- Homicides ---
    Item(
        "MASSMURD",
        "strage",
        stato="esclusa",
        motivo=(
            "La strage e' un esito (piu' morti), non un tipo di rischio: gli "
            "attentati dell'ontologia usano gia' la voce «attentati». "
            + _OUTSIDE_ONTOLOGY
        ),
    ),
    Item("INTENHOM", "omicidi volontari consumati", stato="esclusa", motivo=_HOMICIDE),
    Item(
        "ROBBHOM",
        "omicidi volontari consumati a scopo di furto o rapina",
        madre="INTENHOM",
        stato="esclusa",
        motivo=_HOMICIDE,
    ),
    Item(
        "MAFIAHOM",
        "omicidi volontari consumati di tipo mafioso",
        madre="INTENHOM",
        stato="esclusa",
        motivo=_HOMICIDE,
    ),
    Item(
        "TERRORHOM",
        "omicidi volontari consumati a scopo terroristico",
        madre="INTENHOM",
        stato="esclusa",
        motivo=(
            "Conta le vittime, non i fatti: gli attacchi terroristici "
            "dell'ontologia usano gia' la voce «attentati». " + _OUTSIDE_ONTOLOGY
        ),
    ),
    Item("ATTEMPHOM", "tentati omicidi", stato="esclusa", motivo=_HOMICIDE),
    Item("INFANTHOM", "infanticidi", stato="esclusa", motivo=_HOMICIDE),
    Item("MANSHOM", "omicidi preterintenzionali", stato="esclusa", motivo=_HOMICIDE),
    Item(
        "UNINTHOM",
        "omicidi colposi",
        stato="esclusa",
        motivo=(
            "Reato colposo contro la persona (incidenti stradali, sul lavoro): "
            "nessun rischio TERMINUS corrispondente. " + _OUTSIDE_ONTOLOGY
        ),
    ),
    Item(
        "ROADHOM",
        "omicidi colposi da incidente stradale",
        madre="UNINTHOM",
        stato="esclusa",
        motivo=(
            "Incidente stradale: nessun rischio TERMINUS di incidente. "
            + _OUTSIDE_ONTOLOGY
        ),
    ),
    # --- Other crimes against the person ---
    Item("BLOWS", "percosse", stato="esclusa", motivo=_PERSON),
    Item("CULPINJU", "lesioni dolose"),
    Item("MENACE", "minacce", stato="esclusa", motivo=_PERSON),
    Item("KIDNAPP", "sequestri di persona"),
    Item(
        "OFFENCE",
        "ingiurie",
        rottura_2016=True,
        stato="esclusa",
        motivo=_PERSON + " Depenalizzata dal d.lgs. 7/2016.",
    ),
    # --- Sexual crimes and crimes against minors ---
    Item("RAPE", "violenze sessuali", stato="esclusa", motivo=_SEXUAL),
    Item("RAPEUN18", "atti sessuali con minorenne", stato="esclusa", motivo=_SEXUAL),
    Item("CORRUPUN18", "corruzione di minorenne", stato="esclusa", motivo=_SEXUAL),
    Item(
        "PROSTI",
        "sfruttamento e favoreggiamento della prostituzione",
        stato="esclusa",
        motivo=_SEXUAL,
    ),
    Item(
        "PORNO",
        "pornografia minorile e detenzione di materiale pedopornografico",
        stato="esclusa",
        motivo=_SEXUAL,
    ),
    # --- Thefts ---
    Item("THEFT", "furti"),
    Item("BAGTHEF", "furti con strappo", madre="THEFT"),
    Item(
        "PICKTHEF",
        "furti con destrezza",
        madre="THEFT",
        stato="esclusa",
        motivo=(
            "Nessun rischio TERMINUS di borseggio: i furti dell'ontologia sono ai "
            "danni di luoghi e infrastrutture, e lo scippo ha la sua voce (furti "
            "con strappo)."
        ),
    ),
    Item(
        "BURGTHEF",
        "furti in abitazioni",
        madre="THEFT",
        legata_al_luogo=True,
        stato="esclusa",
        motivo=(
            "Conta i furti nelle abitazioni (categoria di luogo SDI): " + _NO_DWELLINGS
        ),
    ),
    Item(
        "SHOPTHEF",
        "furti in esercizi commerciali",
        madre="THEFT",
        legata_al_luogo=True,
    ),
    Item(
        "VEHITHEF",
        "furti in auto in sosta",
        madre="THEFT",
        legata_al_luogo=True,
        stato="esclusa",
        motivo=(
            "Conta i furti dentro le auto in sosta (categoria di luogo SDI): "
            "nessuna classe OSM del progetto corrisponde a un parcheggio, e "
            "Vehicle_Theft e' il furto del veicolo, non dal veicolo."
        ),
    ),
    Item("ARTTHEF", "furti di opere d'arte e materiale archeologico", madre="THEFT"),
    Item(
        "TRUCKTHEF",
        "furti di automezzi pesanti trasportanti merci",
        madre="THEFT",
        stato="esclusa",
        motivo=(
            "Nessun rischio TERMINUS di furto di mezzi pesanti con il carico: i "
            "furti di merci dell'ontologia avvengono in magazzini, depositi e "
            "negozi."
        ),
    ),
    Item(
        "MOPETHEF",
        "furti di ciclomotori",
        madre="THEFT",
        stato="usabile",
        motivo=_VEHICLES,
    ),
    Item(
        "MOTORTHEF",
        "furti di motocicli",
        madre="THEFT",
        stato="usabile",
        motivo=_VEHICLES,
    ),
    Item("CARTHEF", "furti di autovetture", madre="THEFT"),
    # --- Robberies ---
    Item("ROBBER", "rapine"),
    Item(
        "HOUSEROB",
        "rapine in abitazione",
        madre="ROBBER",
        legata_al_luogo=True,
        stato="esclusa",
        motivo=(
            "Conta le rapine nelle abitazioni (categoria di luogo SDI): "
            + _NO_DWELLINGS
        ),
    ),
    Item("BANKROB", "rapine in banca", madre="ROBBER", legata_al_luogo=True),
    Item("POSTROB", "rapine in uffici postali", madre="ROBBER", legata_al_luogo=True),
    Item(
        "SHOPROB",
        "rapine in esercizi commerciali",
        madre="ROBBER",
        legata_al_luogo=True,
    ),
    Item("STREETROB", "rapine in pubblica via", madre="ROBBER", legata_al_luogo=True),
    # --- Economic, computer and intellectual property crimes ---
    Item(
        "EXTORT",
        "estorsioni",
        stato="esclusa",
        motivo=(
            "Nessun rischio TERMINUS di racket o estorsione ai danni di un "
            "luogo. " + _OUTSIDE_ONTOLOGY
        ),
    ),
    # SWINCYB and COUNTER: no partial match (decision #353, spec §7).
    Item(
        "SWINCYB",
        "truffe e frodi informatiche",
        stato="esclusa",
        motivo=(
            "Il rischio TERMINUS piu' vicino (biglietti contraffatti di "
            "spettatori e viaggiatori) e' un rischio di accesso e "
            "sovraffollamento, non una frode: sovrapposizione minima e non "
            "stimabile."
        ),
    ),
    Item("CYBERCRIM", "delitti informatici"),
    Item(
        "COUNTER",
        "contraffazione di marchi e prodotti industriali",
        stato="esclusa",
        motivo=(
            "Il rischio TERMINUS piu' vicino (contraffazione di generi "
            "alimentari) e' un rischio sanitario, non di marchi: sovrapposizione "
            "minima e non stimabile."
        ),
    ),
    Item(
        "INTPROP",
        "violazione della proprietà intellettuale",
        stato="esclusa",
        motivo=_ECONOMIC,
    ),
    Item("RECEIV", "ricettazione", stato="esclusa", motivo=_ECONOMIC),
    Item(
        "MONEYLAU",
        "riciclaggio e impiego di denaro, beni o utilità di provenienza illecita",
        stato="esclusa",
        motivo=_ECONOMIC,
    ),
    Item("USURY", "usura", stato="esclusa", motivo=_ECONOMIC),
    # --- Damage and fires ---
    Item("DAMAGE", "danneggiamenti", rottura_2016=True),
    Item("ARSON", "incendi"),
    Item("FOREARS", "incendi boschivi", madre="ARSON"),
    Item("DAMARS", "danneggiamento seguito da incendio"),
    # --- Drugs, attacks, organised crime ---
    Item(
        "DRUG",
        "normativa sugli stupefacenti",
        stato="esclusa",
        motivo=(
            "Spaccio e detenzione non sono rischi TERMINUS (il furto di farmaci "
            "usa i furti). " + _OUTSIDE_ONTOLOGY
        ),
    ),
    Item("ATTACK", "attentati"),
    Item("CRIMASS", "associazione per delinquere", stato="esclusa", motivo=_ORGANISED),
    Item("MAFIASS", "associazione di tipo mafioso", stato="esclusa", motivo=_ORGANISED),
    Item("SMUGGL", "contrabbando", stato="esclusa", motivo=_ORGANISED),
    # --- Residual and total ---
    Item(
        "OTHCRIM",
        "altri delitti",
        # By clues: residual item that includes crimes decriminalised in 2016
        # (forgery of private documents, appropriation of lost things).
        rottura_2016=True,
        stato="esclusa",
        motivo=(
            "Voce residua eterogenea senza contenuto definito: nessun rischio "
            "TERMINUS le corrisponde."
        ),
    ),
    Item(
        "TOT",
        "totale",
        # Certain: the total includes damage (DAMAGE) and insults.
        rottura_2016=True,
        stato="cornice",
        motivo=(
            "Totale dei delitti: entra solo come cornice del luogo, mai "
            "collegato a un rischio (D10)."
        ),
    ),
)

#: code -> item, in the order of the codelist.
CATALOG: dict[str, Item] = {item.codice: item for item in _ITEMS}


def hazards_by_item() -> dict[str, tuple[str, ...]]:
    """ISTAT item -> hazards that use it, derived from ``HAZARD_MAPPING``."""
    by_item: dict[str, list[str]] = {}
    for hazard, mapping in HAZARD_MAPPING.items():
        if mapping.voce_istat:
            by_item.setdefault(mapping.voce_istat, []).append(hazard)
    return {item: tuple(hazards) for item, hazards in by_item.items()}


def is_used(code: str) -> bool:
    """``True`` if at least one hazard of the mapping uses the item ``code``."""
    return code in hazards_by_item()


#: Items without ten-year variation (series broken by d.lgs. 7/2016), from the
#: ``rottura_2016`` field of the catalog. It applies to the risk rows (damage) and
#: to the frame of the total, which also includes decriminalised facts (#353): a
#: single rule, no exception for the frame.
BREAK_ITEMS_2016: frozenset[str] = frozenset(
    code for code, item in CATALOG.items() if item.rottura_2016
)
