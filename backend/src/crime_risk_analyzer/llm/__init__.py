"""LLM layer: provider-agnostic client (Claude + Groq) for generation (#20).

Exposes :class:`LLMClient`, :class:`LLMResponse`, :class:`LLMError` and the factory
:func:`build_llm_client`. The client receives ``system_prompt`` and ``user_content``
from outside: the assembly of the RAG context and the domain system prompt are
responsibilities of the generation layer (#23), not of this module.
"""

from crime_risk_analyzer.llm.client import (
    CLAUDE_MODEL,
    GROQ_MODEL,
    GROQ_MODEL_FAMILY,
    LLMClient,
    LLMError,
    LLMResponse,
    build_llm_client,
    model_id_for_provider,
)

__all__ = [
    "CLAUDE_MODEL",
    "GROQ_MODEL",
    "GROQ_MODEL_FAMILY",
    "LLMClient",
    "LLMError",
    "LLMResponse",
    "build_llm_client",
    "model_id_for_provider",
]
