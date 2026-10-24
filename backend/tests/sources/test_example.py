"""Set d'esempio delle fonti dinamiche (#417)."""

from collections.abc import Iterator

import pytest
from rdflib import URIRef
from rdflib.namespace import RDFS

from crime_risk_analyzer import zone_context_cache
from crime_risk_analyzer.geocoding import GeoResult
from crime_risk_analyzer.istat.dati import dati_istat_o_none
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.orchestrator import run_baseline
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.sources.build import fallback_luoghi
from crime_risk_analyzer.sources.context import bind, current_executor
from crime_risk_analyzer.sources.example import (
    EXAMPLE_VOCABULARY,
    example_files,
    example_set,
    example_warnings,
)
from crime_risk_analyzer.sources.model import TERMINUS_CONFIG
from crime_risk_analyzer.sources.parsing import check_sources
from crime_risk_analyzer.sources.vocabulary import TERMINUS_VOCABULARY


@pytest.fixture(autouse=True)
def _pulisci_cache() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    zone_context_cache.clear()
    yield
    zone_context_cache.clear()


def _classi_poi() -> set[str]:
    return set(example_set().osm.osm_to_class.values())


def test_i_file_d_esempio_non_hanno_errori() -> None:
    parsed, report = check_sources(
        example_files(), EXAMPLE_VOCABULARY, fallback_luoghi=fallback_luoghi()
    )
    assert report.errors == []
    assert parsed is not None


def test_example_set_ha_kind_example_ed_e_costruito_una_volta() -> None:
    assert example_set().kind == "example"
    assert example_set().id == "example"
    assert example_set() is example_set()


def test_ontologia_inventata_con_una_decina_di_classi_poi() -> None:
    assert len(_classi_poi()) == 10
    assert EXAMPLE_VOCABULARY.namespace == "http://example.org/mini-crime#"
    assert EXAMPLE_VOCABULARY.namespace != TERMINUS_VOCABULARY.namespace
    assert set(EXAMPLE_VOCABULARY.properties).isdisjoint(TERMINUS_VOCABULARY.properties)
    assert example_set().ontology.namespace == EXAMPLE_VOCABULARY.namespace
    assert example_set().ontology != TERMINUS_CONFIG


def test_ogni_classe_poi_ha_almeno_un_hazard() -> None:
    executor = example_set().executor
    for classe in sorted(_classi_poi()):
        assert executor.profile(classe).hazards, classe


def test_il_profilo_usa_le_proprieta_proprie_dell_esempio() -> None:
    profilo = example_set().executor.profile("Bank")
    assert "Bank_robbery" in profilo.hazards
    assert "Bank → hasRisk → Bank_robbery" in profilo.sparql_paths
    assert profilo.critical_events
    assert profilo.stakeholders
    assert profilo.vulnerabilities


def test_la_classe_eredita_le_restrizioni_della_superclasse() -> None:
    assert "Theft" in example_set().executor.profile("Pharmacy").hazards


def test_etichette_presenti_per_meta_delle_classi_poi() -> None:
    ss = example_set()
    con_etichette = {
        str(c).rsplit("#", 1)[-1]
        for c in ss.graph.subjects(RDFS.label)
        if isinstance(c, URIRef)
    }
    assert len(con_etichette & _classi_poi()) == 5
    labels = ss.labels
    assert labels is not None
    assert labels["Bank"] == ("Banca", "Bank")
    assert labels["Jewelry_shop"] == ("Jewelry shop", "Jewelry shop")  # ripiego


def test_gli_avvisi_segnalano_le_etichette_mancanti() -> None:
    codici = {p.code for p in example_warnings()}
    assert "etichetta_mancante" in codici


def test_i_dati_coincidono_con_delitti_json() -> None:
    reale = dati_istat_o_none()
    assert reale is not None
    esempio = example_set().istat.dati
    assert esempio is not None
    confrontati = 0
    for luogo, per_voce in esempio.delitti.valori.items():
        for voce, per_anno in per_voce.items():
            for anno, valore in per_anno.items():
                assert valore == reale.delitti.valori[luogo][voce][anno], (
                    luogo,
                    voce,
                    anno,
                )
                confrontati += 1
    assert confrontati >= 5
    # campione esplicito di cinque valori, con luogo, voce e anno
    campione = [
        ("058091", "ROBBER", 2024),
        ("015146", "THEFT", 2014),
        ("063049", "TOT", 2024),
        ("IT", "BANKROB", 2024),
        ("058091", "CARTHEF", 2014),
    ]
    for luogo, voce, anno in campione:
        assert esempio.delitti.valore(luogo, voce, anno) == reale.delitti.valore(
            luogo, voce, anno
        )
        assert esempio.delitti.valore(luogo, voce, anno) is not None


def test_i_luoghi_dell_esempio_sono_tre_comuni_con_i_confini_nostri() -> None:
    dati = example_set().istat.dati
    assert dati is not None
    assert {lg.nome_breve for lg in dati.luoghi} == {"Roma", "Milano", "Napoli"}


def test_serie_non_confrontabili_dichiarate_nella_tabella() -> None:
    assert example_set().istat.voci_rottura == {"DAMAGE", "TOT"}
    assert example_set().istat.mappatura["Burglary"].voce_istat is None


async def test_baseline_con_poi_finti_cita_l_ontologia_dell_esempio() -> None:
    async def geo(citta: str, zona: str) -> GeoResult:
        return GeoResult(lat=41.89, lon=12.49, bbox=Bbox(41.88, 12.48, 41.90, 12.50))

    async def poi_source(bbox: Bbox, citta: str) -> list[Poi]:
        return [
            {
                "id": "node/1",
                "name": "Banca Esempio",
                "lat": 41.89,
                "lon": 12.49,
                "osm_tags": "amenity=bank",
                "terminus_class": "Bank",
                "citta": citta,
            }
        ]

    with bind(example_set()):
        risposta = await run_baseline(
            "Roma",
            "Colosseo",
            executor=current_executor(),
            poi_source=poi_source,
            geo_source=geo,
        )
    rischi = risposta.risk_models[0].risks
    assert rischi
    assert all(r.tag == "ONTOLOGIA" for r in rischi)
    assert {r.hazard for r in rischi} == {"Bank_robbery", "Theft"}  # Theft: ereditato
    for r in rischi:
        assert r.source is not None
        classe, _proprieta, entita = (parte.strip() for parte in r.source.split("→"))
        assert (classe, entita) == ("Bank", r.hazard)
    assert risposta.poi[0].sparql_path is not None
    assert risposta.poi[0].terminus_label_it == "Banca"
