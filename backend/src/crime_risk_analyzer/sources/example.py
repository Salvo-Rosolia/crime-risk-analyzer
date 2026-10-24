"""Set d'esempio delle fonti dinamiche (#417).

Mini-ontologia inventata (dieci classi POI, namespace ``http://example.org/mini-crime#``,
proprieta' proprie), tabelle compilate a mano e dati ISTAT ridotti a tre comuni (Roma,
Milano, Napoli) piu' la riga nazionale: i numeri sono quelli veri di
``istat/delitti.json``, cambia solo la struttura. I confini sono i nostri
(``luoghi.json``), quindi non serve un file dei confini.

I file stanno in ``backend/sources_example/`` e passano dallo stesso percorso di
lettura e controllo dei file caricati dall'utente: l'esempio e' anche un caso di
prova dei formati. Il set si costruisce una volta sola e si condivide fra le
sessioni (e' immutabile); :func:`example_set` e' lo stesso per tutti.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from crime_risk_analyzer.sources.build import (
    build_source_set,
    fallback_luoghi,
)
from crime_risk_analyzer.sources.model import SourceSet
from crime_risk_analyzer.sources.parsing import UploadedFiles, read_sources
from crime_risk_analyzer.sources.report import Problem
from crime_risk_analyzer.sources.vocabulary import OntologyVocabulary

__all__ = [
    "EXAMPLE_VOCABULARY",
    "example_bundle",
    "example_files",
    "example_set",
    "example_warnings",
]

#: ``backend/sources_example``: questo file sta in ``backend/src/<package>/sources``.
_CARTELLA = Path(__file__).resolve().parents[3] / "sources_example"

EXAMPLE_VOCABULARY = OntologyVocabulary(
    namespace="http://example.org/mini-crime#",
    hazard="hasRisk",
    critical_event="hasEvent",
    performer="hasActor",
    vulnerability=("isFragileTo", "hasWeakness"),
)


def example_files() -> UploadedFiles:
    """Byte dei file d'esempio, come se li avesse caricati l'utente."""
    return UploadedFiles(
        ontology=(_CARTELLA / "ontology.ttl").read_bytes(),
        ontology_name="ontology.ttl",
        osm_table=(_CARTELLA / "osm_table.csv").read_bytes(),
        data=(_CARTELLA / "data.csv").read_bytes(),
        hazard_table=(_CARTELLA / "hazard_table.csv").read_bytes(),
    )


@lru_cache(maxsize=1)
def example_bundle() -> tuple[SourceSet, tuple[Problem, ...]]:
    """Set d'esempio e avvisi della sua lettura, costruiti una volta sola.

    Raises:
        SourceValidationError: i file d'esempio non sono validi (un test lo vieta).
    """
    parsed, report = read_sources(
        example_files(), EXAMPLE_VOCABULARY, fallback_luoghi=fallback_luoghi()
    )
    return build_source_set(parsed, kind="example"), tuple(report.warnings)


def example_set() -> SourceSet:
    """Il set d'esempio (``kind="example"``)."""
    return example_bundle()[0]


def example_warnings() -> tuple[Problem, ...]:
    """Avvisi della lettura dei file d'esempio (per esempio le etichette mancanti)."""
    return example_bundle()[1]
