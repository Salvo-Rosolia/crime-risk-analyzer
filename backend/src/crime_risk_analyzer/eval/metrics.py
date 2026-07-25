"""Metriche deterministiche di valutazione (#34).

Metriche strutturali sulla AnalyzeResponse. ``grounding``/``hallucination`` sono
PROXY testuali (vedi caveat EN/IT nella spec): misurano se le asserzioni di rischio
citano i dati ancorati (nomi POI/hazard, label EN/IT #77).

**Semantica M1 (#229, ``METRICS_VERSION == 2``).** Il proxy grada SOLO le asserzioni
del blocco ``[ONTOLOGIA]`` — l'unico layer con backing strutturato dal grounding
(``grounding.py`` emette solo il tag ``ONTOLOGIA``). L'``overview`` di sintesi e il
blocco ``[CONTESTO]`` sono INTERPRETAZIONE dell'LLM (conoscenza generale, non un dato
ontologico): la loro qualita'/fabbricazione NON e' gradabile da un proxy deterministico
di ancoraggio ed e' delegata al gold umano (#109/#152), oltre a essere frenata a monte
dal prompt (regola 2 + ``[CONTESTO]`` "senza inventare"). L'attribuzione della fonte e'
per BLOCCO (header #196), non per tag inline: il proxy v1 (pre-#229) cercava ``[TAG]``
nella singola frase e, con i tag ora solo negli header, era mal-calibrato su output
reale — motivo del cambio (non una regressione). La validazione dell'accordo
proxy-vs-annotazione gold umana vive in ``eval/gold.py`` (#109), da rifare su questa
definizione prima di un claim forte.
"""

from __future__ import annotations

import re

from crime_risk_analyzer.eval.pricing import cost_usd
from crime_risk_analyzer.eval.schema import Metrics
from crime_risk_analyzer.orchestrator import AnalyzeResponse
from crime_risk_analyzer.rag.generation import parse_source_prose

#: Generazione della SEMANTICA del proxy grounding/hallucination (#229). ``1`` era il
#: proxy inline-tag (pre-#229): cercava ``[TAG]`` nella singola frase, ma la struttura
#: a blocchi #196 mette il tag SOLO nell'header -> su output reale il proxy v1 era
#: mal-calibrato. ``2`` e' M1 block-aware: grada SOLO le asserzioni del blocco
#: [ONTOLOGIA] (l'unico layer con backing strutturato dal grounding), delegando
#: l'interpretazione [CONTESTO] al gold umano (#152). Espone la versione cosi' che un
#: confronto (compare.py/winner.py #157) non mescoli silenziosamente generazioni di
#: metrica: i valori pre-#229 su output reale non sono confrontabili con questi.
METRICS_VERSION = 2


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


def _ontology_assertions(resp: AnalyzeResponse) -> list[str]:
    """Asserzioni gradabili dal proxy (M1, #229): le frasi del blocco [ONTOLOGIA].

    :func:`~crime_risk_analyzer.rag.generation.parse_source_prose` isola il CORPO del
    blocco ``[ONTOLOGIA]`` dalla narrativa a blocchi (#196): l'header e' gia' escluso
    dal parser, l'``overview`` e il blocco ``[CONTESTO]`` finiscono in campi separati e
    NON entrano qui (interpretazione -> gold umano). Ogni frase-corpo del blocco e' una
    asserzione ontologica: il denominatore di grounding/hallucination. Una narrativa
    senza blocco ``[ONTOLOGIA]`` riconoscibile (vuota o non compliant) ritorna ``[]``:
    la distinzione tra ramo VACUO e NON-ATTRIBUZIONE e' fatta in :func:`_grade`.
    """
    ontology_prose = parse_source_prose(resp.narrativa).ontologia
    return _sentences(ontology_prose)


def _grounded(assertions: list[str], anchors: set[str]) -> list[str]:
    """Asserzioni ontologiche ancorate: nominano un dato reale (POI/hazard, label)."""
    return [s for s in assertions if any(a in s.lower() for a in anchors)]


def _grade(resp: AnalyzeResponse) -> tuple[int, int] | None:
    """``(grounded, assertions)`` del blocco [ONTOLOGIA], o ``None`` se non gradabile.

    ``None`` = ramo VACUO (grounding 1.0 / hallucination 0.0), riservato ai casi in cui
    il proxy non ha legittimamente nulla da gradare:
    - narrativa vuota (fallback strutturato: nessun output LLM da giudicare);
    - nessun ancoraggio disponibile (``_anchors`` vuoto: nessun dato da citare).

    Il caso "narrativa PIENA con dati da citare ma SENZA asserzioni ontologiche" (es.
    modello che non emette l'header [ONTOLOGIA], o lo emette vuoto) NON e' vacuo: e'
    NON-ATTRIBUZIONE e vale ``(0, 1)`` -> grounding 0.0 / hallucination 1.0. Cosi' un
    modello non puo' ottenere un punteggio perfetto omettendo l'header (l'asse
    hallucination e' il criterio PRIMARIO di ``winner.py``, #157): l'evasione perde
    invece di vincere.
    """
    if not resp.narrativa.strip():
        return None
    anchors = _anchors(resp)
    if not anchors:
        return None
    assertions = _ontology_assertions(resp)
    if not assertions:
        return (0, 1)
    return (len(_grounded(assertions, anchors)), len(assertions))


def grounding(resp: AnalyzeResponse) -> float:
    """Frazione di ASSERZIONI ONTOLOGICHE ancorate ai dati [0,1] (M1, #229).

    Asserzione = frase del blocco ``[ONTOLOGIA]`` (:func:`_ontology_assertions`);
    grounded = asserzione che nomina un ancoraggio (POI/hazard, label EN/IT #77).
    Rami vacui (:func:`_grade` -> ``None``: narrativa vuota o nessun ancoraggio da
    citare) → 1.0. Narrativa piena con dati da citare ma senza asserzioni ontologiche
    (header assente/vuoto) → 0.0 (non-attribuzione, non "vacua"). ``overview``/
    ``[CONTESTO]`` sono esclusi (interpretazione, delegata al gold).
    """
    graded = _grade(resp)
    if graded is None:
        return 1.0
    grounded, assertions = graded
    return grounded / assertions


def hallucination(resp: AnalyzeResponse) -> float:
    """Frazione di ASSERZIONI ONTOLOGICHE NON ancorate ai dati [0,1] (M1, #229).

    Complemento di :func:`grounding` sullo stesso denominatore (le asserzioni del blocco
    ``[ONTOLOGIA]``): ``hallucination == 1 - grounding`` su ogni ramo (a meno
    dell'arrotondamento in virgola mobile). Una frase nel blocco ontologia che asserisce
    un rischio senza ancoraggio reale e' fabbricazione e conta come allucinazione
    (invariante #109 preservato DENTRO il layer con backing). Rami vacui → 0.0;
    narrativa piena senza asserzioni ontologiche → 1.0 (non-attribuzione).
    La fabbricazione nell'interpretazione ``[CONTESTO]`` NON e' rilevata dal proxy
    (delegata al gold umano #109/#152): la validazione proxy-vs-gold resta in
    :mod:`crime_risk_analyzer.eval.gold`, da rifare su questa definizione.
    """
    graded = _grade(resp)
    if graded is None:
        return 0.0
    grounded, assertions = graded
    return (assertions - grounded) / assertions


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
