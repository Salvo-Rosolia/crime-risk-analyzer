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
    # real identifier with the typo preserved; corrected label_en
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


def test_extract_category_collision_does_not_depend_on_dict_order() -> None:
    """A filler reached by two properties with different categories does not take
    the one of the first property iterated in ``_prop_category()`` (incidental
    dict order): the category with the higher priority in ``_CATEGORY_ORDER`` wins.

    Empirically reproduces the defect reported in review: before the fix, a
    filler already reachable via a mapped property kept that category and never
    became ``stakeholder`` even when also reachable via ``havingPerformer`` --
    not because ``stakeholder`` was lower priority by construction, but only
    because ``havingPerformer`` is the last entry of the dict returned by
    ``_prop_category()``. Here the vulnerability (priority 3) wins over the
    stakeholder (priority 4) because ``_CATEGORY_ORDER`` says so, not because it
    is listed first.
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


def test_extract_follows_the_properties_of_the_given_ontology() -> None:
    """Namespace and properties come from the configuration, not TERMINUS (#434)."""
    from crime_risk_analyzer.sources.model import OntologyConfig

    g = Graph()
    g.parse(
        data="""
        @prefix ex:   <http://example.org/o#> .
        @prefix owl:  <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        ex:Bank a owl:Class ;
            rdfs:subClassOf [ a owl:Restriction ;
                owl:onProperty ex:hasRisk ;
                owl:someValuesFrom ex:Robbery ] ;
            rdfs:subClassOf [ a owl:Restriction ;
                owl:onProperty ex:weakTo ;
                owl:someValuesFrom ex:Poor_surveillance ] .
        """,
        format="turtle",
    )
    config = OntologyConfig(
        namespace="http://example.org/o#",
        hazard="hasRisk",
        critical_event="hasEvent",
        performer="hasActor",
        vulnerability=("weakTo",),
    )

    by_id = {
        r["identifier"]: r
        for r in extract.extract_records(g, ["Bank"], ontology=config)
    }

    assert by_id["Robbery"]["category"] == "hazard"
    assert by_id["Poor_surveillance"]["category"] == "vulnerability"
