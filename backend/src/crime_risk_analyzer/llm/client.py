"""Provider-agnostic LLM client: Claude (Anthropic) + model via Groq (#20).

Thin and *async* wrapper over the two official SDKs, with a single public
surface :meth:`LLMClient.generate`. The switch between providers happens via
``settings.LLM_PROVIDER`` (factory :func:`build_llm_client`); for Claude the
system prompt travels as a block with ``cache_control: ephemeral`` to enable
Anthropic's prompt caching (on a second request with the same system
prompt ``cache_hit`` is ``True``).

Boundaries (orchestrator.md / generation.md): this module does NOT build the
domain system prompt nor assemble the RAG context (responsibility of #23);
it receives ``system_prompt`` and ``user_content`` already prepared. No numeric
scoring of dangerousness: here only the raw narrative and the reproducibility
metadata are generated.
"""

from __future__ import annotations

import asyncio
import hashlib
from functools import lru_cache
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from crime_risk_analyzer.config import Settings, get_settings

#: Exact version of the Claude model (not an alias) — generation.md §Riproducibilita'.
CLAUDE_MODEL = "claude-sonnet-4-6"

#: Model on Groq for the experimental comparison — generation.md.
#: ``llama-3.1-70b-versatile`` was retired by Groq; its replacement
#: ``llama-3.3-70b-versatile`` was in turn removed from the catalogue
#: (2026-09-10): Groq no longer hosts any general-purpose Llama model, only
#: two prompt-guard models (classifiers, not chat). Replaced with
#: ``openai/gpt-oss-120b`` (same order of magnitude, 120B open-weight),
#: verified available via ``GET /openai/v1/models`` with the current key.
GROQ_MODEL = "openai/gpt-oss-120b"

#: Stable tag of the FAMILY of the current Groq model (not the exact release):
#: the integration tests use it to pin the branch (Groq, not Claude, not
#: fallback) in ``response.llm_used`` tolerating a versioned alias different from
#: ``GROQ_MODEL`` that Groq may report. It must be updated by hand together with
#: ``GROQ_MODEL`` — deriving it with a heuristic parsing of the string does not hold
#: when the shape of the model id changes: the split on ``"-"`` that on
#: ``llama-3.3-70b-versatile`` gave "llama" on ``openai/gpt-oss-120b`` gives
#: "openai/gpt", i.e. the VENDOR prefix, which would pin any
#: ``openai/gpt-*`` instead of just the gpt-oss family. The
#: family/model id link is verified offline in ``tests/test_llm_client.py``.
GROQ_MODEL_FAMILY = "gpt-oss"

#: Shared fixed parameters (generation.md §Riproducibilita').
#: #229: default raised 1024 -> 1536 (anti-truncation margin on the dense case). MUST
#: stay in sync with ``config.Settings.llm_max_tokens`` and
#: ``generation.DEFAULT_MAX_TOKENS`` (test_generation::..._synced_across_modules).
_MAX_TOKENS = 1536
_DEFAULT_TEMPERATURE = 0.2
_DEFAULT_SEED = 42

#: Parameters of the Groq branch only, because ``GROQ_MODEL`` is a reasoning model
#: (#20/#316). Without them Groq reasons at "medium" effort by default and can leak
#: the chain-of-thought into the message content (bug documented
#: on the Groq forum). The low effort also reduces the competition with the budget of
#: ``_MAX_TOKENS``, shared between reasoning and narrative: spent there, the model
#: closes with ``finish_reason="stop"`` and empty content (guard in
#: ``_generate_groq``). Named and not inline: they are model configuration
#: choices, like temperature/seed, and must be read next to them.
_GROQ_REASONING_EFFORT = "low"
_GROQ_INCLUDE_REASONING = False

#: Default timeout (seconds) of the LLM layer (#114). It balances a
#: legitimate generation (a few seconds) with a cap that prevents indefinite hangs;
#: overridable via ``Settings.llm_timeout_seconds``.
_DEFAULT_TIMEOUT_SECONDS = 30.0

Provider = Literal["claude", "groq"]


def model_id_for_provider(provider: Provider) -> str:
    """Exact model id for a provider, without instantiating a client.

    Single source of truth shared by :attr:`LLMClient.model` and by the fallback
    of ``eval.harness._model_id_of`` (no double claude/groq ternary to
    keep in sync by hand): it reads ``CLAUDE_MODEL``/``GROQ_MODEL`` as
    globals of this module on every call, so a test that monkeypatches
    ``client.GROQ_MODEL`` stays consistent wherever this function is invoked.
    """
    return CLAUDE_MODEL if provider == "claude" else GROQ_MODEL


class LLMError(RuntimeError):
    """LLM layer error: missing key or provider failure.

    The SDK exceptions (rate limit, 5xx, network) are encapsulated here,
    so the orchestrator can map them to an HTTP response without knowing the
    Anthropic/Groq-specific types.
    """


class LLMResponse(BaseModel):
    """Outcome of a generation, independent of the provider.

    It exposes the narrative and the reproducibility metadata (``temperature``,
    ``seed``, ``prompt_hash``) required by the ``repro`` block of ``/analyze``.
    """

    text: str = Field(description="Narrativa generata dal modello.")
    llm_used: str = Field(description="Model id esatto che ha prodotto il testo.")
    tokens_input: int = Field(
        ge=0, description="Token di input fatturati (non cachati)."
    )
    tokens_output: int = Field(ge=0, description="Token di output generati.")
    cache_hit: bool = Field(
        description="True se la richiesta ha letto dal prompt cache (solo Claude)."
    )
    temperature: float = Field(description="Temperature usata (riproducibilita').")
    seed: int = Field(description="Seed usato/loggato (riproducibilita').")
    prompt_hash: str = Field(description="Hash del system prompt (versionamento).")


# --- minimal surfaces of the SDKs (DI + testability) ---
#
# Only the methods actually used are typed: the real clients
# ``anthropic.AsyncAnthropic`` / ``groq.AsyncGroq`` satisfy these Protocols
# structurally, and the tests inject lightweight doubles without touching the network.


class _AnthropicMessages(Protocol):
    async def create(self, **kwargs: Any) -> Any: ...


class _AnthropicClient(Protocol):
    @property
    def messages(self) -> _AnthropicMessages: ...


class _GroqCompletions(Protocol):
    async def create(self, **kwargs: Any) -> Any: ...


class _GroqChat(Protocol):
    @property
    def completions(self) -> _GroqCompletions: ...


class _GroqClient(Protocol):
    @property
    def chat(self) -> _GroqChat: ...


def _prompt_hash(system_prompt: str) -> str:
    """Stable hash of the system prompt for versioning (``repro`` field)."""
    return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()


class LLMClient:
    """Async client that abstracts Claude and Groq behind :meth:`generate`.

    Do not instantiate the SDKs in here: they are injected (via the class
    constructors :meth:`for_claude`/:meth:`for_groq` or the factory
    :func:`build_llm_client`), so the tests pass doubles and no global
    state is created.
    """

    def __init__(
        self,
        *,
        provider: Provider,
        anthropic_client: _AnthropicClient | None = None,
        groq_client: _GroqClient | None = None,
        temperature: float = _DEFAULT_TEMPERATURE,
        seed: int = _DEFAULT_SEED,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = _MAX_TOKENS,
    ) -> None:
        self._provider: Provider = provider
        self._anthropic = anthropic_client
        self._groq = groq_client
        self._temperature = temperature
        self._seed = seed
        self._timeout = timeout
        self._max_tokens = max_tokens

    @classmethod
    def for_claude(
        cls,
        anthropic_client: _AnthropicClient,
        *,
        temperature: float = _DEFAULT_TEMPERATURE,
        seed: int = _DEFAULT_SEED,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = _MAX_TOKENS,
    ) -> LLMClient:
        """Builds a client that uses Claude via the injected Anthropic SDK."""
        return cls(
            provider="claude",
            anthropic_client=anthropic_client,
            temperature=temperature,
            seed=seed,
            timeout=timeout,
            max_tokens=max_tokens,
        )

    @classmethod
    def for_groq(
        cls,
        groq_client: _GroqClient,
        *,
        temperature: float = _DEFAULT_TEMPERATURE,
        seed: int = _DEFAULT_SEED,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = _MAX_TOKENS,
    ) -> LLMClient:
        """Builds a client that uses ``GROQ_MODEL`` via the injected Groq SDK."""
        return cls(
            provider="groq",
            groq_client=groq_client,
            temperature=temperature,
            seed=seed,
            timeout=timeout,
            max_tokens=max_tokens,
        )

    def with_temperature(self, temperature: float, seed: int = 0) -> LLMClient:
        """New client that reuses the same injected SDK with fixed temperature/seed.

        Used by the evaluation pipeline for determinism (temperature=0).
        It preserves the current ``timeout``/``max_tokens``. Accessing
        ``self._anthropic``/``self._groq`` is legitimate inside the same class.
        """
        return LLMClient(
            provider=self._provider,
            anthropic_client=self._anthropic,
            groq_client=self._groq,
            temperature=temperature,
            seed=seed,
            timeout=self._timeout,
            max_tokens=self._max_tokens,
        )

    @property
    def provider(self) -> Provider:
        """Active provider (``claude`` or ``groq``)."""
        return self._provider

    @property
    def model(self) -> str:
        """Exact model id of the active provider."""
        return model_id_for_provider(self._provider)

    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        """Generates the narrative for the given ``system_prompt``/``user_content``.

        Raises :class:`LLMError` if the provider fails. For Claude the system
        prompt is sent as a block with ``cache_control: ephemeral``: the
        second request with the same system prompt results in ``cache_hit=True``.
        """
        if self._provider == "claude":
            return await self._generate_claude(system_prompt, user_content)
        return await self._generate_groq(system_prompt, user_content)

    async def _generate_claude(
        self, system_prompt: str, user_content: str
    ) -> LLMResponse:
        assert self._anthropic is not None  # guaranteed by the factory/constructor
        # NB determinism (generation.md §Riproducibilita'): Anthropic's Messages API
        # does NOT accept a ``seed`` parameter (API limitation), so
        # ``self._seed`` is only logged in ``repro``, not sent. Determinism
        # on the Claude side is best-effort via low ``temperature``
        # (temperature=0 does not guarantee identical outputs anyway). On Groq the
        # seed is instead passed (see ``_generate_groq``).
        try:
            # ``asyncio.wait_for`` imposes an explicit client-side ceiling: if the
            # provider hangs, the coroutine is cancelled and TimeoutError is
            # raised (mapped below to LLMError). Defence in depth with
            # the ``timeout=`` passed to the SDK in ``build_llm_client`` (which also
            # covers the SDK's bounded internal retries: 408/409/429/5xx/network).
            message = await asyncio.wait_for(
                self._anthropic.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                    system=[
                        {
                            "type": "text",
                            "text": system_prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[{"role": "user", "content": user_content}],
                ),
                timeout=self._timeout,
            )
        except TimeoutError as exc:
            raise LLMError(
                f"Timeout Claude dopo {self._timeout}s "
                "(mappato a LLMError -> fallback strutturato dell'orchestrator)"
            ) from exc
        except Exception as exc:  # noqa: BLE001 — encapsulates any SDK error
            raise LLMError(f"Generazione Claude fallita: {exc}") from exc

        # Truncation: if the model stopped because of ``max_tokens`` the narrative
        # is incomplete and unreliable for the citation layer (a source tag or
        # a claim might stay cut in half). We map it to LLMError, so
        # the orchestrator degrades to the structured data only (consistent with the
        # Anthropic 429/5xx handling in orchestrator.md), instead of silently serving
        # a truncated narrative.
        if getattr(message, "stop_reason", None) == "max_tokens":
            raise LLMError(
                f"Risposta Claude troncata (stop_reason=max_tokens, "
                f"max_tokens={self._max_tokens}): narrativa incompleta scartata"
            )

        # Empty content with a declared "successful" outcome: the response is not
        # truncated (no ``max_tokens``) but carries no usable text. An empty
        # narrative is never a success — the citation layer has nothing
        # to anchor and the interface would show a mute analysis in place of the
        # structured fallback. Same guard, same exit as the truncation.
        text = _extract_anthropic_text(message)
        if not text.strip():
            raise LLMError(
                f"Risposta Claude senza testo utilizzabile "
                f"(stop_reason={getattr(message, 'stop_reason', None)!r}): "
                "narrativa vuota scartata"
            )

        usage = message.usage
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        return LLMResponse(
            text=text,
            llm_used=str(message.model),
            tokens_input=int(usage.input_tokens),
            tokens_output=int(usage.output_tokens),
            cache_hit=cache_read > 0,
            temperature=self._temperature,
            seed=self._seed,
            prompt_hash=_prompt_hash(system_prompt),
        )

    async def _generate_groq(
        self, system_prompt: str, user_content: str
    ) -> LLMResponse:
        assert self._groq is not None  # guaranteed by the factory/constructor
        try:
            completion = await asyncio.wait_for(
                self._groq.chat.completions.create(
                    model=GROQ_MODEL,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                    seed=self._seed,
                    # Reasoning model: see _GROQ_REASONING_EFFORT.
                    reasoning_effort=_GROQ_REASONING_EFFORT,
                    include_reasoning=_GROQ_INCLUDE_REASONING,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                ),
                timeout=self._timeout,
            )
        except TimeoutError as exc:
            raise LLMError(
                f"Timeout Groq dopo {self._timeout}s "
                "(mappato a LLMError -> fallback strutturato dell'orchestrator)"
            ) from exc
        except Exception as exc:  # noqa: BLE001 — encapsulates any SDK error
            raise LLMError(f"Generazione Groq fallita: {exc}") from exc

        # Truncation: the Groq/OpenAI equivalent of ``stop_reason=max_tokens`` is
        # ``finish_reason=="length"``. Same choice as the Claude branch: truncated
        # narrative -> LLMError -> fallback, never silently served.
        if getattr(completion.choices[0], "finish_reason", None) == "length":
            raise LLMError(
                f"Risposta Groq troncata (finish_reason=length, "
                f"max_tokens={self._max_tokens}): narrativa incompleta scartata"
            )

        # Empty content DESPITE a normal ``finish_reason``: the guard
        # above does not see it (it is not "length"), but the case is concrete precisely
        # on ``GROQ_MODEL``, which is a reasoning model — it can consume the whole
        # ``max_tokens`` budget reasoning and close with ``stop`` without having
        # written a line of narrative. Without this check it became a
        # SUCCESSFUL ``LLMResponse(text="")``: no structured fallback,
        # no error, a mute analysis served as if it were an analysis.
        text = str(completion.choices[0].message.content or "")
        if not text.strip():
            raise LLMError(
                f"Risposta Groq senza testo utilizzabile "
                f"(finish_reason="
                f"{getattr(completion.choices[0], 'finish_reason', None)!r}, "
                f"max_tokens={self._max_tokens}): narrativa vuota scartata — "
                "possibile budget di reasoning esaurito"
            )

        usage = completion.usage
        return LLMResponse(
            text=text,
            llm_used=str(completion.model),
            tokens_input=int(usage.prompt_tokens),
            tokens_output=int(usage.completion_tokens),
            cache_hit=False,  # Groq does not expose prompt caching
            temperature=self._temperature,
            seed=self._seed,
            prompt_hash=_prompt_hash(system_prompt),
        )


def _extract_anthropic_text(message: Any) -> str:
    """Concatenates the text blocks of the Anthropic response (ignores the rest)."""
    parts: list[str] = []
    for block in message.content:
        if getattr(block, "type", None) == "text":
            parts.append(str(block.text))
    return "".join(parts)


def build_llm_client(settings: Settings, provider: Provider | None = None) -> LLMClient:
    """Builds the :class:`LLMClient` from the provider configured in ``settings``.

    If ``provider`` is given explicitly, it is used in place of
    ``settings.llm_provider`` (override for the eval pipeline that respects
    ``ExperimentConfig.model``). With ``provider=None`` (default) the
    behaviour is identical to the previous version: backward compatible.

    It instantiates the SDK of the chosen provider with the key from ``settings`` (never
    hardcoded). Raises :class:`LLMError` if the needed key is missing.
    Injectable into the endpoints via ``Depends``.

    Timeout/retry (#114): the SDK is built with ``timeout=`` from
    ``settings.llm_timeout_seconds`` (and the same value is the client-side
    ``asyncio.wait_for`` ceiling). **Retry deliberately not reimplemented**:
    the Anthropic/Groq SDKs already apply a *bounded* retry with exponential
    backoff (default ``max_retries=2``) on transient errors only
    (408/409/429/5xx/connection, including the timeout). Reimplementing it here
    would multiply the latency (risk on the <10s budget), would add
    non-determinism to the latency measure used in the eval and would duplicate
    logic already present (over-engineering). The ``wait_for`` acts as the total
    cap on the wall-clock; the SDK retries only help the quick transient
    failures within that cap.
    """
    chosen: Provider = provider if provider is not None else settings.llm_provider
    if chosen == "claude":
        if settings.anthropic_api_key is None:
            raise LLMError(
                "ANTHROPIC_API_KEY mancante: necessaria con LLM_PROVIDER=claude"
            )
        from anthropic import AsyncAnthropic

        anthropic_client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            timeout=settings.llm_timeout_seconds,
        )
        # The real SDK satisfies `_AnthropicClient` at runtime (same
        # `messages.create` surface), but its keyword-only signature is not recognised
        # as structurally compatible with the `**kwargs` Protocol by pyright
        # strict. Targeted ignore only at the SDK->Protocol adaptation point.
        return LLMClient.for_claude(
            anthropic_client,  # pyright: ignore[reportArgumentType]
            timeout=settings.llm_timeout_seconds,
            max_tokens=settings.llm_max_tokens,
        )

    if settings.groq_api_key is None:
        raise LLMError("GROQ_API_KEY mancante: necessaria con LLM_PROVIDER=groq")
    from groq import AsyncGroq

    groq_client = AsyncGroq(
        api_key=settings.groq_api_key.get_secret_value(),
        timeout=settings.llm_timeout_seconds,
    )
    # Same reason as the Claude branch: SDK->Protocol adaptation at the boundary.
    return LLMClient.for_groq(
        groq_client,  # pyright: ignore[reportArgumentType]
        timeout=settings.llm_timeout_seconds,
        max_tokens=settings.llm_max_tokens,
    )


@lru_cache
def get_llm_client() -> LLMClient:
    """Cached DI provider of the LLM client built from the configured provider."""
    return build_llm_client(get_settings())
