from __future__ import annotations

from pathlib import Path

from rdflib import Graph

from crime_risk_analyzer.i18n import extract

_FRAGMENT = Path(__file__).parent.parent / "fixtures" / "terminus_labels_fragment.ttl"


def _graph() -> Graph:
    g = Graph()
    g.parse(_FRAGMENT, format="turtle")
    return g


def test_extract_includes_seed_poi() -> None:
    records = extract.extract_records(_graph(), ["Bank"])
    by_id = {r["identifier"]: r for r in records}
    assert by_id["Bank"]["category"] == "poi"
    assert by_id["Bank"]["label_en"] == "Bank"
    assert by_id["Bank"]["label_it"] == ""


def test_extract_follows_hazard_restriction_and_fixes_typo() -> None:
    records = extract.extract_records(_graph(), ["Bank"])
    by_id = {r["identifier"]: r for r in records}
    # identifier reale col refuso preservato; label_en corretta
    assert by_id["Brank_branch"]["category"] == "hazard"
    assert by_id["Brank_branch"]["label_en"] == "Branch robbery"
    assert by_id["Brank_branch"]["label_it"] == ""


def test_extract_follows_vulnerability_restriction() -> None:
    records = extract.extract_records(_graph(), ["Bank"])
    by_id = {r["identifier"]: r for r in records}
    assert by_id["Unmanned_access"]["category"] == "vulnerability"


def test_extract_follows_stakeholder_restriction() -> None:
    records = extract.extract_records(_graph(), ["Bank"])
    by_id = {r["identifier"]: r for r in records}
    assert by_id["Branch_manager"]["category"] == "stakeholder"


def test_extract_categoria_collisione_non_dipende_dall_ordine_del_dict() -> None:
    """Un filler raggiunto da due property con categorie diverse non prende quella
    della prima property iterata in ``_PROP_CATEGORY`` (ordine incidentale del
    dict): vince la categoria con priorita' piu' alta in ``_CATEGORY_ORDER``.

    Riproduce empiricamente il difetto segnalato in review: prima della fix, un
    filler gia' raggiungibile via una property mappata restava con quella
    categoria e non diventava mai ``stakeholder`` anche quando raggiungibile
    anche via ``havingPerformer`` — non perche' ``stakeholder`` fosse meno
    prioritario per costruzione, ma solo perche' ``havingPerformer`` e' l'ultima
    entry del dict ``_PROP_CATEGORY``. Qui la vulnerabilita' (priorita' 3) vince
    sullo stakeholder (priorita' 4) perche' lo dichiara ``_CATEGORY_ORDER``, non
    perche' e' elencata prima.
    """
    g = Graph()
    g.parse(
        data="""
        @prefix tc:   <http://www.enea-terin-sen-apic.it/TERMINUS-crime-v01#> .
        @prefix owl:  <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        tc:Museum a owl:Class ;
            rdfs:subClassOf [ a owl:Restriction ;
                owl:onProperty tc:isVulnerableTo ;
                owl:someValuesFrom tc:Contested_role ] ;
            rdfs:subClassOf [ a owl:Restriction ;
                owl:onProperty tc:havingPerformer ;
                owl:someValuesFrom tc:Contested_role ] .

        tc:Contested_role a owl:Class .
        """,
        format="turtle",
    )

    records = extract.extract_records(g, ["Museum"])
    by_id = {r["identifier"]: r for r in records}

    assert by_id["Contested_role"]["category"] == "vulnerability"


def test_extract_skips_seeds_absent_from_graph() -> None:
    records = extract.extract_records(_graph(), ["Bank", "Hospital"])
    ids = {r["identifier"] for r in records}
    assert "Hospital" not in ids


def test_display_label_normalises_and_fixes_typo() -> None:
    assert extract.display_label("Brank_branch") == "Branch robbery"
    assert extract.display_label("Unmanned_access") == "Unmanned access"


def test_merge_preserves_existing_it() -> None:
    new = [
        {
            "identifier": "Brank_branch",
            "label_en": "Branch robbery",
            "label_it": "",
            "category": "hazard",
        }
    ]
    existing = [
        {
            "identifier": "Brank_branch",
            "label_en": "Branch robbery",
            "label_it": "Rapina in filiale",
            "category": "hazard",
        }
    ]
    merged = extract.merge_preserving_it(new, existing)  # type: ignore[arg-type]
    assert merged[0]["label_it"] == "Rapina in filiale"
