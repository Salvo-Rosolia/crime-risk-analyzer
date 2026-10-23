"""File di fonti minimi e validi per i test del caricamento (#415).

Ogni test parte da :func:`file_validi` e sostituisce solo il pezzo che vuole
rompere, cosi' il report di un test contiene solo i problemi voluti.
"""

from __future__ import annotations

import json
from dataclasses import replace

from crime_risk_analyzer.sources.parsing import UploadedFiles
from crime_risk_analyzer.sources.vocabulary import OntologyVocabulary

NS = "http://example.org/mini#"

VOCABOLARIO = OntologyVocabulary(
    namespace=NS,
    hazard="hasRisk",
    critical_event="hasEvent",
    performer="hasActor",
    vulnerability=("isFragileTo", "hasWeakness"),
)

ONTOLOGIA_TTL = """
@prefix m: <http://example.org/mini#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .

<http://example.org/mini> a owl:Ontology .

m:Banca a owl:Class ;
    rdfs:label "Banca"@it, "Bank"@en ;
    rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty m:hasRisk ; owl:someValuesFrom m:Rapina ] .
m:Ospedale a owl:Class ;
    rdfs:label "Ospedale"@it, "Hospital"@en ;
    rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty m:hasRisk ; owl:someValuesFrom m:Furto ] .
m:Rapina a owl:Class ; rdfs:label "Rapina"@it, "Robbery"@en .
m:Furto a owl:Class ; rdfs:label "Furto"@it, "Theft"@en .
"""

OSM_CSV = "osm_tag,classe\namenity=bank,Banca\namenity=hospital,Ospedale\n"

DATI_CSV = (
    "luogo,voce,voce_etichetta,anno,delitti,tasso,tasso_sotto_soglia\n"
    "IT,TOT,totale,2024,2000000,3400.0,no\n"
    "IT,TOT,totale,2014,2100000,3500.0,no\n"
    "IT,ROB,rapine,2024,30000,50.0,no\n"
    "IT,ROB,rapine,2014,40000,66.0,no\n"
    "IT,THEFT,furti,2024,900000,1500.0,no\n"
    "IT,THEFT,furti,2014,1000000,1700.0,no\n"
    "001,TOT,totale,2024,5000,4000.0,no\n"
    "001,TOT,totale,2014,5200,4100.0,no\n"
    "001,ROB,rapine,2024,100,80.0,no\n"
    "001,ROB,rapine,2014,150,120.0,no\n"
    "001,THEFT,furti,2024,2000,2500.0,no\n"
    "001,THEFT,furti,2014,2500,3000.0,no\n"
)

HAZARD_CSV = (
    "hazard,voce,corrispondenza,serie_non_confrontabile,nota\n"
    "Rapina,ROB,esatta,no,\n"
    "Furto,THEFT,piu_larga,si,Serie interrotta nel 2016\n"
)

CONFINI = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {
                "codice": "001",
                "tipo": "comune",
                "nome": "Comune di Esempio",
                "nome_breve": "Esempio",
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [12.0, 41.0],
                        [13.0, 41.0],
                        [13.0, 42.0],
                        [12.0, 42.0],
                        [12.0, 41.0],
                    ]
                ],
            },
        }
    ],
}


def confini_json(obj: object = CONFINI) -> bytes:
    return json.dumps(obj).encode("utf-8")


def file_validi() -> UploadedFiles:
    return UploadedFiles(
        ontology=ONTOLOGIA_TTL.encode("utf-8"),
        ontology_name="mini.ttl",
        osm_table=OSM_CSV.encode("utf-8"),
        data=DATI_CSV.encode("utf-8"),
        hazard_table=HAZARD_CSV.encode("utf-8"),
        boundaries=confini_json(),
    )


def con(**campi: object) -> UploadedFiles:
    """File validi con alcuni campi sostituiti."""
    return replace(file_validi(), **campi)  # pyright: ignore[reportArgumentType]
