"""Layer RAG: retrieval, grounding e generation.

Espone il generation layer (#23): costruzione del prompt, chiamata al client
LLM (#20) e output JSON strutturato con confidence e metadati di
riproducibilita'. Retrieval e grounding sono step adiacenti (moduli separati);
qui il context_dict arriva gia' validato.
"""

from crime_risk_analyzer.rag.generation import (
    SYSTEM_PROMPT,
    GenerationResult,
    Repro,
    RiskItem,
    RiskModel,
    build_context_str,
    generate_analysis,
)

__all__ = [
    "SYSTEM_PROMPT",
    "GenerationResult",
    "Repro",
    "RiskItem",
    "RiskModel",
    "build_context_str",
    "generate_analysis",
]
