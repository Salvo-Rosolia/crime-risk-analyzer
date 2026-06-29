"""Metriche deterministiche di valutazione (#34).

v1 strutturali sulla AnalyzeResponse. Proxy testuali (vedi caveat EN/IT nella
spec): grounding e hallucination si appoggiano ai tag [ONTOLOGIA] e ai nomi POI.
Validate dall'annotazione manuale sul set ristretto.
"""

from __future__ import annotations

import re

from crime_risk_analyzer.eval.pricing import cost_usd
from crime_risk_analyzer.eval.schema import Metrics
from crime_risk_analyzer.orchestrator import AnalyzeResponse

_TAG_RE = re.compile(r"\[(ONTOLOGIA|CONTESTO|SPECULATIVO)\]")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[.\n]", text) if s.strip()]


def _anchors(resp: AnalyzeResponse) -> set[str]:
    """Token ancorati: nomi POI + hazard strutturati, lowercase."""
    pois = {p.name.lower() for p in resp.poi}
    hazards = {r.hazard.lower() for m in resp.risk_models for r in m.risks}
    return pois | hazards


def grounding(resp: AnalyzeResponse) -> float:
    """Frazione di frasi taggate la cui asserzione è ancorata ai dati [0,1].

    Narrativa vuota → 1.0 (vacuamente ancorata). Narrativa non vuota senza
    alcun tag → 0.0 (l'LLM non ha citato).
    """
    if not resp.narrativa.strip():
        return 1.0
    tagged = [s for s in _sentences(resp.narrativa) if _TAG_RE.search(s)]
    if not tagged:
        return 0.0
    anchors = _anchors(resp)
    backed = [s for s in tagged if any(a in s.lower() for a in anchors)]
    return len(backed) / len(tagged)


def hallucination(resp: AnalyzeResponse) -> float:
    """Frazione di frasi [ONTOLOGIA] NON ancorate ai dati [0,1].

    Nessuna frase [ONTOLOGIA] (incl. narrativa vuota) → 0.0.
    """
    onto = [s for s in _sentences(resp.narrativa) if "[ONTOLOGIA]" in s.upper()]
    if not onto:
        return 0.0
    anchors = _anchors(resp)
    halluc = [s for s in onto if not any(a in s.lower() for a in anchors)]
    return len(halluc) / len(onto)


def latency_ms(resp: AnalyzeResponse) -> int:
    """Latenza end-to-end (passthrough da AnalyzeResponse)."""
    return resp.latenza_ms


def cost_usd_of(resp: AnalyzeResponse) -> float:
    """Costo stimato; 0 se non c'è LLM (baseline/fallback → llm_used vuoto)."""
    if not resp.llm_used:
        return 0.0
    return cost_usd(resp.llm_used, resp.tokens_input, resp.tokens_output)


def compute_metrics(resp: AnalyzeResponse) -> Metrics:
    """Assembla le quattro metriche dalla AnalyzeResponse."""
    return Metrics(
        grounding=grounding(resp),
        hallucination=hallucination(resp),
        latency_ms=latency_ms(resp),
        cost_usd=cost_usd_of(resp),
    )
