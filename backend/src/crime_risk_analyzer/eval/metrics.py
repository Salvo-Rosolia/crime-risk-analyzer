"""Metriche deterministiche di valutazione (#34).

v1 strutturali sulla AnalyzeResponse. Proxy testuali (vedi caveat EN/IT nella
spec): grounding e hallucination si appoggiano ai tag fonte
([ONTOLOGIA]/[CONTESTO]/[SPECULATIVO]) e ai nomi POI/hazard. La validazione
dell'accordo proxy-vs-annotazione gold umana vive in ``eval/gold.py`` (#109).
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
    """Token ancorati: nomi POI + hazard (identifier + etichette EN/IT), lowercase.

    Include le etichette italiane controllate (#77) così il match regge quando la
    narrativa cita l'hazard in italiano (chiude il caveat EN/IT delle metriche).
    I token vuoti (es. POI senza nome) sono scartati: non devono ancorare tutto.
    """
    anchors = {p.name.lower() for p in resp.poi}
    for model in resp.risk_models:
        for risk in model.risks:
            anchors.add(risk.hazard.lower())
            if risk.hazard_label_it:
                anchors.add(risk.hazard_label_it.lower())
            if risk.hazard_label_en:
                anchors.add(risk.hazard_label_en.lower())
    # Scarta i token vuoti/whitespace: un POI OSM senza tag `name` arriva con
    # name="" e, poiché `"" in s` è sempre vero, renderebbe OGNI frase "ancorata"
    # neutralizzando la discriminazione (riaprirebbe cat.2 e vanificherebbe
    # l'esclusione del filler). Cfr. review #163 I1.
    return {a for a in anchors if a.strip()}


def _assertive_sentences(resp: AnalyzeResponse, anchors: set[str]) -> list[str]:
    """Frasi che fanno un'asserzione di dominio: taggate O che nominano un dato.

    Denominatore di grounding/hallucination (#163). Le frasi né taggate né
    ancorate (connettivo/filler) restano fuori: non sono asserzioni verificabili,
    quindi non gonfiano né sgonfiano il tasso di allucinazione.
    """
    return [
        s
        for s in _sentences(resp.narrativa)
        if _TAG_RE.search(s) or any(a in s.lower() for a in anchors)
    ]


def _grounded_sentences(assertive: list[str], anchors: set[str]) -> list[str]:
    """Asserzioni citate bene: taggate AND ancorate ai dati (POI/hazard)."""
    return [
        s
        for s in assertive
        if _TAG_RE.search(s) and any(a in s.lower() for a in anchors)
    ]


def grounding(resp: AnalyzeResponse) -> float:
    """Frazione di ASSERZIONI citate e ancorate ai dati [0,1].

    Asserzione = frase taggata O che nomina un dato (POI/hazard). Narrativa
    vuota → 1.0 (vacuamente ancorata, ramo esclusivo che precede il resto).
    Narrativa non vuota ma senza asserzioni → 0.0 (nulla ancorato).
    """
    if not resp.narrativa.strip():
        return 1.0
    anchors = _anchors(resp)
    assertive = _assertive_sentences(resp, anchors)
    if not assertive:
        return 0.0
    grounded = _grounded_sentences(assertive, anchors)
    return len(grounded) / len(assertive)


def hallucination(resp: AnalyzeResponse) -> float:
    """Frazione di ASSERZIONI NON citate/ancorate ai dati [0,1].

    Complemento di :func:`grounding` sullo stesso denominatore (le asserzioni):
    ``hallucination == 1 - grounding`` sui record con asserzioni > 0. Rispetto a
    #109 il denominatore non è più "le sole frasi taggate": una frase che afferma
    su un dato (nomina un POI/hazard) SENZA citare conta come allucinazione (cat.3,
    reperto A #163), altrimenti un modello che cita poco vincerebbe l'asse del
    verdetto. Ispeziona tutte le classi-tag ([ONTOLOGIA]/[CONTESTO]/[SPECULATIVO]).
    Narrativa vuota → 0.0 (ramo esclusivo). Narrativa piena senza asserzioni → 1.0
    (ha prodotto testo senza ancorare nulla). La validazione proxy-vs-gold umano
    resta in :mod:`crime_risk_analyzer.eval.gold` (#109), da rifare su questa
    definizione prima di un claim forte.
    """
    if not resp.narrativa.strip():
        return 0.0
    anchors = _anchors(resp)
    assertive = _assertive_sentences(resp, anchors)
    if not assertive:
        return 1.0
    grounded = _grounded_sentences(assertive, anchors)
    return (len(assertive) - len(grounded)) / len(assertive)


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
