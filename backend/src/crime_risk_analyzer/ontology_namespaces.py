"""Single source of truth per IRI/namespace dell'ontologia TERMINUS Crime (#75).

Questo modulo consolida in un unico posto l'IRI **reale** dell'ontologia ENEA
(Minardi et al.), condiviso tra il tool di materializzazione offline
(:mod:`~crime_risk_analyzer.ontology_materialize`, #74), il loader di runtime
(:mod:`~crime_risk_analyzer.ontology`) e l'executor SPARQL (#76). Avere
un'unica costante evita il drift e l'uso accidentale di IRI fuorvianti.

Attenzione a DUE IRI da NON usare:

* il default ``xmlns`` ``untitled-ontology-34`` dichiarato nel file OWL sorgente
  e' legacy/fuorviante (artefatto di Protege), non l'identita' dell'ontologia;
* l'IRI placeholder ``http://example.org/terminus-crime#`` usato in passato nelle
  fixture e nelle bozze di spec NON e' l'ontologia reale.

L'IRI canonico e' :data:`TERMINUS_IRI`. :data:`TERMINUS` e' il
:class:`rdflib.Namespace` corrispondente (con ``#`` finale) cosi' che #76 possa
scrivere ``TERMINUS.havingHazard`` / ``TERMINUS["havingHazard"]`` e ottenere
direttamente un :class:`~rdflib.URIRef` per ``initBindings`` nelle query
parametrizzate.
"""

from __future__ import annotations

from rdflib import Namespace

#: IRI reale dell'ontologia TERMINUS Crime (ENEA, Minardi et al.), **senza** il
#: ``#`` finale. NON il default xmlns ``untitled-ontology-34`` del file OWL
#: (legacy/fuorviante) ne' il placeholder ``example.org/terminus-crime``.
TERMINUS_IRI = "http://www.enea-terin-sen-apic.it/TERMINUS-crime-v01"

#: Prefisso leggibile legato a ``TERMINUS_IRI#`` (es. ``tc:Bank``) nel Turtle
#: materializzato e nelle query.
TERMINUS_PREFIX = "tc"

#: :class:`rdflib.Namespace` su ``{TERMINUS_IRI}#``: ``TERMINUS.havingHazard`` o
#: ``TERMINUS["havingHazard"]`` risolvono a ``URIRef`` pronti per SPARQL (#76).
TERMINUS = Namespace(f"{TERMINUS_IRI}#")
