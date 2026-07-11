"""Generation layer RAG: prompt, chiamata LLM, output JSON (#23).

Step finale del ciclo RAG: dato il context **gia' validato dal grounding**
(`rag/grounding.md`), assembla il prompt (system fisso cachabile + contesto
variabile), invoca il client LLM provider-agnostico (#20, `llm/client.py`) e
produce un :class:`GenerationResult` serializzabile in JSON.

Confini (generation.md / grounding.md / retrieval.md):
- NON fa retrieval ne' grounding: il `context_dict` arriva con i rischi gia'
  ancorati e con i tag/confidence assegnati (step adiacenti, moduli separati).
- NON istanzia gli SDK LLM ne' costruisce il system prompt di dominio dentro il
  client: il system prompt vive qui (parte fissa cachata), il client riceve
  ``system_prompt``/``user_content`` gia' pronti.
- NESSUNO scoring numerico di pericolosita': solo narrativa + tag/confidence
  qualitativi propagati dal grounding (vincoli legali, _project.md).

Riproducibilita' (generation.md §Riproducibilita'): ``temperature``/``seed``/
``prompt_hash`` arrivano dal :class:`LLMResponse` e vengono esposti nel blocco
``repro`` cosi' ogni run e' confrontabile (Claude vs Llama) e ricostruibile.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from pydantic import BaseModel, Field, model_validator

from crime_risk_analyzer.i18n.terminus_labels import (
    controlled_vocab_for,
    label_en,
    label_it,
)
from crime_risk_analyzer.llm.client import LLMResponse
from crime_risk_analyzer.models.vocab import Confidence, ConfidenceSummary, Tag

#: Divieto di valutazione di pericolosita' (vincolo legale non negoziabile,
#: _project.md §Vincoli). Copre sia le scale NUMERICHE (percentuali/voti) sia
#: quelle QUALITATIVE di livello di pericolo (ALTO/MEDIO/BASSO): entrambe sono
#: vietate. NON confonde la pericolosita' con i livelli di confidenza, che
#: qualificano la forza probatoria delle affermazioni, non la magnitudo del
#: pericolo. Estratto come costante nominata e COMPOSTO in :data:`SYSTEM_PROMPT`:
#: cosi' il divieto vive nel prompt inviato al modello (non solo nei docstring)
#: e un test puo' verificarne l'inclusione, diventando rosso se la regola viene
#: rimossa dalla composizione.
RULE_NO_DANGER_RATING = (
    "7. NON attribuire alla zona o ai POI una valutazione di pericolosita': "
    'ne\' punteggi, percentuali, voti o scale NUMERICHE (es. "rischio 73%", '
    '"7/10") ne\' scale QUALITATIVE di livello di pericolo (es. "rischio '
    'ALTO/MEDIO/BASSO", "zona pericolosa/sicura"). Descrivi i fattori di rischio '
    "in forma discorsiva; i livelli confermato/plausibile/speculativo qualificano "
    "la forza probatoria delle singole affermazioni, non la magnitudo del pericolo"
)

#: Divieto di indicazioni operative di dispiegamento/assegnazione risorse
#: (vincolo di posizionamento, _project.md §Vincoli: human-in-the-loop, niente
#: azioni operative come "Assegna pattuglia"). Estratto come costante nominata e
#: composto in :data:`SYSTEM_PROMPT` per lo stesso motivo del divieto sopra.
RULE_NO_OPERATIONAL_DIRECTIVES = (
    "8. NON fornire indicazioni operative di dispiegamento o assegnazione di "
    'risorse (es. "assegna una pattuglia", "invia agenti sul posto"): limitati '
    "all'analisi del rischio, la decisione operativa resta all'operatore umano"
)

#: System prompt — parte FISSA del prompt, versionata su Git e inviata come
#: blocco cachabile (``cache_control: ephemeral``) dal client Claude. Contiene
#: le regole obbligatorie di citation/grounding (generation.md §System prompt) e
#: i vincoli legali/di posizionamento (:data:`RULE_NO_DANGER_RATING`,
#: :data:`RULE_NO_OPERATIONAL_DIRECTIVES`) composti esplicitamente qui.
SYSTEM_PROMPT = f"""\
Sei un analista di sicurezza urbana. Ricevi un contesto strutturato su una zona urbana
e devi produrre un'analisi del rischio in italiano, chiara e professionale.

REGOLE OBBLIGATORIE:
1. Per ogni rischio che menzioni, indica la fonte: [ONTOLOGIA] [CONTESTO] [SPECULATIVO]
2. Non inventare rischi non presenti nel contesto che ti viene fornito
3. Organizza la risposta per POI, dal piu' al meno critico
4. Sintesi discorsiva finale, senza un livello di rischio complessivo della zona
5. Usa un linguaggio tecnico ma comprensibile per operatori non informatici
6. Usa ESATTAMENTE i termini del VOCABOLARIO CONTROLLATO per nominare gli hazard
{RULE_NO_DANGER_RATING}
{RULE_NO_OPERATIONAL_DIRECTIVES}

LIVELLI DI CONFIDENZA:
- confermato: supportato da ontologia + contesto OSM verificabile
- plausibile: supportato solo da ontologia, oppure solo dal contesto OSM/input
- speculativo: solo ragionamento per analogia su POI non coperti dall'ontologia"""


class _LLMClientLike(Protocol):
    """Superficie minima del client LLM usata dal generation layer.

    Permette di iniettare il :class:`~crime_risk_analyzer.llm.client.LLMClient`
    reale o un doppio nei test, senza accoppiarsi alla classe concreta (DI).
    """

    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse: ...


class RiskItem(BaseModel):
    """Singolo rischio per un POI: hazard + confidence + tag fonte.

    Riflette il citation layer: ogni rischio porta un ``tag``
    (``ONTOLOGIA``/``CONTESTO``/``SPECULATIVO``) e un ``confidence`` qualitativo
    (mai un punteggio numerico). Le etichette display EN/IT sono popolate dalla
    sorgente unica del vocabolario controllato (#77) a partire dall'``hazard``.
    """

    hazard: str = Field(description="Nome dell'hazard (classe ontologica reale).")
    confidence: Confidence = Field(
        description="Livello qualitativo: confermato/plausibile/speculativo."
    )
    tag: Tag | None = Field(
        default=None, description="Tag fonte: ONTOLOGIA/CONTESTO/SPECULATIVO."
    )
    hazard_label_it: str = Field(
        default="", description="Etichetta IT controllata dell'hazard (display)."
    )
    hazard_label_en: str = Field(
        default="", description="Etichetta EN corretta dell'hazard (display)."
    )

    @model_validator(mode="after")
    def _fill_labels(self) -> RiskItem:
        if not self.hazard_label_it:
            self.hazard_label_it = label_it(self.hazard)
        if not self.hazard_label_en:
            self.hazard_label_en = label_en(self.hazard)
        return self


class RiskModel(BaseModel):
    """Rischi raggruppati per POI (contributo del generation layer)."""

    poi: str = Field(description="Nome del POI.")
    risks: list[RiskItem] = Field(
        default_factory=list[RiskItem], description="Rischi ancorati per il POI."
    )


class Repro(BaseModel):
    """Blocco di riproducibilita' loggato per ogni run (generation.md)."""

    temperature: float = Field(description="Temperature usata nella generazione.")
    seed: int = Field(description="Seed usato/loggato.")
    prompt_hash: str = Field(description="Hash del system prompt versionato.")


class GenerationResult(BaseModel):
    """Contributo del generation layer allo schema canonico di ``/analyze``.

    L'orchestrator unisce questi campi con ``citta``/``zona_normalizzata`` e
    ``poi[]`` (orchestrator.md); in caso di discrepanza prevale orchestrator.md.
    """

    narrativa: str = Field(description="Testo dell'analisi generato dal LLM.")
    risk_models: list[RiskModel] = Field(
        default_factory=list[RiskModel],
        description="Rischi per POI (dal context validato).",
    )
    confidence_summary: ConfidenceSummary = Field(
        default_factory=ConfidenceSummary,
        description="Conteggio per livello (confermato/plausibile/speculativo).",
    )
    llm_used: str = Field(description="Model id esatto che ha prodotto la narrativa.")
    tokens_input: int = Field(ge=0, description="Token di input fatturati.")
    tokens_output: int = Field(ge=0, description="Token di output generati.")
    latenza_ms: int = Field(ge=0, description="Latenza della chiamata LLM in ms.")
    cache_hit: bool = Field(
        description="True se la richiesta ha letto dal prompt cache."
    )
    repro: Repro = Field(description="Parametri per la riproducibilita' del run.")


def build_context_str(context_dict: dict[str, Any]) -> str:
    """Assembla la parte VARIABILE del prompt dal context validato.

    Segue il formato di generation.md §Contesto per richiesta: zona + un blocco
    per POI con hazard (tag + confidence), vulnerabilita' e path ontologico.
    I tag/confidence sono quelli gia' assegnati dal grounding: qui non si
    rivaluta nulla, si serializza solo per il modello.
    """
    zona = str(context_dict.get("zona", ""))
    validated = context_dict.get("validated_risks", [])

    all_hazards = [
        str(risk.get("hazard", ""))
        for poi in validated
        for risk in poi.get("risks", [])
    ]
    vocab = controlled_vocab_for(all_hazards)

    lines: list[str] = [f"ZONA: {zona}", ""]
    if vocab:
        lines.append(
            "VOCABOLARIO CONTROLLATO (usa ESATTAMENTE questi termini italiani "
            "per nominare gli hazard):"
        )
        lines.append("  " + "; ".join(vocab))
        lines.append("")
    lines.append("POI RILEVANTI:")

    for poi in validated:
        name = str(poi.get("poi", ""))
        terminus = str(poi.get("terminus_class", ""))
        lines.append(f"  POI: {name} ({terminus})")

        risks = poi.get("risks", [])
        if risks:
            lines.append("  Hazard verificati:")
            for risk in risks:
                hazard = str(risk.get("hazard", ""))
                hazard_it = label_it(hazard)
                tag = risk.get("tag")
                confidence = str(risk.get("confidence", ""))
                tag_str = f"[{tag}] " if tag else ""
                lines.append(f"    - {tag_str}{hazard} / {hazard_it} ({confidence})")
        else:
            lines.append("  Hazard verificati: nessuno (POI non coperto)")

        vulns = poi.get("vulnerabilities", [])
        if vulns:
            lines.append(f"  Vulnerabilita': {', '.join(str(v) for v in vulns)}")

        path = poi.get("sparql_path")
        if path:
            lines.append(f"  Path ontologico: {path}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _risk_models_from_context(context_dict: dict[str, Any]) -> list[RiskModel]:
    """Estrae i risk_models per POI dal context validato (no ricalcolo)."""
    models: list[RiskModel] = []
    for poi in context_dict.get("validated_risks", []):
        items = [
            RiskItem.model_validate(
                {
                    "hazard": str(risk.get("hazard", "")),
                    "confidence": risk.get("confidence"),
                    "tag": risk.get("tag"),
                }
            )
            for risk in poi.get("risks", [])
        ]
        models.append(RiskModel(poi=str(poi.get("poi", "")), risks=items))
    return models


async def generate_analysis(
    context_dict: dict[str, Any], llm_client: _LLMClientLike
) -> GenerationResult:
    """Genera l'analisi del rischio dal context validato.

    Costruisce il prompt (``SYSTEM_PROMPT`` + :func:`build_context_str`), chiama
    il client LLM iniettato e assembla l'output JSON: narrativa dal modello,
    ``risk_models``/``confidence_summary`` propagati dal grounding (nessun
    ricalcolo qui), metadati di token/latenza/cache e blocco ``repro``.
    """
    user_content = build_context_str(context_dict)

    start = time.perf_counter()
    response = await llm_client.generate(SYSTEM_PROMPT, user_content)
    latenza_ms = int((time.perf_counter() - start) * 1000)

    confidence_summary = ConfidenceSummary.model_validate(
        context_dict.get("confidence_summary", {})
    )

    return GenerationResult(
        narrativa=response.text,
        risk_models=_risk_models_from_context(context_dict),
        confidence_summary=confidence_summary,
        llm_used=response.llm_used,
        tokens_input=response.tokens_input,
        tokens_output=response.tokens_output,
        latenza_ms=latenza_ms,
        cache_hit=response.cache_hit,
        repro=Repro(
            temperature=response.temperature,
            seed=response.seed,
            prompt_hash=response.prompt_hash,
        ),
    )
