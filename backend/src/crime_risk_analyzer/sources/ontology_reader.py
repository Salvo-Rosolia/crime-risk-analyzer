"""Reading and checking of the uploaded ontology (#415).

Formats: Turtle (``.ttl``) and OWL/RDF-XML (``.owl``, ``.rdf``, ``.xml``) via
``rdflib``. The file must be self-sufficient: ``owl:imports`` is rejected (and
``rdflib`` does not follow it anyway), and in RDF/XML the external entities
(``<!ENTITY ... SYSTEM|PUBLIC``) are rejected, which would trigger a network
request. The internal entities (``<!ENTITY owl "http://...">``, the ones Protege
writes) remain allowed.

From the graph are derived: the classes of the namespace, their IT/EN labels with
the fallback on the name (``_`` -> space) and the count of the restrictions on the
risk properties of the vocabulary, which if zero almost certainly means a wrong
namespace or property names.
"""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass
from pathlib import PurePath

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from crime_risk_analyzer.sources.limits import check_text
from crime_risk_analyzer.sources.report import ValidationReport
from crime_risk_analyzer.sources.vocabulary import OntologyVocabulary

__all__ = ["OntologyReading", "fallback_label", "read_ontology"]

_FILE = "ontology"
_FORMATS = {".ttl": "turtle", ".owl": "xml", ".rdf": "xml", ".xml": "xml"}
_EXTERNAL_ENTITY = re.compile(rb"<!ENTITY\s+(?:%\s+)?\S+\s+(?:SYSTEM|PUBLIC)\b")
_MAX_EXAMPLES = 10
#: UTF-32 and UTF-16 BOMs (the longer ones first).
_BOM = (
    codecs.BOM_UTF32_LE,
    codecs.BOM_UTF32_BE,
    codecs.BOM_UTF16_LE,
    codecs.BOM_UTF16_BE,
)
#: An internal declaration ``<!ENTITY name "value">`` (or with single quotes).
_INTERNAL_ENTITY = re.compile(
    rb"""<!ENTITY\s+(?:%\s+)?[^\s>]+\s+(?:"([^"]*)"|'([^']*)')\s*>"""
)
_MAX_ENTITIES = 100
_MAX_ENTITY_BYTES = 10_000


@dataclass(frozen=True)
class OntologyReading:
    """Ontology read: graph, names of the namespace classes and labels."""

    graph: Graph
    #: Local names (without namespace) of all the classes of the namespace.
    classes: frozenset[str]
    #: Class name -> (IT label, EN label), with fallback on the name.
    labels: dict[str, tuple[str, str]]


def fallback_label(class_name: str) -> str:
    """Fallback label: the class name with ``_`` replaced by a space."""
    return class_name.replace("_", " ")


def read_ontology(
    content: bytes,
    name: str,
    vocabulary: OntologyVocabulary,
    report: ValidationReport,
) -> OntologyReading | None:
    """Reads and checks the ontology; ``None`` if one cannot proceed.

    With a graph read it always returns the result even in the presence of errors
    (``owl:imports``, texts not allowed, no restriction): the caller
    continues the cross checks on the tables and reports everything at once.
    """
    reasons = vocabulary.problems()
    for reason in reasons:
        report.error("vocabolario_non_valido", _FILE, reason)
    if reasons:
        return None

    fmt = _FORMATS.get(PurePath(name).suffix.lower())
    if fmt is None:
        report.error(
            "ontologia_formato_non_supportato",
            _FILE,
            f"estensione di {name!r} non supportata: usa .ttl, .owl, .rdf o .xml",
        )
        return None
    if fmt == "xml" and (b"\x00" in content or content.startswith(_BOM)):
        report.error(
            "codifica_non_ammessa",
            _FILE,
            "l'ontologia XML deve essere in UTF-8 (o ASCII): UTF-16 e UTF-32 "
            "non sono ammessi",
        )
        return None
    if fmt == "xml" and _EXTERNAL_ENTITY.search(content):
        report.error(
            "entita_esterna_non_ammessa",
            _FILE,
            "il file dichiara un'entita' XML esterna (SYSTEM o PUBLIC): "
            "non e' ammessa, il file deve essere autosufficiente",
        )
        return None

    if fmt == "xml" and not _allowed_entities(content, report):
        return None

    graph = Graph()
    try:
        graph.parse(data=content, format=fmt)
    except Exception as exc:  # rdflib raises different types on malformed files
        report.error(
            "ontologia_illeggibile",
            _FILE,
            f"ontologia non leggibile come {fmt}: {_readable_cause(exc)}",
        )
        return None
    if len(graph) == 0:
        report.error("ontologia_vuota", _FILE, "l'ontologia non contiene triple")
        return None

    _check_imports(graph, report)
    class_names = _class_names(graph, vocabulary.namespace)
    for class_name in sorted(class_names):
        reason = check_text(class_name)
        if reason is not None:
            report.error(
                "testo_non_ammesso",
                _FILE,
                f"nome di classe {class_name[:40]!r}: {reason}",
            )
    class_labels = _labels(graph, vocabulary.namespace, class_names, report)
    if _count_restrictions(graph, vocabulary) == 0:
        report.error(
            "ontologia_senza_restrizioni",
            _FILE,
            "nessuna restrizione OWL sulle proprieta' di rischio "
            f"({', '.join(vocabulary.properties)}) nel namespace "
            f"{vocabulary.namespace!r}: controlla namespace e nomi delle proprieta'",
        )
    return OntologyReading(graph=graph, classes=class_names, labels=class_labels)


_RDFLIB_LINE = re.compile(r"^at line (\d+) of ")
_CONTENT_CUT = " at ^"


def _readable_cause(exc: Exception) -> str:
    """Line and cause of a parse error, without the file fragment (#439).

    The rdflib message for Turtle is ``at line N of <>:`` followed by the
    cause, then `` at ^ in:`` and a piece of the file: only ``riga N`` and the
    cause are kept, cutting from `` at ^`` onwards. For the other errors (XML, encoding)
    the first non-empty line applies.
    """
    lines = [r.strip() for r in str(exc).splitlines() if r.strip()]
    line_no: str | None = None
    if lines and (m := _RDFLIB_LINE.match(lines[0])):
        line_no = m.group(1)
        lines = lines[1:]
    cause = lines[0].split(_CONTENT_CUT)[0].strip()[:200] if lines else ""
    if not cause:
        cause = type(exc).__name__
    return f"riga {line_no}: {cause}" if line_no else cause


def _allowed_entities(content: bytes, report: ValidationReport) -> bool:
    """Allows only a few simple internal entities (the ones Protege writes).

    A value that contains ``&`` can call other entities: nesting them
    builds an exponential expansion (billion laughs) that blocks the CPU.
    """
    declared = content.count(b"<!ENTITY")
    found = list(_INTERNAL_ENTITY.finditer(content))
    if len(found) != declared:
        report.error(
            "entita_xml_non_ammessa",
            _FILE,
            "una dichiarazione <!ENTITY ...> non ha la forma semplice "
            '<!ENTITY nome "valore">: non e\' ammessa',
        )
        return False
    if declared > _MAX_ENTITIES:
        report.error(
            "entita_xml_troppe",
            _FILE,
            f"il file dichiara {declared} entita' XML, il massimo e' {_MAX_ENTITIES}",
        )
        return False
    values = [m.group(1) if m.group(1) is not None else m.group(2) for m in found]
    if sum(len(v) for v in values) > _MAX_ENTITY_BYTES:
        report.error(
            "entita_xml_troppe",
            _FILE,
            f"le entita' XML superano {_MAX_ENTITY_BYTES} byte in totale",
        )
        return False
    if any(b"&" in v for v in values):
        report.error(
            "entita_xml_annidata",
            _FILE,
            "un'entita' XML ne richiama altre (valore con &): non e' ammesso",
        )
        return False
    return True


def _check_imports(graph: Graph, report: ValidationReport) -> None:
    imported = sorted({str(o) for o in graph.objects(None, OWL.imports)})
    if imported:
        report.error(
            "owl_imports_non_ammessi",
            _FILE,
            "l'ontologia usa owl:imports, che non viene seguito: il file deve "
            "essere autosufficiente. Import trovati: "
            + ", ".join(imported[:_MAX_EXAMPLES]),
        )


def _local_part(uri: object, namespace: str) -> str | None:
    if isinstance(uri, URIRef) and str(uri).startswith(namespace):
        rest = str(uri)[len(namespace) :]
        return rest or None
    return None


def _class_names(graph: Graph, namespace: str) -> frozenset[str]:
    """Classes of the namespace: typed as class, or used in subClassOf/filler."""
    found_names: set[str | None] = set()
    for rdf_type in (OWL.Class, RDFS.Class):
        found_names.update(
            _local_part(s, namespace) for s in graph.subjects(RDF.type, rdf_type)
        )
    for s, o in graph.subject_objects(RDFS.subClassOf):
        found_names.add(_local_part(s, namespace))
        found_names.add(_local_part(o, namespace))
    found_names.update(
        _local_part(o, namespace) for o in graph.objects(None, OWL.someValuesFrom)
    )
    return frozenset(n for n in found_names if n is not None)


def _language(literal: Literal) -> str:
    return (literal.language or "").split("-")[0].lower()


def _labels(
    graph: Graph, namespace: str, class_names: frozenset[str], report: ValidationReport
) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    missing_labels: dict[str, list[str]] = {"it": [], "en": []}
    for class_name in sorted(class_names):
        per_language: dict[str, list[str]] = {}
        for lit in graph.objects(URIRef(namespace + class_name), RDFS.label):
            if not isinstance(lit, Literal):
                continue
            text = str(lit)
            reason = check_text(text)
            if reason is not None:
                report.error(
                    "testo_non_ammesso",
                    _FILE,
                    f"etichetta della classe {class_name[:40]!r} "
                    f"({text[:40]!r}): {reason}",
                )
                continue
            per_language.setdefault(_language(lit), []).append(text)
        values: list[str] = []
        for language in ("it", "en"):
            candidates = per_language.get(language)
            if candidates:
                values.append(min(candidates))
            else:
                missing_labels[language].append(class_name)
                values.append(fallback_label(class_name))
        result[class_name] = (values[0], values[1])
    language_adjective = {"it": "italiana", "en": "inglese"}
    for language, classes in missing_labels.items():
        if classes:
            examples = ", ".join(classes[:_MAX_EXAMPLES])
            others = (
                ""
                if len(classes) <= _MAX_EXAMPLES
                else f" e altre {len(classes) - _MAX_EXAMPLES}"
            )
            report.warning(
                "etichetta_mancante",
                _FILE,
                f"{len(classes)} classi senza etichetta {language_adjective[language]} "
                f"(si usa il nome della classe): {examples}{others}",
            )
    return result


def _count_restrictions(graph: Graph, vocabulary: OntologyVocabulary) -> int:
    properties = {URIRef(vocabulary.namespace + n) for n in vocabulary.properties}
    count = 0
    for restriction in graph.subjects(RDF.type, OWL.Restriction):
        if not properties.intersection(graph.objects(restriction, OWL.onProperty)):
            continue
        if any(
            isinstance(f, URIRef)
            for f in graph.objects(restriction, OWL.someValuesFrom)
        ):
            count += 1
    return count
