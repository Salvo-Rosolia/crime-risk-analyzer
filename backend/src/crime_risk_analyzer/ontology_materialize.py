"""Offline materialisation of the OWL ontology (RDF/XML) -> Turtle (#74).

PURE syntax conversion with ``rdflib``: parse of the OWL file supplied by the
supervisor, bind of a readable prefix for the real ENEA IRI, serialisation to
Turtle. **No reasoner, no owlready2/HermiT, no Java** (spec-root
§Stack: zero-Java at runtime; here it is anyway only a syntactic conversion).

The source OWL file and the produced TTL are both *ghost*: gitignored, they do
not go to GitHub (licence/reuse to be clarified — see ``.gitignore``). This
module is the offline tool that an operator runs once to produce the
``.ttl`` that the runtime loader (:mod:`~crime_risk_analyzer.ontology`)
will load.

CLI usage::

    uv run python -m crime_risk_analyzer.ontology_materialize
    uv run python -m crime_risk_analyzer.ontology_materialize --src in.owl --out out.ttl

The default source is ``ontology/terminus-crime.owl`` (ghost, gitignored).
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

#: Default source/destination (both gitignored, ghost). The output
#: coincides with ``Settings.ontology_path`` (config.py) so that the runtime
#: loader finds the TTL produced by the tool without further configuration.
DEFAULT_SRC = "ontology/terminus-crime.owl"
DEFAULT_OUT = "ontology/terminus_crime_materialized.ttl"


class MaterializeError(RuntimeError):
    """Materialisation failed: missing source, non-RDF/XML or empty graph."""


def materialize_owl_to_ttl(src: str, out: str) -> str:
    """Converts the OWL (RDF/XML) in ``src`` to Turtle, writing it to ``out``.

    Pure syntactic conversion: parse RDF/XML -> bind the ENEA prefix ->
    serialize Turtle. Raises :class:`MaterializeError` if the source does not
    exist, is not valid RDF/XML or the resulting graph is empty (0 triples). Returns
    the output path written.
    """
    if not Path(src).is_file():
        raise MaterializeError(f"File OWL sorgente non trovato: {src!r}")

    graph = Graph()
    try:
        # The source is expected in RDF/XML (OWL serialised by the supervisor). An
        # input in another syntax (Turtle, JSON-LD, ...) fails here: the
        # message declares it explicitly so as not to mislead the diagnosis.
        graph.parse(src, format="xml")
    except Exception as exc:  # rdflib raises several types on malformed RDF/XML
        raise MaterializeError(
            f"Parse RDF/XML fallito (sorgente non e' OWL/RDF-XML valido): {src!r}"
        ) from exc

    if len(graph) == 0:
        # Contract symmetric to the runtime loader (:mod:`ontology` rejects an
        # empty graph): a TTL without triples is not a usable ontology.
        raise MaterializeError(f"Ontologia vuota (0 triple) dopo il parse: {src!r}")

    # Readable ``tc`` prefix for the real ENEA IRI, so the produced Turtle
    # uses ``tc:Bank`` instead of the expanded IRI. ``override``/``replace``
    # replace any pre-existing ``tc`` binding — they do NOT touch the empty prefix.
    #
    # Honest note (empirically verified on the real file): the legacy namespace
    # ``untitled-ontology-34`` (default xmlns of the source) does NOT appear in
    # the output not because of this bind, but simply because no
    # entity uses it and rdflib does not emit unused prefixes. If an entity
    # really used it, rdflib would serialise it anyway (as an empty prefix or
    # expanded IRI) and this bind would not neutralise it; hiding it
    # would falsify the data, so there is no code to "remove it".
    graph.namespace_manager.bind(TERMINUS_PREFIX, TERMINUS, override=True, replace=True)

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=str(out_path), format="turtle")

    logger.info("Ontology materialised: %s -> %s (%d triples)", src, out, len(graph))
    return str(out_path)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="crime_risk_analyzer.ontology_materialize",
        description="Converts the OWL ontology (RDF/XML) to Turtle.",
    )
    parser.add_argument(
        "--src",
        default=DEFAULT_SRC,
        help=f"Source OWL/RDF-XML file (default: {DEFAULT_SRC!r}).",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help=f"Output Turtle file (default: {DEFAULT_OUT!r}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: materialises the OWL into TTL; returns 0 if ok, 1 on error."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    try:
        out = materialize_owl_to_ttl(args.src, args.out)
    except MaterializeError as exc:
        logger.error("%s", exc)
        return 1
    logger.info("Written: %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
