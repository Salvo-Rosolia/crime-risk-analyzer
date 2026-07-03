"""Estrazione deterministica del sottografo affiorante dell'ontologia (#77).

Semi = classi POI target di ``OSM_TO_TERMINUS`` (escluso il fallback generico);
si espandono via ``rdfs:subClassOf*`` e si seguono le ``owl:Restriction`` sulle
object property rilevanti per raccogliere hazard/eventi/vulnerabilità collegati.
Emette record con ``identifier`` reale (refusi preservati), ``label_en`` display
(refusi noti corretti) e ``label_it`` vuoto da curare a mano. Ri-eseguibile:
``merge_preserving_it`` conserva le etichette IT già curate.

CLI: ``uv run python -m crime_risk_analyzer.i18n.extract [--src OWL] [--out JSON]``
(legge l'ontologia ghost; il JSON generato è l'artefatto committato).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

from rdflib import RDFS, Graph
from rdflib.namespace import OWL

from crime_risk_analyzer.i18n.terminus_labels import LabelRecord
from crime_risk_analyzer.ontology_namespaces import TERMINUS
from crime_risk_analyzer.sparql_module.osm_mapping import (
    GENERIC_FALLBACK,
    OSM_TO_TERMINUS,
)

_DEFAULT_SRC = "ontology/terminus-crime.owl"
_DEFAULT_OUT = str(Path(__file__).parent / "terminus_labels.json")

#: Refusi noti dell'ontologia → etichetta EN corretta (solo display).
_TYPO_FIXES: dict[str, str] = {
    "Brank_branch": "Branch robbery",
    "Buiding_damage": "Building damage",
}

#: Object property → categoria del filler.
_PROP_CATEGORY: dict[str, str] = {
    "havingHazard": "hazard",
    "havingCriticalEvent": "critical_event",
    "havingVulnerability": "vulnerability",
    "isVulnerableTo": "vulnerability",
}

_CATEGORY_ORDER: dict[str, int] = {
    "poi": 0,
    "hazard": 1,
    "critical_event": 2,
    "vulnerability": 3,
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
    """Etichetta EN leggibile: refusi noti corretti, altrimenti normalizzata."""
    if identifier in _TYPO_FIXES:
        return _TYPO_FIXES[identifier]
    text = identifier.replace("_", " ").strip()
    if not text:
        return identifier
    return text[:1].upper() + text[1:]


def _local(uri: object) -> str:
    return str(uri).rsplit("#", 1)[-1]


def _record(identifier: str, category: str) -> LabelRecord:
    return {
        "identifier": identifier,
        "label_en": display_label(identifier),
        "label_it": "",
        "category": category,
    }


def extract_records(graph: Graph, seeds: Iterable[str]) -> list[LabelRecord]:
    """Estrae i record del sottografo affiorante a partire dai POI seed."""
    records: dict[str, LabelRecord] = {}
    for poi in sorted(set(seeds)):
        poi_uri = TERMINUS[poi]
        if not any(graph.triples((poi_uri, None, None))):
            continue
        records.setdefault(poi, _record(poi, "poi"))
        for prop, category in _PROP_CATEGORY.items():
            rows = graph.query(
                _FILLER_Q,
                initBindings={"poi": poi_uri, "p": TERMINUS[prop]},
                initNs={"rdfs": RDFS, "owl": OWL},
            )
            for row in rows:
                filler = _local(row.filler)  # type: ignore[attr-defined]
                records.setdefault(filler, _record(filler, category))
    return sorted(
        records.values(),
        key=lambda r: (_CATEGORY_ORDER[r["category"]], r["identifier"]),
    )


def merge_preserving_it(
    new_records: list[LabelRecord], existing: list[LabelRecord]
) -> list[LabelRecord]:
    """Conserva i ``label_it`` già curati per gli identifier esistenti."""
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
    parser = argparse.ArgumentParser(description="Estrae il vocabolario EN→IT (#77).")
    parser.add_argument("--src", default=_DEFAULT_SRC, help="Ontologia sorgente.")
    parser.add_argument("--out", default=_DEFAULT_OUT, help="JSON di destinazione.")
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
    curati = sum(1 for r in merged if r["label_it"])
    print(f"Scritti {len(merged)} record ({curati} con label_it) in {out_path}")


if __name__ == "__main__":
    main()
