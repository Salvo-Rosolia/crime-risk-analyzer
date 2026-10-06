"""Misura il budget del prompt di zona con i dati ISTAT (#345, D14).

Costruisce il prompt REALE (system + user_content) sugli snapshot delle 4 zone di
valutazione con l'ontologia vera, a ISTAT spento e acceso, e stampa per ciascuno:
POI inclusi, voci ISTAT incluse e tagliate, stima dei token (la stessa euristica
del troncamento) e, se ``tiktoken`` e' disponibile, i token REALI col tokenizer di
gpt-oss (``o200k_harmony``) piu' i ``max_tokens`` riservati all'output: cio' che
Groq conta contro il limite di token al minuto (TPM 8.000 per gpt-oss-120b).

Uso (da ``backend``; tiktoken NON e' una dipendenza del progetto)::

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
from crime_risk_analyzer.istat.dati import VOCE_TOTALE
from crime_risk_analyzer.ontology import load_ontology
from crime_risk_analyzer.rag.generation import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_REQUEST_TOKEN_BUDGET,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_ISTAT,
    _estimate_tokens,  # pyright: ignore[reportPrivateUsage]
    build_context,
)
from crime_risk_analyzer.rag.grounding import ground
from crime_risk_analyzer.rag.retrieval import retrieve
from crime_risk_analyzer.sparql_module.query_executor import RiskQueryExecutor

BACKEND = Path(__file__).resolve().parents[1]
ONTOLOGIA = BACKEND / "ontology" / "terminus_crime_materialized.ttl"
RISULTATI = BACKEND / "results"
#: TPM di gpt-oss-120b su Groq (D14) e margine del 5% per l'errore residuo.
TPM_GROQ = 8000
LIMITE_REALE = int(TPM_GROQ * 0.95)

Contatore = Callable[[str], int]


class Misura(NamedTuple):
    zona: str
    istat: bool
    stima_totale: int
    reali_totale: int | None
    poi_inclusi: int
    poi_totali: int
    voci_istat: int
    voci_tagliate: int


async def contesti() -> list[tuple[str, dict[str, Any]]]:
    """Contesti grounded delle 4 zone di valutazione, dagli snapshot (nessuna rete)."""
    executor = RiskQueryExecutor(load_ontology(str(ONTOLOGIA)))
    out: list[tuple[str, dict[str, Any]]] = []
    for caso in ROSTER[:4]:
        chiave = make_snapshot_key(caso.citta, caso.zona)
        ctx = await retrieve(
            caso.citta,
            caso.zona,
            executor=executor,
            poi_source=replay_source(snapshot_path(RISULTATI, chiave)),
            geo_source=offline_geo_source(),
        )
        out.append((chiave, dict(ground(ctx))))
    return out


def misura(
    zona: str,
    ctx: dict[str, Any],
    *,
    istat: bool,
    budget: int = DEFAULT_REQUEST_TOKEN_BUDGET,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    reali: Contatore | None = None,
) -> Misura:
    """Stessa costruzione di ``generate_analysis``, senza chiamare il modello."""
    prompt_budget = SYSTEM_PROMPT_ISTAT if istat else SYSTEM_PROMPT
    contesto = build_context(
        ctx,
        context_budget_tokens=budget - _estimate_tokens(prompt_budget) - max_tokens,
        istat=istat,
    )
    system = SYSTEM_PROMPT_ISTAT if contesto.blocco_istat.testo else SYSTEM_PROMPT
    return Misura(
        zona=zona,
        istat=istat,
        stima_totale=_estimate_tokens(system)
        + _estimate_tokens(contesto.testo)
        + max_tokens,
        reali_totale=(
            reali(system) + reali(contesto.testo) + max_tokens
            if reali is not None
            else None
        ),
        poi_inclusi=contesto.poi_inclusi,
        poi_totali=len(ctx.get("validated_risks", [])),
        voci_istat=sum(1 for r in contesto.blocco_istat.righe if r.voce != VOCE_TOTALE),
        voci_tagliate=contesto.blocco_istat.voci_tagliate,
    )


def contatore_reale() -> Contatore | None:
    """Conteggio reale col tokenizer di gpt-oss, se ``tiktoken`` e' installato."""
    try:
        tiktoken: Any = importlib.import_module("tiktoken")
    except ImportError:
        return None
    codifica: Any = tiktoken.get_encoding("o200k_harmony")

    def conta(testo: str) -> int:
        return len(codifica.encode(testo))

    return conta


def budget_suggerito(
    casi: list[tuple[str, dict[str, Any]]], *, reali: Contatore
) -> int | None:
    """Il budget piu' alto (passi di 100) con tutte le richieste sotto il limite."""
    for budget in range(DEFAULT_REQUEST_TOKEN_BUDGET, 3999, -100):
        richieste = [
            misura(zona, ctx, istat=istat, budget=budget, reali=reali)
            for zona, ctx in casi
            for istat in (False, True)
        ]
        if all((m.reali_totale or 0) <= LIMITE_REALE for m in richieste):
            return budget
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Budget del prompt con ISTAT (D14)")
    parser.add_argument("--suggerisci-budget", action="store_true")
    args = parser.parse_args(argv)
    casi = asyncio.run(contesti())
    reali = contatore_reale()
    print(f"budget {DEFAULT_REQUEST_TOKEN_BUDGET}, limite reale {LIMITE_REALE}")
    print("zona | istat | stima | reali | POI | voci | tagliate")
    for zona, ctx in casi:
        for istat in (False, True):
            m = misura(zona, ctx, istat=istat, reali=reali)
            print(
                f"{m.zona} | {m.istat} | {m.stima_totale} | {m.reali_totale} | "
                f"{m.poi_inclusi}/{m.poi_totali} | {m.voci_istat} | {m.voci_tagliate}"
            )
    if args.suggerisci_budget:
        if reali is None:
            print(
                "serve tiktoken: uv run --with tiktoken python scripts/istat_budget.py"
            )
            return 1
        print(f"budget suggerito: {budget_suggerito(casi, reali=reali)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
