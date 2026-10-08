"""Tabella hazard TERMINUS -> voce ISTAT (#345, spec 4.2 / D3).

Una riga per ciascuno dei 155 hazard dell'ontologia. ``voce_istat`` e' il codice
della voce del dataset ISTAT 73_67 (``None`` = nessuna voce adeguata, anche quando
la sovrapposizione e' solo parziale); ``corrispondenza`` dice come la voce sta
rispetto al rischio:

- ``esatta``: la voce e' lo stesso reato;
- ``piu_larga``: la voce comprende il rischio e altro (es. "furti" per "furto di rame");
- ``piu_stretta``: la voce copre solo una parte del rischio.

``rottura_2016``: la voce e' toccata dalla depenalizzazione del d.lgs. 7/2016, quindi
la variazione decennale non si calcola. Ripete il campo della voce nel catalogo
(:mod:`~crime_risk_analyzer.istat.catalogo`, #353), che e' la sorgente di
``VOCI_ROTTURA_2016``; un test vincola i due a coincidere. Nessuna somma di voci.

Trascritta dalla bozza revisionata (foglio "Mappatura"), stile
``sparql_module/osm_mapping.py``. I conteggi fissati in
``tests/istat/test_mappatura.py`` (righe mappate, corrispondenze, voci distinte)
non bastano: spostare un hazard fra due voci con la stessa corrispondenza li
lascia invariati. Per questo lo stesso file fissa anche gli hazard per voce, che
coglie lo spostamento; resta invisibile ai conteggi solo lo scambio di due
hazard fra due voci, coperto dove serve da test puntuali. **Da verificare
dall'utente prima del merge (D3).**
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["MAPPATURA", "Corrispondenza", "Mappatura"]

#: Rapporto fra la voce ISTAT e il rischio (D3).
Corrispondenza = Literal["esatta", "piu_larga", "piu_stretta"]


@dataclass(frozen=True)
class Mappatura:
    """Collegamento di un hazard a una voce ISTAT (o la sua assenza)."""

    voce_istat: str | None
    corrispondenza: Corrispondenza | None
    rottura_2016: bool
    nota: str


#: hazard TERMINUS (identifier reale) -> collegamento alla voce ISTAT.
MAPPATURA: dict[str, Mappatura] = {
    "Theft_of_ancient_artifacts": Mappatura(
        voce_istat="ARTTHEF",
        corrispondenza="esatta",
        rottura_2016=False,
        nota="La voce ISTAT comprende il materiale archeologico.",
    ),
    "Theft_of_works_of_art": Mappatura(
        voce_istat="ARTTHEF",
        corrispondenza="esatta",
        rottura_2016=False,
        nota="",
    ),
    "Purse_snatching": Mappatura(
        voce_istat="BAGTHEF",
        corrispondenza="esatta",
        rottura_2016=False,
        nota="",
    ),
    "Bank_robbery": Mappatura(
        voce_istat="BANKROB",
        corrispondenza="esatta",
        rottura_2016=False,
        nota="",
    ),
    "Cyber_attack": Mappatura(
        voce_istat="CYBERCRIM",
        corrispondenza="esatta",
        rottura_2016=False,
        nota="",
    ),
    "Post_office_robbery": Mappatura(
        voce_istat="POSTROB",
        corrispondenza="esatta",
        rottura_2016=False,
        nota="",
    ),
    "Store_robbery": Mappatura(
        voce_istat="SHOPROB",
        corrispondenza="esatta",
        rottura_2016=False,
        nota="",
    ),
    "Mugging": Mappatura(
        voce_istat="STREETROB",
        corrispondenza="esatta",
        rottura_2016=False,
        nota="Aggressione a scopo di furto in strada = rapina in pubblica via.",
    ),
    "Vehicle_Theft": Mappatura(
        voce_istat="CARTHEF",
        corrispondenza="piu_stretta",
        rottura_2016=False,
        nota="ISTAT conta solo le autovetture: la voce copre una parte del rischio (esclusi moto, ciclomotori, mezzi pesanti).",  # noqa: E501 — nota della bozza non abbreviata
    ),
    "Property_damage": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_stretta",
        rottura_2016=True,
        nota="Dal 2016 il danneggiamento semplice non è più reato: ISTAT conta solo quello aggravato.",  # noqa: E501 — nota della bozza non abbreviata
    ),
    "Vandalism": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_stretta",
        rottura_2016=True,
        nota="Dal 2016 il danneggiamento semplice non è più reato: ISTAT conta solo quello aggravato.",  # noqa: E501 — nota della bozza non abbreviata
    ),
    "Infrastructure_fire": Mappatura(
        voce_istat="ARSON",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="",
    ),
    "Explosive_attack": Mappatura(
        voce_istat="ATTACK",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="",
    ),
    "Terrorist_attack": Mappatura(
        voce_istat="ATTACK",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota='Esiste anche "omicidi a scopo terroristico", ma solo per gli omicidi consumati.',  # noqa: E501 — nota della bozza non abbreviata
    ),
    "Harm": Mappatura(
        voce_istat="CULPINJU",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Lesioni dolose; non comprende le percosse.",
    ),
    "Viewer_aggression": Mappatura(
        voce_istat="CULPINJU",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota='Alternativa: "percosse". Da decidere.',
    ),
    "CyberHazard": Mappatura(
        voce_istat="CYBERCRIM",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="",
    ),
    "Cyber_hazard": Mappatura(
        voce_istat="CYBERCRIM",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="",
    ),
    "Branch_damage": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Building_damage": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Cinema_damage": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_in_hospital": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_in_the_bathing_establishment": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_in_the_building": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_in_the_school": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_in_the_warehouse": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_electrical_substation": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_fuel_tanks": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_furniture": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_overhead_lines": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_pharmacy": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_railway_trains": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_refuelling_column": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_archaeological_site": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_business_premises": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_forest_area": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_freeway_artery": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_goods": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_jetty": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_monument": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_movie_theater": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_museum": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_public_space": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_shopping_center": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_stopping_area": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_storage_tank": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_the_water_system": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Damage_to_works_of_art": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Equipment_damage": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Helicopter_damage": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Lighthouse_damage": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Pipeline_damage": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Platform_damage": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Power_plant_damage": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Railway_station_damage": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Silo_damage": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Store_damage": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Structure_damage": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Transportation_damage": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Vegetation_damage": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Vehicle_damage": Mappatura(
        voce_istat="DAMAGE",
        corrispondenza="piu_larga",
        rottura_2016=True,
        nota="Totale danneggiamenti (voce più ampia del rischio).",
    ),
    "Incendiary_attack": Mappatura(
        voce_istat="DAMARS",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota='Alternativa: "attentati". Da decidere.',
    ),
    "Forest_fire_anthropic": Mappatura(
        voce_istat="FOREARS",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="La voce ISTAT comprende anche gli incendi boschivi colposi.",
    ),
    "Child_kidnapping": Mappatura(
        voce_istat="KIDNAPP",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Sequestri di persona, non solo di minori.",
    ),
    "Customer_robbery": Mappatura(
        voce_istat="ROBBER",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Rapina ai clienti: luogo non specificato, si usa il totale rapine.",
    ),
    "Pharmacy_robbery": Mappatura(
        voce_istat="ROBBER",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale rapine: nello SDI le farmacie sono un luogo separato dagli esercizi commerciali.",  # noqa: E501 — nota con la fonte
    ),
    "Robbery_at_the_jewelry_store": Mappatura(
        voce_istat="SHOPROB",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Rapine in esercizi commerciali, non solo gioiellerie.",
    ),
    "Robbery_at_the_mall": Mappatura(
        voce_istat="SHOPROB",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="",
    ),
    "Robbery_in_the_cinema": Mappatura(
        voce_istat="ROBBER",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale rapine: nello SDI locali ed esercizi pubblici sono un luogo separato dagli esercizi commerciali.",  # noqa: E501 — nota con la fonte
    ),
    "Tobacconist's_shop_robbery": Mappatura(
        voce_istat="ROBBER",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale rapine per prudenza: non e' provato che lo SDI conti le tabaccherie fra gli esercizi commerciali.",  # noqa: E501 — nota con la fonte
    ),
    "Jewelry_theft": Mappatura(
        voce_istat="SHOPTHEF",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Furti in esercizi commerciali, non solo gioiellerie.",
    ),
    "Traveler_robbery": Mappatura(
        voce_istat="STREETROB",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Rapina al viaggiatore: la voce più vicina è la rapina in pubblica via.",
    ),
    "ATM_removal": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Banknote_acceptor_theft": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Building_theft": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Copper_theft": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Drug_theft": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Electricity_theft": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Equipment_removal": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Equipment_theft": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Fuel_theft": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Fuel_theft_from_tanks": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Helicopter_theft": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Pipeline_theft": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Property_theft": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "School_theft": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Spare_part_theft": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_at_the_refinery_jetty": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_in_hospital": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_in_the_bathing_establishment": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_in_the_warehouse": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_of_drug_vending_machine": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_of_furniture": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_of_gas_cylinders": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_of_goods": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_of_pyrotechnic_material": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Theft_structure_pieces": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Water_theft_from_pipelines": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Water_theft_from_silo": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "Weapon_subtraction": Mappatura(
        voce_istat="THEFT",
        corrispondenza="piu_larga",
        rottura_2016=False,
        nota="Totale furti: la voce ISTAT non distingue questo tipo di furto.",
    ),
    "ATM_out_of_service": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Absence_of_concession": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Blocking_access_to_the_hospital": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Blocking_of_the_road_in_front_of_the_building": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Building_collapse": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Child_abuse": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Maltrattamenti non pubblicati in 73_67; le voci sui minori sono solo di natura sessuale.",  # noqa: E501 — nota della bozza non abbreviata
    ),
    "Citizen_protest_over_the_proximity_of_the_gas_station_to_homes": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Counterfeit_fuel": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Frode in commercio: nessuna voce ISTAT corrispondente.",
    ),
    "Counterfeiting_of_documents": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Falso documentale non censito in 73_67.",
    ),
    "Counterfeiting_of_foodstuffs": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Sovrapposizione solo parziale con la contraffazione di marchi: non mappato.",  # noqa: E501 — nota della bozza non abbreviata
    ),
    "Crime_explosion": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Rischio generico: il totale dei delitti entra solo come cornice del luogo (D10), non come voce del rischio.",  # noqa: E501 — nota della bozza non abbreviata
    ),
    "Demonstration_in_front_of_the_building": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Demonstration_with_occupation_of_the_tracks": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Distribution_system_out_of_service": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Drone_overflight_and_crash": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Drone_strike": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Nessuna voce ISTAT adeguata.",
    ),
    "Electrical_substation_out_of_service": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Exposure_to_biological_agent": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Gas_station_strike": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Hawker_not_going_to_the_market": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Health_personnel_strike": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Interruption_of_supply": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Landslide": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Occupation_of_the_highway_artery_to_hinder_the_movement_of_vehicles": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Omission_of_maintenance": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Out_of_service_self-service": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Out_of_service_ticket_office": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Peddlers_strike": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Power_line_out_of_order": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Power_plant_out_of_service": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Prisoner_escape": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Release_of_foreign_substances_into_the_tanks": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Release_of_hazardous_substances_into_pipelines": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "School_dispersion": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Spectator_with_counterfeit_ticket": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Sovrapposizione solo parziale con le truffe: non mappato.",
    ),
    "Spread_of_pathogenic_germs": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Traveller_with_counterfeit_ticket": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Sovrapposizione solo parziale con le truffe: non mappato.",
    ),
    "Unauthorised_strike_by_refinery_employees": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorised_strike_of_prison_staff": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorized_employee_strike": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorized_healt_personnel_strike": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorized_strike_by_cinema_staff": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorized_strike_of_railway_personnel": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorized_strike_of_school_personnel": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorized_strike_of_the_forest_ranger": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorized_strike_of_transportation_company_employees": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unauthorized_workers_strike": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unexcused_absence_of_employees": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Unexcused_absence_of_staff": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Violent_prisoner_revolt": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Waiting_for_the_return_of_the_helicopter": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Water_contamination": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Water_poisoning": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="Avvelenamento di acque non censito in 73_67.",
    ),
    "Water_purification_plant_not_functioning": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
    "Workers_strike": Mappatura(
        voce_istat=None,
        corrispondenza=None,
        rottura_2016=False,
        nota="",
    ),
}
