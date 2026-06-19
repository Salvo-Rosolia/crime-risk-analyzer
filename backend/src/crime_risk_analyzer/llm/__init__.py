"""Layer LLM: client provider-agnostico (Claude + Groq) per la generazione (#20).

Espone :class:`LLMClient`, :class:`LLMResponse`, :class:`LLMError` e la factory
:func:`build_llm_client`. Il client riceve ``system_prompt`` e ``user_content``
dall'esterno: l'assemblaggio del contesto RAG e il system prompt di dominio sono
responsabilita' del generation layer (#23), non di questo modulo.
"""

from crime_risk_analyzer.llm.client import (
    CLAUDE_MODEL,
    GROQ_MODEL,
    LLMClient,
    LLMError,
    LLMResponse,
    build_llm_client,
)

__all__ = [
    "CLAUDE_MODEL",
    "GROQ_MODEL",
    "LLMClient",
    "LLMError",
    "LLMResponse",
    "build_llm_client",
]
