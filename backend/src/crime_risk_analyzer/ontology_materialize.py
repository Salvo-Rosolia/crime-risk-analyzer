"""Materializzazione offline dell'ontologia OWL (RDF/XML) -> Turtle (#74).

PURA conversione di sintassi con ``rdflib``: parse del file OWL fornito dal
relatore, bind di un prefisso leggibile per l'IRI ENEA reale, serializzazione a
Turtle. **Niente reasoner, niente owlready2/HermiT, niente Java** (spec-root
§Stack: zero-Java a runtime; qui e' comunque solo conversione sintattica).

Il file OWL sorgente e il TTL prodotto sono entrambi *ghost*: gitignored, non
vanno su GitHub (licenza/riuso da chiarire — vedi ``.gitignore``). Questo modulo
e' lo strumento offline che un operatore esegue una tantum per produrre il
``.ttl`` che il loader di runtime (:mod:`~crime_risk_analyzer.ontology`)
carichera'.

Uso da CLI::

    uv run python -m crime_risk_analyzer.ontology_materialize
    uv run python -m crime_risk_analyzer.ontology_materialize --src in.owl --out out.ttl

Il default sorgente e' ``ontology/terminus-crime.owl`` (ghost, gitignored).
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from rdflib import Graph

from crime_risk_analyzer.ontology_namespaces import (
    TERMINUS,
    TERMINUS_PREFIX,
)

logger = logging.getLogger(__name__)

#: Sorgente/destinazione di default (entrambi gitignored, ghost). L'output
#: coincide con ``Settings.ontology_path`` (config.py) cosi' che il loader di
#: runtime trovi il TTL prodotto dal tool senza ulteriore configurazione.
DEFAULT_SRC = "ontology/terminus-crime.owl"
DEFAULT_OUT = "ontology/terminus_crime_materialized.ttl"


class MaterializeError(RuntimeError):
    """Materializzazione fallita: sorgente mancante, non-RDF/XML o grafo vuoto."""


def materialize_owl_to_ttl(src: str, out: str) -> str:
    """Converte l'OWL (RDF/XML) in ``src`` in Turtle, scrivendolo in ``out``.

    Conversione sintattica pura: parse RDF/XML -> bind del prefisso ENEA ->
    serialize Turtle. Solleva :class:`MaterializeError` se il sorgente non esiste,
    non e' RDF/XML valido o il grafo risultante e' vuoto (0 triple). Ritorna il
    path di output scritto.
    """
    if not Path(src).is_file():
        raise MaterializeError(f"File OWL sorgente non trovato: {src!r}")

    graph = Graph()
    try:
        # Il sorgente e' atteso in RDF/XML (OWL serializzato dal relatore). Un
        # input in altra sintassi (Turtle, JSON-LD, ...) fallisce qui: il
        # messaggio lo dichiara esplicitamente per non sviare la diagnosi.
        graph.parse(src, format="xml")
    except Exception as exc:  # rdflib solleva diversi tipi su RDF/XML malformato
        raise MaterializeError(
            f"Parse RDF/XML fallito (sorgente non e' OWL/RDF-XML valido): {src!r}"
        ) from exc

    if len(graph) == 0:
        # Contratto simmetrico al loader di runtime (:mod:`ontology` rifiuta un
        # grafo vuoto): un TTL senza triple non e' un'ontologia utilizzabile.
        raise MaterializeError(f"Ontologia vuota (0 triple) dopo il parse: {src!r}")

    # Prefisso leggibile ``tc`` per l'IRI ENEA reale, cosi' il Turtle prodotto
    # usa ``tc:Bank`` invece dell'IRI esteso. ``override``/``replace`` rimpiazzano
    # un eventuale binding ``tc`` preesistente — NON toccano il prefisso vuoto.
    #
    # Nota onesta (verificata empiricamente sul file reale): il namespace legacy
    # ``untitled-ontology-34`` (default xmlns del sorgente) NON compare
    # nell'output non per via di questo bind, ma semplicemente perche' nessuna
    # entita' lo usa e rdflib non emette prefissi inutilizzati. Se un'entita' lo
    # usasse davvero, rdflib lo serializzerebbe comunque (come prefisso vuoto o
    # IRI esteso) e questo bind non lo neutralizzerebbe; nasconderlo
    # falsificherebbe i dati, quindi non c'e' codice per "rimuoverlo".
    graph.namespace_manager.bind(TERMINUS_PREFIX, TERMINUS, override=True, replace=True)

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=str(out_path), format="turtle")

    logger.info("Ontologia materializzata: %s -> %s (%d triple)", src, out, len(graph))
    return str(out_path)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="crime_risk_analyzer.ontology_materialize",
        description="Converte l'ontologia OWL (RDF/XML) in Turtle.",
    )
    parser.add_argument(
        "--src",
        default=DEFAULT_SRC,
        help=f"File OWL/RDF-XML sorgente (default: {DEFAULT_SRC!r}).",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help=f"File Turtle di output (default: {DEFAULT_OUT!r}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entrypoint CLI: materializza l'OWL in TTL; ritorna 0 se ok, 1 su errore."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    try:
        out = materialize_owl_to_ttl(args.src, args.out)
    except MaterializeError as exc:
        logger.error("%s", exc)
        return 1
    logger.info("Scritto: %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
