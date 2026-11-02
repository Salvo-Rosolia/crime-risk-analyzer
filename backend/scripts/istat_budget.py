"""Measures the zone prompt budget with ISTAT data (#345, D14).

Builds the REAL prompt (system + user_content) on the snapshots of the 4 evaluation
zones with the real ontology, with ISTAT off and on, and prints for each of them:
POIs included, ISTAT items included and cut, token estimate (the same heuristic
used by the truncation) and, if ``tiktoken`` is available, the REAL tokens with the
gpt-oss tokenizer (``o200k_harmony``) plus the ``max_tokens`` reserved for the
output: what Groq counts against the tokens-per-minute limit (TPM 8,000 for
gpt-oss-120b).

Usage (from ``backend``; tiktoken is NOT a project dependency)::

    uv run --with tiktoken python scripts/istat_budget.py
    uv run --with tiktoken python scripts/istat_budget.py --suggerisci-budget
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

from crime_risk_analyzer.eval.city_agnostic import ROSTER
from crime_risk_analyzer.eval.harness import make_snapshot_key
from crime_risk_analyzer.eval.snapshots import (
    offline_geo_source,
    replay_source,
    snapshot_path,
)
from crime_risk_analyzer.istat.data import TOTAL_ITEM
from crime_risk_analyzer.ontology import load_ontology
from crime_risk_analyzer.rag.generation import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_REQUEST_TOKEN_BUDGET,
    _estimate_tokens,  # pyright: ignore[reportPrivateUsage]
    prepare_zone_request,
)
from crime_risk_analyzer.rag.grounding import ground
from crime_risk_analyzer.rag.retrieval import retrieve
from crime_risk_analyzer.sparql_module.query_executor import RiskQueryExecutor

BACKEND = Path(__file__).resolve().parents[1]
ONTOLOGY = BACKEND / "ontology" / "terminus_crime_materialized.ttl"
RESULTS = BACKEND / "results"
#: TPM of gpt-oss-120b on Groq (D14) and a 5% margin for the residual error.
GROQ_TPM = 8000
REAL_LIMIT = int(GROQ_TPM * 0.95)
#: Range of the budget search, around the default (steps of 100).
BUDGET_MIN, BUDGET_MAX, BUDGET_STEP = 6000, 12000, 100

Counter = Callable[[str], int]


class Measurement(NamedTuple):
    zone: str
    istat: bool
    estimated_total: int
    real_total: int | None
    pois_included: int
    pois_total: int
    istat_items: int
    items_cut: int


async def contexts() -> list[tuple[str, dict[str, Any]]]:
    """Grounded contexts of the 4 evaluation zones, from snapshots (no network)."""
    executor = RiskQueryExecutor(load_ontology(str(ONTOLOGY)))
    out: list[tuple[str, dict[str, Any]]] = []
    for case in ROSTER[:4]:
        key = make_snapshot_key(case.citta, case.zona)
        ctx = await retrieve(
            case.citta,
            case.zona,
            executor=executor,
            poi_source=replay_source(snapshot_path(RESULTS, key)),
            geo_source=offline_geo_source(),
        )
        out.append((key, dict(ground(ctx))))
    return out


def measure(
    zone: str,
    ctx: dict[str, Any],
    *,
    istat: bool,
    budget: int = DEFAULT_REQUEST_TOKEN_BUDGET,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    real: Counter | None = None,
) -> Measurement:
    """The request that ``generate_analysis`` would send, without calling the model.

    Same function (:func:`prepare_zone_request`): gate on the ISTAT rows and
    fallback to the off path when the block does not materialize, included.
    """
    system, context = prepare_zone_request(
        ctx, request_token_budget=budget, max_tokens=max_tokens, istat=istat
    )
    return Measurement(
        zone=zone,
        istat=istat,
        estimated_total=_estimate_tokens(system)
        + _estimate_tokens(context.testo)
        + max_tokens,
        real_total=(
            real(system) + real(context.testo) + max_tokens
            if real is not None
            else None
        ),
        pois_included=context.included_poi_count,
        pois_total=len(ctx.get("validated_risks", [])),
        istat_items=sum(1 for r in context.blocco_istat.righe if r.voce != TOTAL_ITEM),
        items_cut=context.blocco_istat.voci_tagliate,
    )


def real_counter() -> Counter | None:
    """Real count with the gpt-oss tokenizer, if ``tiktoken`` is installed."""
    try:
        tiktoken: Any = importlib.import_module("tiktoken")
    except ImportError:
        return None
    encoding: Any = tiktoken.get_encoding("o200k_harmony")

    def count(text: str) -> int:
        return len(encoding.encode(text))

    return count


def suggested_budget(
    cases: list[tuple[str, dict[str, Any]]], *, real: Counter
) -> int | None:
    """The highest budget with all requests under the limit.

    Searches :data:`BUDGET_MIN`..:data:`BUDGET_MAX` (steps of
    :data:`BUDGET_STEP`), above and below the default: starting from the default
    and going down would never say there is room to raise it.
    """
    for budget in range(BUDGET_MAX, BUDGET_MIN - 1, -BUDGET_STEP):
        requests = [
            measure(zone, ctx, istat=istat, budget=budget, real=real)
            for zone, ctx in cases
            for istat in (False, True)
        ]
        if all((m.real_total or 0) <= REAL_LIMIT for m in requests):
            return budget
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prompt budget with ISTAT (D14)")
    parser.add_argument("--suggerisci-budget", action="store_true")
    args = parser.parse_args(argv)
    cases = asyncio.run(contexts())
    real = real_counter()
    print(f"budget {DEFAULT_REQUEST_TOKEN_BUDGET}, real limit {REAL_LIMIT}")
    print("zone | istat | estimate | real | POI | items | cut")
    for zone, ctx in cases:
        for istat in (False, True):
            m = measure(zone, ctx, istat=istat, real=real)
            print(
                f"{m.zone} | {m.istat} | {m.estimated_total} | {m.real_total} | "
                f"{m.pois_included}/{m.pois_total} | {m.istat_items} | {m.items_cut}"
            )
    if args.suggerisci_budget:
        if real is None:
            print(
                "tiktoken needed: uv run --with tiktoken python scripts/istat_budget.py"
            )
            return 1
        print(f"suggested budget: {suggested_budget(cases, real=real)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
