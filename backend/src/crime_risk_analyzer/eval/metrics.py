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


def _tagged_sentences(text: str) -> list[str]:
    """Frasi che portano un tag fonte [ONTOLOGIA]/[CONTESTO]/[SPECULATIVO].

    Seleziona per classe-tag via :data:`_TAG_RE` (che copre tutti e tre i tag):
    e' l'insieme delle asserzioni citate dall'LLM su cui grounding e hallucination
    misurano rispettivamente la frazione ancorata e non ancorata.
    """
    return [s for s in _sentences(text) if _TAG_RE.search(s)]


def _anchors(resp: AnalyzeResponse) -> set[str]:
    """Token ancorati: nomi POI + hazard (identifier + etichette EN/IT), lowercase.

    Include le etichette italiane controllate (#77) così il match regge quando la
    narrativa cita l'hazard in italiano (chiude il caveat EN/IT delle metriche).
    """
    anchors = {p.name.lower() for p in resp.poi}
    for model in resp.risk_models:
        for risk in model.risks:
            anchors.add(risk.hazard.lower())
            if risk.hazard_label_it:
                anchors.add(risk.hazard_label_it.lower())
            if risk.hazard_label_en:
                anchors.add(risk.hazard_label_en.lower())
    return anchors


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
    """Frazione di frasi taggate (qualunque classe) NON ancorate ai dati [0,1].

    Ispeziona TUTTE le classi-tag ([ONTOLOGIA]/[CONTESTO]/[SPECULATIVO]) e non la
    sola [ONTOLOGIA] (#109): una fabbricazione taggata come contesto o
    speculazione era prima invisibile e la metrica sotto-misurava l'allucinazione.
    L'ancoraggio ai dati (nomi POI + hazard EN/IT) resta il discriminante per ogni
    classe. Nessuna frase taggata (incl. narrativa vuota) → 0.0.

    Onesta' metrica (limite noto): sul sottoinsieme delle frasi taggate questa
    metrica e' il COMPLEMENTO di :func:`grounding` — stesso denominatore (le frasi
    taggate) e stesso predicato di ancoraggio — quindi ``hallucination == 1 -
    grounding`` su quel sottoinsieme. Le due NON sono segnali indipendenti.
    L'UNICA divergenza numerica dall'identita' e' la narrativa NON vuota SENZA
    frasi taggate: grounding 0.0 (l'LLM non ha citato) ma hallucination 0.0,
    mentre ``1 - 0.0 = 1.0``. La narrativa vuota prende invece un ramo di
    early-return separato in :func:`grounding` ma SODDISFA comunque l'identita'
    (grounding 1.0, hallucination 0.0, ``1 - 1.0 = 0.0``). La validazione
    indipendente e' demandata al confronto proxy-vs-gold in
    :mod:`crime_risk_analyzer.eval.gold`, in particolare alla cella FALSE-NEGATIVE
    (proxy tace, umano segnala) che quantifica la sotto-misura dell'allucinazione.
    """
    tagged = _tagged_sentences(resp.narrativa)
    if not tagged:
        return 0.0
    anchors = _anchors(resp)
    halluc = [s for s in tagged if not any(a in s.lower() for a in anchors)]
    return len(halluc) / len(tagged)


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
