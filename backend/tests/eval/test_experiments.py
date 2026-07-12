"""Test delle config esperimento versionate di ablation (#32).

Le config vivono in ``backend/experiments/`` (versionate nel repo per la
riproducibilità). Questi test blindano il contratto del deliverable: i due
bracci (analyze/baseline) esistono, parsano contro ``ExperimentConfig`` e sono
ancorati alle STESSE 4 zone del roster di validazione C1 (#31).
"""

from __future__ import annotations

from pathlib import Path

from crime_risk_analyzer.eval.city_agnostic import ROSTER
from crime_risk_analyzer.eval.cli import load_config

#: backend/experiments (test_file → eval → tests → backend).
EXPERIMENTS_DIR = Path(__file__).resolve().parents[2] / "experiments"


def _zones(name: str) -> list[tuple[str, str]]:
    cfg = load_config(EXPERIMENTS_DIR / f"{name}.json")
    return [(c.citta, c.zona) for c in cfg.cases]


def test_ablation_configs_parse_with_expected_names() -> None:
    for name in ("ablation-analyze", "ablation-baseline"):
        cfg = load_config(EXPERIMENTS_DIR / f"{name}.json")
        assert cfg.name == name


def test_ablation_configs_have_the_two_arms() -> None:
    """Due config: un braccio COMPLETO (analyze+LLM), uno BASELINE (senza LLM)."""
    assert load_config(EXPERIMENTS_DIR / "ablation-analyze.json").mode == "analyze"
    assert load_config(EXPERIMENTS_DIR / "ablation-baseline.json").mode == "baseline"


def test_ablation_arms_share_the_same_four_zones() -> None:
    """Confronto iso-input: i due bracci puntano alle STESSE 4 coppie (citta, zona)."""
    zones_analyze = _zones("ablation-analyze")
    zones_baseline = _zones("ablation-baseline")
    assert len(zones_analyze) == 4
    assert zones_analyze == zones_baseline


def test_ablation_zones_anchored_to_c1_roster() -> None:
    """Le 4 zone sono ancorate al roster #31 (i primi 4: 3 garantite + Torino)."""
    roster_pairs = [(city.citta, city.zona) for city in ROSTER]
    zones = _zones("ablation-analyze")
    for zona in zones:
        assert zona in roster_pairs, f"{zona} non è nel roster di validazione C1"
    assert zones == roster_pairs[:4]
