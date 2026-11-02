"""Tests of the versioned ablation experiment configs (#32).

The configs live in ``backend/experiments/`` (versioned in the repo for
reproducibility). These tests lock the contract of the deliverable: the two
arms (analyze/baseline) exist, parse against ``ExperimentConfig`` and are
anchored to the SAME 4 zones of the C1 validation roster (#31).
"""

from __future__ import annotations

from pathlib import Path

from crime_risk_analyzer.eval.city_agnostic import ROSTER
from crime_risk_analyzer.eval.cli import load_config

#: backend/experiments (test_file -> eval -> tests -> backend).
EXPERIMENTS_DIR = Path(__file__).resolve().parents[2] / "experiments"


def _zones(name: str) -> list[tuple[str, str]]:
    cfg = load_config(EXPERIMENTS_DIR / f"{name}.json")
    return [(c.citta, c.zona) for c in cfg.cases]


def test_ablation_configs_parse_with_expected_names() -> None:
    for name in ("ablation-analyze", "ablation-baseline"):
        cfg = load_config(EXPERIMENTS_DIR / f"{name}.json")
        assert cfg.name == name


def test_ablation_configs_have_the_two_arms() -> None:
    """Two configs: a FULL arm (analyze+LLM), one BASELINE (without LLM)."""
    assert load_config(EXPERIMENTS_DIR / "ablation-analyze.json").mode == "analyze"
    assert load_config(EXPERIMENTS_DIR / "ablation-baseline.json").mode == "baseline"


def test_ablation_arms_share_the_same_four_zones() -> None:
    """Iso-input comparison: the two arms point to the SAME 4 (citta, zona) pairs."""
    zones_analyze = _zones("ablation-analyze")
    zones_baseline = _zones("ablation-baseline")
    assert len(zones_analyze) == 4
    assert zones_analyze == zones_baseline


def test_no_ontology_arm_config_exists_with_the_llm() -> None:
    """#236: the arm that isolates the ontology runs with the LLM, not without.

    ``model`` is groq because it is the provider of the real runs (Claude is
    paid and stays deferred): the arm must be compared with
    ``ablation-analyze-groq``, i.e. the SAME model.
    """
    cfg = load_config(EXPERIMENTS_DIR / "ablation-no-ontology-groq.json")
    assert cfg.name == "ablation-no-ontology-groq"
    assert cfg.mode == "no_ontology_prompt"
    assert cfg.model == "groq"


def test_no_ontology_arm_shares_the_zones_of_the_complete_arm() -> None:
    """Iso-input comparison: the same 4 zones as the full arm with Groq.

    Different zones would make the C3 comparison unreadable before even
    looking at the numbers: the POI snapshots are keyed by (citta, zona).
    """
    assert _zones("ablation-no-ontology-groq") == _zones("ablation-analyze-groq")


def test_ablation_zones_anchored_to_c1_roster() -> None:
    """The 4 zones are anchored to the #31 roster (the first 4: 3 guaranteed +
    Turin)."""
    roster_pairs = [(city.citta, city.zona) for city in ROSTER]
    zones = _zones("ablation-analyze")
    for zona in zones:
        assert zona in roster_pairs, f"{zona} non è nel roster di validazione C1"
    assert zones == roster_pairs[:4]


def test_istat_arm_differs_only_by_istat() -> None:
    """#345: ontology vs ontology + ISTAT comparison on the same 4 zones and model."""
    istat = load_config(EXPERIMENTS_DIR / "istat-analyze-groq.json")
    base = load_config(EXPERIMENTS_DIR / "ablation-analyze-groq.json")
    assert (istat.name, istat.mode, istat.model, istat.istat) == (
        "istat-analyze-groq",
        "analyze",
        "groq",
        True,
    )
    assert base.istat is False
    assert istat.model_dump(exclude={"name", "istat"}) == base.model_dump(
        exclude={"name", "istat"}
    )
