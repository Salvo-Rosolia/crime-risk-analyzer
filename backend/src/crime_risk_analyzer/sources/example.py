"""Example set of the dynamic sources (#417).

Invented mini-ontology (ten POI classes, namespace
``http://example.org/mini-crime#``, own properties), hand-compiled tables and ISTAT
data reduced to three municipalities (Roma, Milano, Napoli) plus the national row: the
numbers are the real ones from ``istat/delitti.json``, only the structure changes. The
boundaries are our own (``luoghi.json``), so no boundaries file is needed.

The files live in ``backend/sources_example/`` and go through the same path of
reading and checking as the files uploaded by the user: the example is also a test
case of the formats. The set is built only once and shared between the
sessions (it is immutable); :func:`example_set` is the same for everyone.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from crime_risk_analyzer.sources.build import (
    build_source_set,
    fallback_places,
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

#: ``backend/sources_example``: this file sits in ``backend/src/<package>/sources``.
_FOLDER = Path(__file__).resolve().parents[3] / "sources_example"

EXAMPLE_VOCABULARY = OntologyVocabulary(
    namespace="http://example.org/mini-crime#",
    hazard="hasRisk",
    critical_event="hasEvent",
    performer="hasActor",
    vulnerability=("isFragileTo", "hasWeakness"),
)


def example_files() -> UploadedFiles:
    """Bytes of the example files, as if the user had uploaded them."""
    return UploadedFiles(
        ontology=(_FOLDER / "ontology.ttl").read_bytes(),
        ontology_name="ontology.ttl",
        osm_table=(_FOLDER / "osm_table.csv").read_bytes(),
        data=(_FOLDER / "data.csv").read_bytes(),
        hazard_table=(_FOLDER / "hazard_table.csv").read_bytes(),
    )


@lru_cache(maxsize=1)
def example_bundle() -> tuple[SourceSet, tuple[Problem, ...]]:
    """Example set and warnings of its reading, built only once.

    Raises:
        SourceValidationError: the example files are not valid (a test forbids it).
    """
    parsed, report = read_sources(
        example_files(), EXAMPLE_VOCABULARY, fallback_places=fallback_places()
    )
    return build_source_set(parsed, kind="example"), tuple(report.warnings)


def example_set() -> SourceSet:
    """The example set (``kind="example"``)."""
    return example_bundle()[0]


def example_warnings() -> tuple[Problem, ...]:
    """Warnings from reading the example files (for example the missing labels)."""
    return example_bundle()[1]
