"""Lettura e controllo dell'ontologia caricata (#415).

Formati: Turtle (``.ttl``) e OWL/RDF-XML (``.owl``, ``.rdf``, ``.xml``) tramite
``rdflib``. Il file deve bastare a se stesso: ``owl:imports`` e' rifiutato (e
``rdflib`` non lo segue comunque), e in RDF/XML sono rifiutate le entita'
esterne (``<!ENTITY ... SYSTEM|PUBLIC``), che farebbero partire una richiesta di
rete. Le entita' interne (``<!ENTITY owl "http://...">``, quelle che scrive
Protege) restano ammesse.

Dal grafo si ricavano: le classi del namespace, le loro etichette IT/EN con il
ripiego sul nome (``_`` -> spazio) e il conteggio delle restrizioni sulle
proprieta' di rischio del vocabolario, che se e' zero quasi certamente vuol dire
namespace o nomi di proprieta' sbagliati.
"""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass
from pathlib import PurePath

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from crime_risk_analyzer.sources.limits import controlla_testo
from crime_risk_analyzer.sources.report import ValidationReport
from crime_risk_analyzer.sources.vocabulary import OntologyVocabulary

__all__ = ["OntologyReading", "fallback_label", "read_ontology"]

_FILE = "ontology"
_FORMATI = {".ttl": "turtle", ".owl": "xml", ".rdf": "xml", ".xml": "xml"}
_ENTITA_ESTERNA = re.compile(rb"<!ENTITY\s+(?:%\s+)?\S+\s+(?:SYSTEM|PUBLIC)\b")
_MAX_ESEMPI = 10
#: BOM UTF-32 e UTF-16 (i primi, piu' lunghi, prima).
_BOM = (
    codecs.BOM_UTF32_LE,
    codecs.BOM_UTF32_BE,
    codecs.BOM_UTF16_LE,
    codecs.BOM_UTF16_BE,
)
#: Una dichiarazione ``<!ENTITY nome "valore">`` (o con apici singoli) interna.
_ENTITA_INTERNA = re.compile(
    rb"""<!ENTITY\s+(?:%\s+)?[^\s>]+\s+(?:"([^"]*)"|'([^']*)')\s*>"""
)
_MAX_ENTITA = 100
_MAX_BYTES_ENTITA = 10_000


@dataclass(frozen=True)
class OntologyReading:
    """Ontologia letta: grafo, nomi delle classi del namespace ed etichette."""

    graph: Graph
    #: Nomi locali (senza namespace) di tutte le classi del namespace.
    classes: frozenset[str]
    #: Nome della classe -> (etichetta IT, etichetta EN), col ripiego sul nome.
    labels: dict[str, tuple[str, str]]


def fallback_label(class_name: str) -> str:
    """Etichetta di ripiego: il nome della classe con ``_`` sostituito da spazio."""
    return class_name.replace("_", " ")


def read_ontology(
    content: bytes,
    name: str,
    vocabulary: OntologyVocabulary,
    report: ValidationReport,
) -> OntologyReading | None:
    """Legge e controlla l'ontologia; ``None`` se non si puo' proseguire.

    Con un grafo letto restituisce sempre il risultato anche in presenza di errori
    (``owl:imports``, testi non ammessi, nessuna restrizione): il chiamante
    continua i controlli incrociati sulle tabelle e riporta tutto in una volta.
    """
    motivi = vocabulary.problems()
    for motivo in motivi:
        report.error("vocabolario_non_valido", _FILE, motivo)
    if motivi:
        return None

    formato = _FORMATI.get(PurePath(name).suffix.lower())
    if formato is None:
        report.error(
            "ontologia_formato_non_supportato",
            _FILE,
            f"estensione di {name!r} non supportata: usa .ttl, .owl, .rdf o .xml",
        )
        return None
    if formato == "xml" and (b"\x00" in content or content.startswith(_BOM)):
        report.error(
            "codifica_non_ammessa",
            _FILE,
            "l'ontologia XML deve essere in UTF-8 (o ASCII): UTF-16 e UTF-32 "
            "non sono ammessi",
        )
        return None
    if formato == "xml" and _ENTITA_ESTERNA.search(content):
        report.error(
            "entita_esterna_non_ammessa",
            _FILE,
            "il file dichiara un'entita' XML esterna (SYSTEM o PUBLIC): "
            "non e' ammessa, il file deve essere autosufficiente",
        )
        return None

    if formato == "xml" and not _entita_ammesse(content, report):
        return None

    graph = Graph()
    try:
        graph.parse(data=content, format=formato)
    except Exception as exc:  # rdflib solleva tipi diversi su file malformati
        report.error(
            "ontologia_illeggibile",
            _FILE,
            f"ontologia non leggibile come {formato}: {str(exc)[:200]}",
        )
        return None
    if len(graph) == 0:
        report.error("ontologia_vuota", _FILE, "l'ontologia non contiene triple")
        return None

    _controlla_imports(graph, report)
    nomi = _nomi_classi(graph, vocabulary.namespace)
    for nome in sorted(nomi):
        motivo = controlla_testo(nome)
        if motivo is not None:
            report.error(
                "testo_non_ammesso",
                _FILE,
                f"nome di classe {nome[:40]!r}: {motivo}",
            )
    etichette = _etichette(graph, vocabulary.namespace, nomi, report)
    if _conta_restrizioni(graph, vocabulary) == 0:
        report.error(
            "ontologia_senza_restrizioni",
            _FILE,
            "nessuna restrizione OWL sulle proprieta' di rischio "
            f"({', '.join(vocabulary.properties)}) nel namespace "
            f"{vocabulary.namespace!r}: controlla namespace e nomi delle proprieta'",
        )
    return OntologyReading(graph=graph, classes=nomi, labels=etichette)


def _entita_ammesse(content: bytes, report: ValidationReport) -> bool:
    """Ammette solo poche entita' interne semplici (quelle che scrive Protege).

    Un valore che contiene ``&`` puo' richiamare altre entita': annidandole si
    costruisce un'espansione esponenziale (billion laughs) che blocca la CPU.
    """
    dichiarate = content.count(b"<!ENTITY")
    trovate = list(_ENTITA_INTERNA.finditer(content))
    if len(trovate) != dichiarate:
        report.error(
            "entita_xml_non_ammessa",
            _FILE,
            "una dichiarazione <!ENTITY ...> non ha la forma semplice "
            '<!ENTITY nome "valore">: non e\' ammessa',
        )
        return False
    if dichiarate > _MAX_ENTITA:
        report.error(
            "entita_xml_troppe",
            _FILE,
            f"il file dichiara {dichiarate} entita' XML, il massimo e' {_MAX_ENTITA}",
        )
        return False
    valori = [m.group(1) if m.group(1) is not None else m.group(2) for m in trovate]
    if sum(len(v) for v in valori) > _MAX_BYTES_ENTITA:
        report.error(
            "entita_xml_troppe",
            _FILE,
            f"le entita' XML superano {_MAX_BYTES_ENTITA} byte in totale",
        )
        return False
    if any(b"&" in v for v in valori):
        report.error(
            "entita_xml_annidata",
            _FILE,
            "un'entita' XML ne richiama altre (valore con &): non e' ammesso",
        )
        return False
    return True


def _controlla_imports(graph: Graph, report: ValidationReport) -> None:
    importati = sorted({str(o) for o in graph.objects(None, OWL.imports)})
    if importati:
        report.error(
            "owl_imports_non_ammessi",
            _FILE,
            "l'ontologia usa owl:imports, che non viene seguito: il file deve "
            "essere autosufficiente. Import trovati: "
            + ", ".join(importati[:_MAX_ESEMPI]),
        )


def _locale(uri: object, namespace: str) -> str | None:
    if isinstance(uri, URIRef) and str(uri).startswith(namespace):
        resto = str(uri)[len(namespace) :]
        return resto or None
    return None


def _nomi_classi(graph: Graph, namespace: str) -> frozenset[str]:
    """Classi del namespace: tipizzate come classe, o usate in subClassOf/filler."""
    trovati: set[str | None] = set()
    for tipo in (OWL.Class, RDFS.Class):
        trovati.update(_locale(s, namespace) for s in graph.subjects(RDF.type, tipo))
    for s, o in graph.subject_objects(RDFS.subClassOf):
        trovati.add(_locale(s, namespace))
        trovati.add(_locale(o, namespace))
    trovati.update(
        _locale(o, namespace) for o in graph.objects(None, OWL.someValuesFrom)
    )
    return frozenset(n for n in trovati if n is not None)


def _lingua(letterale: Literal) -> str:
    return (letterale.language or "").split("-")[0].lower()


def _etichette(
    graph: Graph, namespace: str, nomi: frozenset[str], report: ValidationReport
) -> dict[str, tuple[str, str]]:
    risultato: dict[str, tuple[str, str]] = {}
    senza: dict[str, list[str]] = {"it": [], "en": []}
    for nome in sorted(nomi):
        per_lingua: dict[str, list[str]] = {}
        for lett in graph.objects(URIRef(namespace + nome), RDFS.label):
            if not isinstance(lett, Literal):
                continue
            testo = str(lett)
            motivo = controlla_testo(testo)
            if motivo is not None:
                report.error(
                    "testo_non_ammesso",
                    _FILE,
                    f"etichetta della classe {nome[:40]!r} ({testo[:40]!r}): {motivo}",
                )
                continue
            per_lingua.setdefault(_lingua(lett), []).append(testo)
        valori: list[str] = []
        for lingua in ("it", "en"):
            candidati = per_lingua.get(lingua)
            if candidati:
                valori.append(min(candidati))
            else:
                senza[lingua].append(nome)
                valori.append(fallback_label(nome))
        risultato[nome] = (valori[0], valori[1])
    descrizione = {"it": "italiana", "en": "inglese"}
    for lingua, classi in senza.items():
        if classi:
            esempi = ", ".join(classi[:_MAX_ESEMPI])
            altre = (
                ""
                if len(classi) <= _MAX_ESEMPI
                else f" e altre {len(classi) - _MAX_ESEMPI}"
            )
            report.warning(
                "etichetta_mancante",
                _FILE,
                f"{len(classi)} classi senza etichetta {descrizione[lingua]} "
                f"(si usa il nome della classe): {esempi}{altre}",
            )
    return risultato


def _conta_restrizioni(graph: Graph, vocabulary: OntologyVocabulary) -> int:
    proprieta = {URIRef(vocabulary.namespace + n) for n in vocabulary.properties}
    conteggio = 0
    for restrizione in graph.subjects(RDF.type, OWL.Restriction):
        if not proprieta.intersection(graph.objects(restrizione, OWL.onProperty)):
            continue
        if any(
            isinstance(f, URIRef)
            for f in graph.objects(restrizione, OWL.someValuesFrom)
        ):
            conteggio += 1
    return conteggio
