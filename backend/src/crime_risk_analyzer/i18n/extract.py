"""Deterministic extraction of the surfacing subgraph of the ontology (#77).

Seeds = target POI classes of ``OSM_TO_TERMINUS`` (excluding the generic fallback);
they are expanded via ``rdfs:subClassOf*`` and the ``owl:Restriction`` on the
relevant object properties are followed to collect linked
hazards/events/vulnerabilities. It emits records with the real ``identifier`` (typos
preserved), display ``label_en`` (known typos fixed) and empty ``label_it`` to be
curated by hand. Re-runnable: ``merge_preserving_it`` keeps the IT labels already
curated.

CLI: ``uv run python -m crime_risk_analyzer.i18n.extract [--src OWL] [--out JSON]``
(reads the ghost ontology; the generated JSON is the committed artefact).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

from rdflib import RDFS, Graph, Namespace
from rdflib.namespace import OWL

from crime_risk_analyzer.i18n.terminus_labels import LabelRecord
from crime_risk_analyzer.sources.model import TERMINUS_CONFIG, OntologyConfig
from crime_risk_analyzer.sparql_module.osm_mapping import (
    GENERIC_FALLBACK,
    OSM_TO_TERMINUS,
)

_DEFAULT_SRC = "ontology/terminus-crime.owl"
_DEFAULT_OUT = str(Path(__file__).parent / "terminus_labels.json")

#: Known typos of the ontology → corrected EN label (display only).
#: The entries below are illustrative examples of the mechanism; they do not appear
#: in the current surfacing subgraph (the real classes use correct spellings).
#: They are kept as a forward-looking guard and exercised by the tests of Task 2.
_TYPO_FIXES: dict[str, str] = {
    "Brank_branch": "Branch robbery",
    "Buiding_damage": "Building damage",
}

_CATEGORY_ORDER: dict[str, int] = {
    "poi": 0,
    "hazard": 1,
    "critical_event": 2,
    "vulnerability": 3,
    "stakeholder": 4,
}

_FILLER_Q = """
SELECT DISTINCT ?filler WHERE {
    ?poi rdfs:subClassOf* ?c .
    ?c rdfs:subClassOf ?r .
    ?r a owl:Restriction ; owl:onProperty ?p ; owl:someValuesFrom ?filler .
    FILTER(isIRI(?filler))
}
"""


def display_label(identifier: str) -> str:
    """Readable EN label: known typos fixed, otherwise normalised."""
    if identifier in _TYPO_FIXES:
        return _TYPO_FIXES[identifier]
    text = identifier.replace("_", " ").strip()
    if not text:
        return identifier
    return text[:1].upper() + text[1:]


def _local(uri: object) -> str:
    text = str(uri)
    return text.rsplit("#", 1)[-1] if "#" in text else text.rsplit("/", 1)[-1]


def _record(identifier: str, category: str) -> LabelRecord:
    return {
        "identifier": identifier,
        "label_en": display_label(identifier),
        "label_it": "",
        "category": category,
    }


def _prop_category(ontology: OntologyConfig) -> dict[str, str]:
    """Local name of the property -> category of the filler, from the ontology."""
    return {
        ontology.hazard: "hazard",
        ontology.critical_event: "critical_event",
        **{name: "vulnerability" for name in ontology.vulnerability},
        ontology.performer: "stakeholder",
    }


def extract_records(
    graph: Graph,
    seeds: Iterable[str],
    ontology: OntologyConfig = TERMINUS_CONFIG,
) -> list[LabelRecord]:
    """Extracts the records of the surfacing subgraph starting from the seed POIs.

    Namespace and property names come from ``ontology`` (default TERMINUS, #434).

    A filler can be reached by SEVERAL properties with different categories (on the
    real surfacing subgraph it already happens, not only in theory: e.g.
    ``ATM_out_of_service`` is both hazard and critical_event on different POIs).
    The category is not that of the first property met while iterating
    the property -> category map — it would depend on the dict order, incidental — but
    the one with the highest priority in ``_CATEGORY_ORDER`` (the same order already
    used for the output): an explicit and stable criterion, not a side
    effect of the definition order.
    """
    ns = Namespace(ontology.namespace)
    prop_category = _prop_category(ontology)
    poi_records: dict[str, LabelRecord] = {}
    filler_categories: dict[str, set[str]] = {}
    for poi in sorted(set(seeds)):
        poi_uri = ns[poi]
        if not any(graph.triples((poi_uri, None, None))):
            continue
        poi_records.setdefault(poi, _record(poi, "poi"))
        for prop, category in prop_category.items():
            rows = graph.query(
                _FILLER_Q,
                initBindings={"poi": poi_uri, "p": ns[prop]},
                initNs={"rdfs": RDFS, "owl": OWL},
            )
            for row in rows:
                filler = _local(row.filler)  # type: ignore[attr-defined]
                filler_categories.setdefault(filler, set()).add(category)

    records: dict[str, LabelRecord] = {
        filler: _record(filler, min(categories, key=lambda c: _CATEGORY_ORDER[c]))
        for filler, categories in filler_categories.items()
    }
    records.update(poi_records)
    return sorted(
        records.values(),
        key=lambda r: (_CATEGORY_ORDER[r["category"]], r["identifier"]),
    )


def merge_preserving_it(
    new_records: list[LabelRecord], existing: list[LabelRecord]
) -> list[LabelRecord]:
    """Keeps the ``label_it`` already curated for the existing identifiers."""
    prev = {r["identifier"]: r["label_it"] for r in existing if r["label_it"]}
    for rec in new_records:
        if not rec["label_it"] and rec["identifier"] in prev:
            rec["label_it"] = prev[rec["identifier"]]
    return new_records


def _load_existing(out_path: Path) -> list[LabelRecord]:
    if not out_path.exists():
        return []
    return json.loads(out_path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def main() -> None:
    parser = argparse.ArgumentParser(description="Extracts the EN→IT vocabulary (#77).")
    parser.add_argument("--src", default=_DEFAULT_SRC, help="Source ontology.")
    parser.add_argument("--out", default=_DEFAULT_OUT, help="Destination JSON.")
    args = parser.parse_args()

    graph = Graph()
    fmt = "xml" if str(args.src).endswith(".owl") else "turtle"
    graph.parse(args.src, format=fmt)

    seeds = [v for v in OSM_TO_TERMINUS.values() if v != GENERIC_FALLBACK]
    new_records = extract_records(graph, seeds)

    out_path = Path(args.out)
    merged = merge_preserving_it(new_records, _load_existing(out_path))
    out_path.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    curated = sum(1 for r in merged if r["label_it"])
    print(f"Written {len(merged)} records ({curated} with label_it) to {out_path}")


if __name__ == "__main__":
    main()
