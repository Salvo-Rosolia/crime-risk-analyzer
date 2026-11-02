"""Single source of truth for the IRI/namespace of the TERMINUS Crime ontology (#75).

This module consolidates in a single place the **real** IRI of the ENEA ontology
(Minardi et al.), shared between the offline materialisation tool
(:mod:`~crime_risk_analyzer.ontology_materialize`, #74), the runtime loader
(:mod:`~crime_risk_analyzer.ontology`) and the SPARQL executor (#76). Having
a single constant avoids drift and the accidental use of misleading IRIs.

Beware of TWO IRIs NOT to use:

* the default ``xmlns`` ``untitled-ontology-34`` declared in the source OWL file
  is legacy/misleading (a Protege artefact), not the identity of the ontology;
* the placeholder IRI ``http://example.org/terminus-crime#`` used in the past in
  fixtures and spec drafts is NOT the real ontology.

The canonical IRI is :data:`TERMINUS_IRI`. :data:`TERMINUS` is the corresponding
:class:`rdflib.Namespace` (with a trailing ``#``) so that #76 can
write ``TERMINUS.havingHazard`` / ``TERMINUS["havingHazard"]`` and directly get
a :class:`~rdflib.URIRef` for ``initBindings`` in the parametrised
queries.
"""

from __future__ import annotations

from rdflib import Namespace

#: Real IRI of the TERMINUS Crime ontology (ENEA, Minardi et al.), **without** the
#: trailing ``#``. NOT the default xmlns ``untitled-ontology-34`` of the OWL file
#: (legacy/misleading) nor the ``example.org/terminus-crime`` placeholder.
TERMINUS_IRI = "http://www.enea-terin-sen-apic.it/TERMINUS-crime-v01"

#: Readable prefix bound to ``TERMINUS_IRI#`` (e.g. ``tc:Bank``) in the
#: materialised Turtle and in the queries.
TERMINUS_PREFIX = "tc"

#: :class:`rdflib.Namespace` on ``{TERMINUS_IRI}#``: ``TERMINUS.havingHazard`` or
#: ``TERMINUS["havingHazard"]`` resolve to ``URIRef`` ready for SPARQL (#76).
TERMINUS = Namespace(f"{TERMINUS_IRI}#")
