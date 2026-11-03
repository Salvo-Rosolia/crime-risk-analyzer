"""The narrative prompts use the labels of the ACTIVE source set (#442).

A set that carries its own labels (``SourceSet.labels``) must win over the TERMINUS
JSON in the zone prompt and in the single-POI prompt; outside ``bind`` (default set)
the text stays the TERMINUS one.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from crime_risk_analyzer.rag.generation import ContextFormat, build_context_str
from crime_risk_analyzer.rag.grounding import GroundedRisk
from crime_risk_analyzer.rag.poi_context import NeighbourPoi
from crime_risk_analyzer.rag.poi_generation import build_poi_context_str
from crime_risk_analyzer.sources.context import bind, default_set
from crime_risk_analyzer.sources.model import SourceSet
from crime_risk_analyzer.sources.ontology_reader import fallback_label

_CLASS = "Bank"
_HAZARD = "Bank_robbery"
_VULN = "Area_away_from_the_town"

# TERMINUS JSON labels (default behaviour).
_TERMINUS_CLASS_IT = "Banca"
_TERMINUS_HAZARD_IT = "Rapina in banca"
_TERMINUS_VULN_IT = "Area lontana dal centro abitato"

# Labels of the custom set: deliberately different from TERMINUS.
_SET_CLASS_IT = "Istituto di credito"
_SET_HAZARD_IT = "Assalto allo sportello"
_SET_VULN_IT = "Zona poco sorvegliata"

_FORMATS: tuple[ContextFormat, ...] = ("per_poi", "per_classe")


def _custom_set(labels: dict[str, tuple[str, str]] | None) -> SourceSet:
    return dataclasses.replace(
        default_set(), id="custom-labels", kind="custom", labels=labels
    )


def _set_with_labels() -> SourceSet:
    return _custom_set(
        {
            _CLASS: (_SET_CLASS_IT, "Credit institution"),
            _HAZARD: (_SET_HAZARD_IT, "Counter assault"),
            _VULN: (_SET_VULN_IT, "Poorly monitored area"),
        }
    )


def _zone_ctx(
    *, class_name: str = _CLASS, hazard: str = _HAZARD, vuln: str = _VULN
) -> dict[str, Any]:
    return {
        "zona": "Colosseo",
        "validated_risks": [
            {
                "poi_id": "node/1",
                "poi": "Banca A",
                "terminus_class": class_name,
                "risks": [
                    {
                        "hazard": hazard,
                        "tag": "ONTOLOGIA",
                        "confidence": "verificato",
                    }
                ],
                "vulnerabilities": [{"name": vuln, "source": "x"}],
                "sparql_path": f"{class_name} → havingHazard → {hazard}",
            }
        ],
        "confidence_summary": {"verificato": 1, "da_confermare": 0},
    }


def _zone_prompt(
    fmt: ContextFormat,
    *,
    class_name: str = _CLASS,
    hazard: str = _HAZARD,
    vuln: str = _VULN,
) -> str:
    ctx = _zone_ctx(class_name=class_name, hazard=hazard, vuln=vuln)
    return build_context_str(ctx, context_format=fmt)


def _vocab_line(prompt: str) -> str:
    lines = prompt.split("\n")
    header = next(i for i, ln in enumerate(lines) if ln.startswith("VOCABOLARIO"))
    return lines[header + 1]


def _poi_prompt(*, hazard: str = _HAZARD, vuln: str = _VULN) -> str:
    return build_poi_context_str(
        citta="Roma",
        zona="Colosseo",
        poi_name="Banca A",
        poi_label_it="Banca",
        risks=[
            GroundedRisk(
                hazard=hazard,
                tag="ONTOLOGIA",
                confidence="verificato",
                source=f"{_CLASS} → havingHazard → {hazard}",
            )
        ],
        vulnerabilities=[vuln],
        sparql_path=f"{_CLASS} → havingHazard → {hazard}",
        neighbours=[NeighbourPoi(name="Liceo", label_it="Scuola", distance_m=40)],
        zone_summary="2 punti di interesse nella zona.",
    )


# --- zone narrative ------------------------------------------------------------


@pytest.mark.parametrize("fmt", _FORMATS)
def test_zone_vocabulary_uses_set_labels(fmt: ContextFormat) -> None:
    with bind(_set_with_labels()):
        vocab = _vocab_line(_zone_prompt(fmt))
    assert vocab.strip().split("; ") == [_SET_HAZARD_IT, _SET_CLASS_IT, _SET_VULN_IT]
    for terminus in (_TERMINUS_CLASS_IT, _TERMINUS_HAZARD_IT, _TERMINUS_VULN_IT):
        assert terminus not in vocab


@pytest.mark.parametrize("fmt", _FORMATS)
def test_zone_blocks_use_set_labels(fmt: ContextFormat) -> None:
    with bind(_set_with_labels()):
        prompt = _zone_prompt(fmt)
    assert f"  Classe: {_CLASS} / {_SET_CLASS_IT}" in prompt
    assert f"{_HAZARD} / {_SET_HAZARD_IT}" in prompt
    assert f"{_VULN} / {_SET_VULN_IT}" in prompt
    assert f"{_CLASS} / {_TERMINUS_CLASS_IT}" not in prompt
    assert f"{_HAZARD} / {_TERMINUS_HAZARD_IT}" not in prompt
    assert f"{_VULN} / {_TERMINUS_VULN_IT}" not in prompt


@pytest.mark.parametrize("fmt", _FORMATS)
def test_zone_outside_bind_uses_terminus_json(fmt: ContextFormat) -> None:
    prompt = _zone_prompt(fmt)
    assert _vocab_line(prompt).strip().split("; ") == [
        _TERMINUS_HAZARD_IT,
        _TERMINUS_CLASS_IT,
        _TERMINUS_VULN_IT,
    ]
    assert f"  Classe: {_CLASS} / {_TERMINUS_CLASS_IT}" in prompt
    assert _SET_CLASS_IT not in prompt


@pytest.mark.parametrize("fmt", _FORMATS)
def test_zone_set_without_labels_is_identical_to_default(fmt: ContextFormat) -> None:
    baseline = _zone_prompt(fmt)
    with bind(_custom_set(None)):
        assert _zone_prompt(fmt) == baseline


@pytest.mark.parametrize("fmt", _FORMATS)
def test_zone_after_bind_goes_back_to_default(fmt: ContextFormat) -> None:
    baseline = _zone_prompt(fmt)
    with bind(_set_with_labels()):
        assert _zone_prompt(fmt) != baseline
    assert _zone_prompt(fmt) == baseline


def test_zone_class_with_empty_it_label_falls_back_to_en() -> None:
    """Defensive contract of ``label_it``: an empty IT slot falls back on EN.

    ``sources/ontology_reader._labels`` never produces ``("", EN)`` (see the next
    test), but a hand-built set may.
    """
    labels = {
        _CLASS: ("", "Credit institution"),
        _HAZARD: (_SET_HAZARD_IT, "Counter assault"),
        _VULN: (_SET_VULN_IT, "Poorly monitored area"),
    }
    with bind(_custom_set(labels)):
        prompt = _zone_prompt("per_classe")
    assert f"  Classe: {_CLASS} / Credit institution" in prompt
    assert f"{_CLASS} / {_TERMINUS_CLASS_IT}" not in prompt


def test_zone_class_with_only_en_label_shows_fallback_name_not_en() -> None:
    """The pair ``ontology_reader._labels`` really builds for an EN-only class.

    The missing IT label is filled with ``fallback_label(name)`` (name with ``_``
    replaced by a space), NOT left empty: ``label_it`` then finds a non-empty IT slot,
    so the prompt shows that name and never the EN label.
    """
    labels = {
        _CLASS: (fallback_label(_CLASS), "Credit institution"),
        _HAZARD: (_SET_HAZARD_IT, "Counter assault"),
        _VULN: (_SET_VULN_IT, "Poorly monitored area"),
    }
    with bind(_custom_set(labels)):
        prompt = _zone_prompt("per_classe")
    assert f"  Classe: {_CLASS} / {fallback_label(_CLASS)}" in prompt
    assert "Credit institution" not in prompt


def test_zone_class_missing_from_set_falls_back_to_spaced_name() -> None:
    # Hyphen, double separator: neither the TERMINUS JSON nor ``_normalize`` yields
    # this text, so only the set fallback (``_spaced``) can have produced it.
    class_name = "Cash-point__unit"
    labels = {
        _HAZARD: (_SET_HAZARD_IT, "Counter assault"),
        _VULN: (_SET_VULN_IT, "Poorly monitored area"),
    }
    with bind(_custom_set(labels)):
        prompt = _zone_prompt("per_classe", class_name=class_name)
    assert f"  Classe: {class_name} / Cash point unit" in prompt


def test_zone_hazard_missing_from_set_falls_back_to_spaced_name() -> None:
    hazard = "bank-robbery__attempt"
    vuln = "Area-away__from_town"
    with bind(_custom_set({_CLASS: (_SET_CLASS_IT, "Credit institution")})):
        prompt = _zone_prompt("per_classe", hazard=hazard, vuln=vuln)
    assert f"{hazard} / bank robbery attempt" in prompt
    assert _vocab_line(prompt).strip().split("; ") == [
        "bank robbery attempt",
        _SET_CLASS_IT,
        "Area away from town",
    ]


# --- single-POI narrative ------------------------------------------------------


def test_poi_vocabulary_uses_set_labels() -> None:
    with bind(_set_with_labels()):
        vocab = _vocab_line(_poi_prompt())
    assert vocab.strip().split("; ") == [_SET_HAZARD_IT, _SET_VULN_IT]
    assert _TERMINUS_HAZARD_IT not in vocab
    assert _TERMINUS_VULN_IT not in vocab


def test_poi_risks_and_vulnerabilities_use_set_labels() -> None:
    with bind(_set_with_labels()):
        prompt = _poi_prompt()
    assert f"  - {_HAZARD} / {_SET_HAZARD_IT} [ONTOLOGIA]" in prompt
    assert f"Vulnerabilita': {_VULN} / {_SET_VULN_IT}" in prompt
    assert _TERMINUS_HAZARD_IT not in prompt
    assert _TERMINUS_VULN_IT not in prompt


def test_poi_class_label_is_the_one_passed_by_the_caller() -> None:
    """``poi_label_it`` arrives already resolved: the prompt does not re-derive it."""
    sentinel = "etichetta_del_chiamante"
    with bind(_set_with_labels()):
        prompt = build_poi_context_str(
            citta="Roma",
            zona="Colosseo",
            poi_name="Banca A",
            poi_label_it=sentinel,
            risks=[],
            vulnerabilities=[],
            sparql_path=None,
            neighbours=[],
            zone_summary="1 punto di interesse nella zona.",
        )
    assert f"(classe: {sentinel})" in prompt


def test_poi_outside_bind_uses_terminus_json() -> None:
    prompt = _poi_prompt()
    assert f"  - {_HAZARD} / {_TERMINUS_HAZARD_IT} [ONTOLOGIA]" in prompt
    assert f"Vulnerabilita': {_VULN} / {_TERMINUS_VULN_IT}" in prompt
    assert _SET_HAZARD_IT not in prompt
    assert _SET_VULN_IT not in prompt


def test_poi_hazard_without_set_label_falls_back_to_en_then_spaced() -> None:
    vuln = "area-away__from_town"  # neither in the TERMINUS JSON nor ``_normalize``
    labels = {_HAZARD: ("", "Counter assault")}
    with bind(_custom_set(labels)):
        prompt = _poi_prompt(vuln=vuln)
    assert f"  - {_HAZARD} / Counter assault [ONTOLOGIA]" in prompt
    assert f"Vulnerabilita': {vuln} / area away from town" in prompt


# --- current state (pinned, not desired) ---------------------------------------


def test_current_state_per_class_header_says_terminus_even_with_custom_set() -> None:
    """PINS the current behaviour, it does not endorse it.

    The per-class header (``rag/generation.py``, "POI RILEVANTI (raggruppati per
    classe TERMINUS ...") is a fixed string: it still says "TERMINUS" when the active
    set is custom. It is model-facing text and changing it alters the default prompt,
    so it is out of scope for #442. If the header becomes set-aware this test must be
    updated on purpose.
    """
    with bind(_set_with_labels()):
        prompt = _zone_prompt("per_classe")
    assert "POI RILEVANTI (raggruppati per classe TERMINUS:" in prompt
