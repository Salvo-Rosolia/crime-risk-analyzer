"""Tests for the provider-agnostic LLM client (#20).

No real network call: the Anthropic/Groq SDKs are injected as dependencies and
replaced with async doubles that reproduce only the surface used by the client
(Messages API for Claude, Chat Completions for Groq). We verify: (a) claude
provider -> populated LLMResponse; (b) prompt caching -> cache_hit True on the
second call with the same system prompt; (c) groq provider switch -> same
LLMResponse format; (d) provider errors mapped to LLMError; (e) missing key ->
error at construction.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import SecretStr

from crime_risk_analyzer.config import Settings

# Import from the package (not from the ``.client`` module) on purpose: it is the
# public surface of the LLM layer, and this import verifies it together with the
# rest.
from crime_risk_analyzer.llm import (
    CLAUDE_MODEL,
    GROQ_MODEL,
    GROQ_MODEL_FAMILY,
    LLMClient,
    LLMError,
    LLMResponse,
    build_llm_client,
    model_id_for_provider,
)

_SYSTEM = "Sei un analista di sicurezza urbana. Regole: ..."
_USER = "ZONA: Colosseo\nPOI RILEVANTI: ..."


# --- async doubles of the SDKs (they reproduce only the surface used) ---


class _Usage:
    def __init__(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _AnthropicMessage:
    def __init__(
        self, *, text: str, model: str, usage: _Usage, stop_reason: str = "end_turn"
    ) -> None:
        self.content = [_TextBlock(text)]
        self.model = model
        self.usage = usage
        self.stop_reason = stop_reason


class _FakeAnthropicMessages:
    def __init__(self, owner: _FakeAnthropic) -> None:
        self._owner = owner

    async def create(self, **kwargs: Any) -> _AnthropicMessage:
        self._owner.calls.append(kwargs)
        # Simulates the prompt caching: the first request writes the cache, the
        # following ones with the same system prompt read it.
        system = kwargs["system"]
        block: dict[str, str] = system[0]
        system_text: str = block["text"]
        if system_text in self._owner.seen_systems:
            usage = _Usage(
                input_tokens=10, output_tokens=42, cache_read_input_tokens=820
            )
        else:
            self._owner.seen_systems.add(system_text)
            usage = _Usage(
                input_tokens=830, output_tokens=42, cache_creation_input_tokens=820
            )
        return _AnthropicMessage(
            text=self._owner.text,
            model=str(kwargs["model"]),
            usage=usage,
            stop_reason=self._owner.stop_reason,
        )


class _FakeAnthropic:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.seen_systems: set[str] = set()
        # ``end_turn`` = normal completion; the truncation tests set it to
        # ``max_tokens`` to trigger the LLMError.
        self.stop_reason = "end_turn"
        # Text of the response block: the empty-content tests empty it without touching
        # ``stop_reason`` (the response stays "successful").
        self.text = "Analisi del rischio per la zona."
        self.messages = _FakeAnthropicMessages(self)


class _GroqUsage:
    def __init__(self, *, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _GroqMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _GroqChoice:
    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self.message = _GroqMessage(content)
        self.finish_reason = finish_reason


class _GroqCompletion:
    def __init__(
        self,
        *,
        content: str,
        model: str,
        usage: _GroqUsage,
        finish_reason: str = "stop",
    ) -> None:
        self.choices = [_GroqChoice(content, finish_reason)]
        self.model = model
        self.usage = usage


class _FakeGroqCompletions:
    def __init__(self, owner: _FakeGroq) -> None:
        self._owner = owner

    async def create(self, **kwargs: Any) -> _GroqCompletion:
        self._owner.calls.append(kwargs)
        return _GroqCompletion(
            content=self._owner.content,
            model=str(kwargs["model"]),
            usage=_GroqUsage(prompt_tokens=512, completion_tokens=88),
            finish_reason=self._owner.finish_reason,
        )


class _FakeGroqChat:
    def __init__(self, owner: _FakeGroq) -> None:
        self.completions = _FakeGroqCompletions(owner)


class _FakeGroq:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        # ``stop`` = normal completion; ``length`` = truncated on max_tokens
        # (Groq/OpenAI equivalent of stop_reason=max_tokens).
        self.finish_reason = "stop"
        # Message content: the empty-content tests empty it leaving
        # ``finish_reason="stop"`` (the response declares itself successful).
        self.content = "Analisi del rischio per la zona."
        self.chat = _FakeGroqChat(self)


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "anthropic_api_key": SecretStr("sk-ant-test"),
        "groq_api_key": SecretStr("gsk-test"),
    }
    base.update(overrides)
    return Settings(**base)  # pyright: ignore[reportCallIssue]


# --- (a) claude provider: LLMResponse with populated fields ---


async def test_claude_returns_populated_response() -> None:
    fake = _FakeAnthropic()
    client = LLMClient.for_claude(fake, temperature=0.2, seed=42)

    result = await client.generate(_SYSTEM, _USER)

    assert isinstance(result, LLMResponse)
    assert result.text == "Analisi del rischio per la zona."
    assert result.llm_used == CLAUDE_MODEL
    assert result.tokens_input == 830
    assert result.tokens_output == 42
    assert result.cache_hit is False
    assert result.temperature == 0.2
    assert result.seed == 42
    assert result.prompt_hash  # non-empty


async def test_claude_uses_exact_model_and_params() -> None:
    fake = _FakeAnthropic()
    client = LLMClient.for_claude(fake, temperature=0.2, seed=42)

    await client.generate(_SYSTEM, _USER)

    call = fake.calls[0]
    assert call["model"] == "claude-sonnet-4-6"
    assert call["max_tokens"] == 1536  # #229: default raised 1024 -> 1536
    assert call["temperature"] == 0.2
    # system as a block with ephemeral cache_control (prompt caching)
    assert call["system"] == [
        {"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}
    ]
    assert call["messages"] == [{"role": "user", "content": _USER}]


# --- (b) prompt caching: cache_hit True on the second call ---


async def test_claude_prompt_caching_second_call_is_hit() -> None:
    fake = _FakeAnthropic()
    client = LLMClient.for_claude(fake, temperature=0.2, seed=42)

    first = await client.generate(_SYSTEM, _USER)
    second = await client.generate(_SYSTEM, "ZONA: altra zona")

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.tokens_input == 10  # only the non-cached tokens


# --- (c) groq provider switch: same LLMResponse format ---


async def test_groq_returns_same_response_shape() -> None:
    fake = _FakeGroq()
    client = LLMClient.for_groq(fake, temperature=0.2, seed=42)

    result = await client.generate(_SYSTEM, _USER)

    assert isinstance(result, LLMResponse)
    assert result.text == "Analisi del rischio per la zona."
    assert result.llm_used == GROQ_MODEL
    assert result.tokens_input == 512
    assert result.tokens_output == 88
    assert result.cache_hit is False  # Groq does not expose prompt caching
    assert result.temperature == 0.2
    assert result.seed == 42
    assert result.prompt_hash


async def test_groq_uses_chat_messages_and_params() -> None:
    fake = _FakeGroq()
    client = LLMClient.for_groq(fake, temperature=0.2, seed=42)

    await client.generate(_SYSTEM, _USER)

    call = fake.calls[0]
    assert call["model"] == GROQ_MODEL
    assert call["max_tokens"] == 1536  # #229: default raised 1024 -> 1536
    assert call["temperature"] == 0.2
    assert call["seed"] == 42
    # Reasoning model (#316): without these two parameters Groq reasons at "medium"
    # effort and can leak the chain-of-thought into the content. Deleting them must
    # make this fail here, not go unnoticed in a live run.
    assert call["reasoning_effort"] == "low"
    assert call["include_reasoning"] is False
    assert call["messages"] == [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _USER},
    ]


# --- model constants: family and resolution per provider ---


def test_groq_model_family_is_a_tag_of_the_current_model_id() -> None:
    """``GROQ_MODEL_FAMILY`` must be kept in sync by hand with ``GROQ_MODEL``.

    The link was verified only inside a ``@pytest.mark.integration`` test (skipped
    by default): a misalignment would have passed in CI and would have shown only
    live, where the tag serves to pin the Groq branch. This test is offline and
    always runs.
    """
    assert GROQ_MODEL_FAMILY in GROQ_MODEL


def test_model_id_for_provider_resolves_both_providers() -> None:
    assert model_id_for_provider("claude") == CLAUDE_MODEL
    assert model_id_for_provider("groq") == GROQ_MODEL


# --- deterministic prompt_hash, dependent on the system prompt ---


async def test_prompt_hash_stable_for_same_system() -> None:
    fake = _FakeAnthropic()
    client = LLMClient.for_claude(fake, temperature=0.2, seed=42)

    a = await client.generate(_SYSTEM, _USER)
    b = await client.generate(_SYSTEM, "altro user")
    c = await client.generate("system diverso", _USER)

    assert a.prompt_hash == b.prompt_hash
    assert a.prompt_hash != c.prompt_hash


# --- (d) provider error mapped to LLMError ---


async def test_claude_provider_error_is_wrapped() -> None:
    fake = _FakeAnthropic()

    async def _raise(**_kwargs: Any) -> _AnthropicMessage:
        raise RuntimeError("503 overloaded")

    # Replaces the create method with one that fails.
    fake.messages.create = _raise
    client = LLMClient.for_claude(fake, temperature=0.2, seed=42)

    with pytest.raises(LLMError):
        await client.generate(_SYSTEM, _USER)


async def test_groq_provider_error_is_wrapped() -> None:
    fake = _FakeGroq()

    async def _raise(**_kwargs: Any) -> _GroqCompletion:
        raise RuntimeError("429 rate limited")

    fake.chat.completions.create = _raise  # type: ignore[method-assign]
    client = LLMClient.for_groq(fake, temperature=0.2, seed=42)

    with pytest.raises(LLMError):
        await client.generate(_SYSTEM, _USER)


# --- (e) factory + missing key ---


def test_build_llm_client_claude_from_settings() -> None:
    client = build_llm_client(_settings(llm_provider="claude"))
    assert isinstance(client, LLMClient)
    assert client.provider == "claude"
    assert client.model == CLAUDE_MODEL


def test_build_llm_client_groq_from_settings() -> None:
    client = build_llm_client(_settings(llm_provider="groq"))
    assert isinstance(client, LLMClient)
    assert client.provider == "groq"
    assert client.model == GROQ_MODEL


def test_build_llm_client_missing_claude_key_raises() -> None:
    with pytest.raises(LLMError):
        build_llm_client(_settings(llm_provider="claude", anthropic_api_key=None))


def test_build_llm_client_missing_groq_key_raises() -> None:
    with pytest.raises(LLMError):
        build_llm_client(_settings(llm_provider="groq", groq_api_key=None))


# --- with_temperature: pinned temperature/seed, same provider and SDK ---


def test_with_temperature_returns_new_client_with_pinned_params() -> None:
    """with_temperature creates a new LLMClient with pinned temperature/seed."""
    fake = _FakeAnthropic()
    original = LLMClient.for_claude(fake, temperature=0.2, seed=42)

    pinned = original.with_temperature(0.0, 0)

    assert pinned is not original
    assert pinned.provider == "claude"
    assert pinned._temperature == 0.0  # pyright: ignore[reportPrivateUsage]
    assert pinned._seed == 0  # pyright: ignore[reportPrivateUsage]
    # The original must not be mutated (original was built with 0.2/42).
    assert original._temperature != 0.0 or original._seed != 0  # pyright: ignore[reportPrivateUsage]


def test_with_temperature_preserves_same_sdk_double() -> None:
    """The returned client reuses the same SDK (same fake instance)."""
    fake = _FakeAnthropic()
    original = LLMClient.for_claude(fake, temperature=0.2, seed=42)

    pinned = original.with_temperature(0.0, 0)

    # The shared double must be the same object (same injected SDK).
    assert pinned._anthropic is fake  # pyright: ignore[reportPrivateUsage]


def test_with_temperature_groq_preserves_provider_and_sdk() -> None:
    """with_temperature also works with the groq provider."""
    fake = _FakeGroq()
    original = LLMClient.for_groq(fake, temperature=0.2, seed=42)

    pinned = original.with_temperature(0.0, 0)

    assert pinned.provider == "groq"
    assert pinned._groq is fake  # pyright: ignore[reportPrivateUsage]


# --- (A) build_llm_client with explicit provider override ---


def test_build_llm_client_provider_override_groq_wins_over_settings() -> None:
    """build_llm_client(settings, provider='groq') builds groq even if
    settings.llm_provider=='claude', as long as both keys are present."""
    s = _settings(llm_provider="claude")
    client = build_llm_client(s, provider="groq")
    assert client.provider == "groq"


def test_build_llm_client_provider_override_claude_wins_over_settings() -> None:
    """build_llm_client(settings, provider='claude') builds claude even if
    settings.llm_provider=='groq'."""
    s = _settings(llm_provider="groq")
    client = build_llm_client(s, provider="claude")
    assert client.provider == "claude"


def test_build_llm_client_provider_none_falls_back_to_settings() -> None:
    """provider=None (default) uses settings.llm_provider -- backward compatibility."""
    s_claude = _settings(llm_provider="claude")
    s_groq = _settings(llm_provider="groq")
    assert build_llm_client(s_claude).provider == "claude"
    assert build_llm_client(s_groq).provider == "groq"


# --- (#114) timeout: provider beyond the timeout -> LLMError (-> fallback) ---


async def test_claude_timeout_is_mapped_to_llm_error() -> None:
    """A Claude provider that exceeds the timeout produces LLMError (not a hang)."""
    fake = _FakeAnthropic()

    async def _slow(**_kwargs: Any) -> _AnthropicMessage:
        await asyncio.sleep(1)  # beyond the timeout: it will be cancelled
        raise AssertionError("create doveva essere cancellato dal timeout")

    fake.messages.create = _slow  # type: ignore[method-assign]
    client = LLMClient.for_claude(fake, temperature=0.0, seed=0, timeout=0.01)

    with pytest.raises(LLMError):
        await client.generate(_SYSTEM, _USER)


async def test_groq_timeout_is_mapped_to_llm_error() -> None:
    """A Groq provider that exceeds the timeout produces LLMError (not a hang)."""
    fake = _FakeGroq()

    async def _slow(**_kwargs: Any) -> _GroqCompletion:
        await asyncio.sleep(1)
        raise AssertionError("create doveva essere cancellato dal timeout")

    fake.chat.completions.create = _slow  # type: ignore[method-assign]
    client = LLMClient.for_groq(fake, temperature=0.0, seed=0, timeout=0.01)

    with pytest.raises(LLMError):
        await client.generate(_SYSTEM, _USER)


# --- (#114) truncation: stop_reason/finish_reason -> LLMError (-> fallback) ---


async def test_claude_max_tokens_truncation_is_mapped_to_llm_error() -> None:
    """stop_reason=max_tokens: truncated narrativa -> LLMError, not served."""
    fake = _FakeAnthropic()
    fake.stop_reason = "max_tokens"
    client = LLMClient.for_claude(fake, temperature=0.2, seed=42)

    with pytest.raises(LLMError):
        await client.generate(_SYSTEM, _USER)


async def test_groq_length_finish_reason_is_mapped_to_llm_error() -> None:
    """finish_reason=length (Groq) is equivalent to the max_tokens truncation ->
    LLMError."""
    fake = _FakeGroq()
    fake.finish_reason = "length"
    client = LLMClient.for_groq(fake, temperature=0.2, seed=42)

    with pytest.raises(LLMError):
        await client.generate(_SYSTEM, _USER)


async def test_truncation_guard_fires_regardless_of_max_tokens_value() -> None:
    """#229/D6: the anti-truncation guard fires on the provider SIGNAL
    (``stop_reason=max_tokens`` / ``finish_reason=length``), NOT on the value of
    ``max_tokens``. Raising the cap to 1536 (or beyond) does not disable the safety
    net: a truncated output stays discarded -> LLMError -> fallback, at any
    ``max_tokens``. So "1536 is enough" stays an empirical claim (live smoke run),
    while the guard guarantees that a possible truncation is never served."""
    claude = _FakeAnthropic()
    claude.stop_reason = "max_tokens"
    with pytest.raises(LLMError):
        await LLMClient.for_claude(claude, max_tokens=4096).generate(_SYSTEM, _USER)

    groq = _FakeGroq()
    groq.finish_reason = "length"
    with pytest.raises(LLMError):
        await LLMClient.for_groq(groq, max_tokens=4096).generate(_SYSTEM, _USER)


# --- (#316) empty content with "successful" outcome -> LLMError (-> fallback) ---


@pytest.mark.parametrize("empty_value", ["", "   \n\t  "])
async def test_groq_empty_content_is_mapped_to_llm_error(empty_value: str) -> None:
    """Empty content and normal ``finish_reason``: it is a failure, not a text.

    ``GROQ_MODEL`` is a reasoning model: it can spend the whole ``max_tokens``
    budget reasoning and close with ``finish_reason="stop"`` without having emitted
    a visible line. The truncation guard does not intercept it (it is not "length"),
    and without this check the pipeline received an empty narrativa marked as
    SUCCESS -- worse than the error, because it does not trigger the structured
    fallback and serves a mute analysis as if it were an analysis.
    """
    fake = _FakeGroq()
    fake.content = empty_value  # finish_reason stays "stop"
    client = LLMClient.for_groq(fake, temperature=0.2, seed=42)

    with pytest.raises(LLMError):
        await client.generate(_SYSTEM, _USER)


@pytest.mark.parametrize("empty_value", ["", "   \n\t  "])
async def test_claude_empty_text_is_mapped_to_llm_error(empty_value: str) -> None:
    """Same guard on the Claude branch: the cause changes, the outcome to serve does
    not.

    Here the reasoning budget is irrelevant (extended thinking is not active), but
    a response without useful text blocks remains possible -- and an empty narrativa
    is never a success for the citation layer, which has nothing to anchor on
    nothing. Keeping the guard on a single provider would leave the hole open
    exactly on the primary model.
    """
    fake = _FakeAnthropic()
    fake.text = empty_value  # stop_reason stays "end_turn"
    client = LLMClient.for_claude(fake, temperature=0.2, seed=42)

    with pytest.raises(LLMError):
        await client.generate(_SYSTEM, _USER)


async def test_claude_normal_stop_reason_does_not_raise() -> None:
    """stop_reason=end_turn (default): no LLMError, normal response."""
    fake = _FakeAnthropic()
    client = LLMClient.for_claude(fake, temperature=0.2, seed=42)

    result = await client.generate(_SYSTEM, _USER)

    assert result.text == "Analisi del rischio per la zona."


async def test_groq_normal_finish_reason_does_not_raise() -> None:
    """finish_reason=stop (default): no LLMError, normal response."""
    fake = _FakeGroq()
    client = LLMClient.for_groq(fake, temperature=0.2, seed=42)

    result = await client.generate(_SYSTEM, _USER)

    assert result.text == "Analisi del rischio per la zona."


# --- (#114) configurable max_tokens (default unchanged) ---


async def test_claude_uses_configured_max_tokens() -> None:
    fake = _FakeAnthropic()
    client = LLMClient.for_claude(fake, temperature=0.2, seed=42, max_tokens=256)

    await client.generate(_SYSTEM, _USER)

    assert fake.calls[0]["max_tokens"] == 256


async def test_groq_uses_configured_max_tokens() -> None:
    fake = _FakeGroq()
    client = LLMClient.for_groq(fake, temperature=0.2, seed=42, max_tokens=256)

    await client.generate(_SYSTEM, _USER)

    assert fake.calls[0]["max_tokens"] == 256


# --- (#114) build_llm_client: timeout/max_tokens from Settings ---


def test_build_llm_client_threads_timeout_and_max_tokens() -> None:
    """Settings.llm_timeout_seconds / llm_max_tokens reach the LLMClient."""
    s = _settings(llm_provider="claude", llm_timeout_seconds=15.0, llm_max_tokens=2048)
    client = build_llm_client(s)

    assert client._timeout == 15.0  # pyright: ignore[reportPrivateUsage]
    assert client._max_tokens == 2048  # pyright: ignore[reportPrivateUsage]


def test_build_llm_client_passes_timeout_to_anthropic_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Anthropic SDK is built with timeout= (fix of bug #114)."""
    import anthropic

    captured: dict[str, Any] = {}

    class _SpyAnthropic:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _SpyAnthropic)
    build_llm_client(_settings(llm_provider="claude", llm_timeout_seconds=12.5))

    assert captured.get("timeout") == 12.5


def test_build_llm_client_passes_timeout_to_groq_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Groq SDK is built with timeout= (fix of bug #114)."""
    import groq

    captured: dict[str, Any] = {}

    class _SpyGroq:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(groq, "AsyncGroq", _SpyGroq)
    build_llm_client(_settings(llm_provider="groq", llm_timeout_seconds=7.0))

    assert captured.get("timeout") == 7.0
