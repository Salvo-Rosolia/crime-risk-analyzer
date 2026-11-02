"""Table of TERMINUS hazards -> ISTAT item (#345, spec 4.2 / D3).

One row for each of the 155 hazards of the ontology. ``voce_istat`` is the code of
the item of the ISTAT 73_67 dataset (``None`` = no adequate item, even when the
overlap is only partial); ``corrispondenza`` says how the item relates to the risk:

- ``esatta``: the item is the same crime;
- ``piu_larga``: the item includes the risk and more (e.g. "furti" for "furto di
  rame");
- ``piu_stretta``: the item covers only a part of the risk.

``rottura_2016``: the item is touched by the decriminalisation of d.lgs. 7/2016, so
the ten-year variation is not computed. It repeats the field of the item in the
catalog (:mod:`~crime_risk_analyzer.istat.catalog`, #353), which is the source of
``BREAK_ITEMS_2016``; a test forces the two to coincide. No sum of items.

Transcribed from the reviewed draft (sheet "Mappatura"), in the style of
``sparql_module/osm_mapping.py``. The counts fixed in
``tests/istat/test_mapping.py`` (mapped rows, matches, distinct items) are not
enough: moving a hazard between two items with the same match leaves them
unchanged. That is why the same file also fixes the hazards per item, which
catches the move; only the swap of two hazards between two items stays invisible
to the counts, covered where needed by targeted tests. **To be verified by the
user before the merge (D3).**
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["HAZARD_MAPPING", "HazardMapping", "MatchKind"]

#: Relation between the ISTAT item and the risk (D3).
MatchKind = Literal["esatta", "piu_larga", "piu_stretta"]


@dataclass(frozen=True)
class HazardMapping:
    """Link of a hazard to an ISTAT item (or its absence)."""

    voce_istat: str | None
    corrispondenza: MatchKind | None
    rottura_2016: bool
    nota: str


#: TERMINUS hazard (real identifier) -> link to the ISTAT item.
HAZARD_MAPPING: dict[str, HazardMapping] = {
    "Theft_of_ancient_artifacts": HazardMapping(
        voce_istat="ARTTHEF",
        corrispondenza="esatta",
        rottura_2016=False,
        nota="La voce ISTAT comprende il materiale archeologico.",
    ),
    "Theft_of_works_of_art": HazardMapping(
        voce_istat="ARTTHEF",
        corrispondenza="esatta",
        rottura_2016=False,
        nota="",
    ),
    "Purse_snatching": HazardMapping(
        voce_istat="BAGTHEF",
        corrispondenza="esatta",
        rottura_2016=False,
        nota="",
    ),
    "Bank_robbery": HazardMapping(
        voce_istat="BANKROB",
        corrispondenza="esatta",
        rottura_2016=False,
        nota="",
    ),
    "Cyber_attack": HazardMapping(
        voce_istat="CYBERCRIM",
        corrispondenza="esatta",
        rottura_2016=False,
        nota="",
    ),
    "Post_office_robbery": HazardMapping(
        voce_istat="POSTROB",
        corrispondenza="esatta",
        rottura_2016=False,
        nota="",
    ),
    "Store_robbery": HazardMapping(
        voce_istat="SHOPROB",
        corrispondenza="esatta",
        rottura_2016=False,
        nota="",
    ),
    "Mugging": HazardMapping(
        voce_istat="STREETROB",
        corrispondenza="esatta",
        rottura_2016=False,
        nota="Aggressione a scopo di furto in strada = rapina in pubblica via.",
    ),
    "Vehicle_Theft": HazardMapping(
        voce_istat="CARTHEF",
        corrispondenza="piu_stretta",
        rottura_2016=False,
        nota="ISTAT conta solo le autovetture: la voce copre una parte del rischio (esclusi moto, ciclomotori, mezzi pesanti).",  # noqa: E501 — nota della bozza non abbreviata
    ),
    "Property_damage": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_stretta",
        rottura_2016=True,
        nota="Dal 2016 il danneggiamento semplice non è più reato: ISTAT conta solo quello aggravato.",  # noqa: E501 — nota della bozza non abbreviata
    ),
    "Vandalism": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_stretta",
        rottura_2016=True,
        nota="Dal 2016 il danneggiamento semplice non è più reato: ISTAT conta solo quello aggravato.",  # noqa: E501 — nota della bozza non abbreviata
    ),
    "Infrastructure_fire": HazardMapping(
        voce_istat="ARSON",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="",
    ),
    "Explosive_attack": HazardMapping(
        voce_istat="ATTACK",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="",
    ),
    "Terrorist_attack": HazardMapping(
        voce_istat="ATTACK",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota='Esiste anche "omicidi a scopo terroristico", ma solo per gli omicidi consumati.',  # noqa: E501 — nota della bozza non abbreviata
    ),
    "Harm": HazardMapping(
        voce_istat="CULPINJU",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Lesioni dolose; non comprende le percosse.",
    ),
    "Viewer_aggression": HazardMapping(
        voce_istat="CULPINJU",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota='Alternativa: "percosse". Da decidere.',
    ),
    "CyberHazard": HazardMapping(
        voce_istat="CYBERCRIM",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="",
    ),
    "Cyber_hazard": HazardMapping(
        voce_istat="CYBERCRIM",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="",
    ),
    "Branch_damage": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Building_damage": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Cinema_damage": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_in_hospital": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_in_the_bathing_establishment": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_in_the_building": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_in_the_school": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_in_the_warehouse": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_electrical_substation": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_fuel_tanks": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_furniture": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_overhead_lines": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_pharmacy": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_railway_trains": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_refuelling_column": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_archaeological_site": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_business_premises": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_forest_area": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_freeway_artery": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_goods": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_jetty": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_monument": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_movie_theater": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_museum": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_public_space": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_shopping_center": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_stopping_area": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_storage_tank": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_water_system": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_works_of_art": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Equipment_damage": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Helicopter_damage": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Lighthouse_damage": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Pipeline_damage": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Platform_damage": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Power_plant_damage": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Railway_station_damage": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Silo_damage": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Store_damage": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Structure_damage": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Transportation_damage": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Vegetation_damage": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Vehicle_damage": HazardMapping(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Incendiary_attack": HazardMapping(
        voce_istat="DAMARS",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota='Alternativa: "attentati". Da decidere.',
    ),
    "Forest_fire_anthropic": HazardMapping(
        voce_istat="FOREARS",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="La voce ISTAT comprende anche gli incendi boschivi colposi.",
    ),
    "Child_kidnapping": HazardMapping(
        voce_istat="KIDNAPP",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Sequestri di persona, non solo di minori.",
    ),
    "Customer_robbery": HazardMapping(
        voce_istat="ROBBER",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Rapina ai clienti: luogo non specificato, si usa il totale rapine.",
    ),
    "Pharmacy_robbery": HazardMapping(
        voce_istat="ROBBER",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale rapine: nello SDI le farmacie sono un luogo separato dagli esercizi commerciali.",  # noqa: E501 — nota con la fonte
    ),
    "Robbery_at_the_jewelry_store": HazardMapping(
        voce_istat="SHOPROB",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Rapine in esercizi commerciali, non solo gioiellerie.",
    ),
    "Robbery_at_the_mall": HazardMapping(
        voce_istat="SHOPROB",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="",
    ),
    "Robbery_in_the_cinema": HazardMapping(
        voce_istat="ROBBER",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale rapine: nello SDI locali ed esercizi pubblici sono un luogo separato dagli esercizi commerciali.",  # noqa: E501 — nota con la fonte
    ),
    "Tobacconist's_shop_robbery": HazardMapping(
        voce_istat="ROBBER",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale rapine per prudenza: non e' provato che lo SDI conti le tabaccherie fra gli esercizi commerciali.",  # noqa: E501 — nota con la fonte
    ),
    "Jewelry_theft": HazardMapping(
        voce_istat="SHOPTHEF",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Furti in esercizi commerciali, non solo gioiellerie.",
    ),
    "Traveler_robbery": HazardMapping(
        voce_istat="STREETROB",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Rapina al viaggiatore: la voce più vicina è la rapina in pubblica via.",
    ),
    "ATM_removal": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Banknote_acceptor_theft": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Building_theft": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Copper_theft": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Drug_theft": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Electricity_theft": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Equipment_removal": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Equipment_theft": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Fuel_theft": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Fuel_theft_from_tanks": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Helicopter_theft": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Pipeline_theft": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Property_theft": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "School_theft": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Spare_part_theft": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_at_the_refinery_jetty": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_in_hospital": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_in_the_bathing_establishment": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_in_the_warehouse": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_of_drug_vending_machine": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_of_furniture": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_of_gas_cylinders": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_of_goods": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_of_pyrotechnic_material": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_structure_pieces": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Water_theft_from_pipelines": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Water_theft_from_silo": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Weapon_subtraction": HazardMapping(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "ATM_out_of_service": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Absence_of_concession": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Blocking_access_to_the_hospital": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Blocking_of_the_road_in_front_of_the_building": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Building_collapse": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Child_abuse": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Maltrattamenti non pubblicati in 73_67; le voci sui minori sono solo di natura sessuale.",  # noqa: E501 — nota della bozza non abbreviata
    ),
    "Citizen_protest_over_the_proximity_of_the_gas_station_to_homes": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Counterfeit_fuel": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Frode in commercio: nessuna voce ISTAT corrispondente.",
    ),
    "Counterfeiting_of_documents": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Falso documentale non censito in 73_67.",
    ),
    "Counterfeiting_of_foodstuffs": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Sovrapposizione solo parziale con la contraffazione di marchi: non mappato.",  # noqa: E501 — nota della bozza non abbreviata
    ),
    "Crime_explosion": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Rischio generico: il totale dei delitti entra solo come cornice del luogo (D10), non come voce del rischio.",  # noqa: E501 — nota della bozza non abbreviata
    ),
    "Demonstration_in_front_of_the_building": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Demonstration_with_occupation_of_the_tracks": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Distribution_system_out_of_service": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Drone_overflight_and_crash": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Drone_strike": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Nessuna voce ISTAT adeguata.",
    ),
    "Electrical_substation_out_of_service": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Exposure_to_biological_agent": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Gas_station_strike": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Hawker_not_going_to_the_market": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Health_personnel_strike": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Interruption_of_supply": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Landslide": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Occupation_of_the_highway_artery_to_hinder_the_movement_of_vehicles": HazardMapping(  # noqa: E501 - real TERMINUS identifier
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Omission_of_maintenance": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Out_of_service_self-service": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Out_of_service_ticket_office": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Peddlers_strike": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Power_line_out_of_order": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Power_plant_out_of_service": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Prisoner_escape": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Release_of_foreign_substances_into_the_tanks": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Release_of_hazardous_substances_into_pipelines": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "School_dispersion": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Spectator_with_counterfeit_ticket": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Sovrapposizione solo parziale con le truffe: non mappato.",
    ),
    "Spread_of_pathogenic_germs": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Traveller_with_counterfeit_ticket": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Sovrapposizione solo parziale con le truffe: non mappato.",
    ),
    "Unauthorised_strike_by_refinery_employees": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorised_strike_of_prison_staff": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorized_employee_strike": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorized_healt_personnel_strike": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorized_strike_by_cinema_staff": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorized_strike_of_railway_personnel": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorized_strike_of_school_personnel": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorized_strike_of_the_forest_ranger": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorized_strike_of_transportation_company_employees": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorized_workers_strike": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unexcused_absence_of_employees": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unexcused_absence_of_staff": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Violent_prisoner_revolt": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Waiting_for_the_return_of_the_helicopter": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Water_contamination": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Water_poisoning": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Avvelenamento di acque non censito in 73_67.",
    ),
    "Water_purification_plant_not_functioning": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Workers_strike": HazardMapping(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
}
