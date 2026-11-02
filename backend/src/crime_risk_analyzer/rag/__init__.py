"""RAG layer: retrieval, grounding and generation.

Exposes the generation layer (#23): prompt construction, call to the LLM
client (#20) and structured JSON output with confidence and reproducibility
metadata. Retrieval and grounding are adjacent steps (separate modules);
here the context_dict arrives already validated.
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
