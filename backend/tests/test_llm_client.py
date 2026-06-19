"""Test del client LLM provider-agnostico (#20).

Nessuna chiamata di rete reale: gli SDK Anthropic/Groq sono iniettati come
dipendenze e sostituiti con dei doppi asincroni che riproducono solo la
superficie usata dal client (Messages API per Claude, Chat Completions per
Groq). Si verificano: (a) provider claude -> LLMResponse popolata; (b) prompt
caching -> cache_hit True alla seconda chiamata con lo stesso system prompt;
(c) switch provider groq -> stesso formato di LLMResponse; (d) errori del
provider mappati a LLMError; (e) chiave assente -> errore in costruzione.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from crime_risk_analyzer.config import Settings
from crime_risk_analyzer.llm.client import (
    CLAUDE_MODEL,
    GROQ_MODEL,
    LLMClient,
    LLMError,
    LLMResponse,
    build_llm_client,
)

_SYSTEM = "Sei un analista di sicurezza urbana. Regole: ..."
_USER = "ZONA: Colosseo\nPOI RILEVANTI: ..."


# --- doppi asincroni degli SDK (riproducono solo la superficie usata) ---


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
    def __init__(self, *, text: str, model: str, usage: _Usage) -> None:
        self.content = [_TextBlock(text)]
        self.model = model
        self.usage = usage


class _FakeAnthropicMessages:
    def __init__(self, owner: _FakeAnthropic) -> None:
        self._owner = owner

    async def create(self, **kwargs: Any) -> _AnthropicMessage:
        self._owner.calls.append(kwargs)
        # Simula il prompt caching: la prima richiesta scrive la cache, le
        # successive con lo stesso system prompt la leggono.
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
            text="Analisi del rischio per la zona.",
            model=str(kwargs["model"]),
            usage=usage,
        )


class _FakeAnthropic:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.seen_systems: set[str] = set()
        self.messages = _FakeAnthropicMessages(self)


class _GroqUsage:
    def __init__(self, *, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _GroqMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _GroqChoice:
    def __init__(self, content: str) -> None:
        self.message = _GroqMessage(content)


class _GroqCompletion:
    def __init__(self, *, content: str, model: str, usage: _GroqUsage) -> None:
        self.choices = [_GroqChoice(content)]
        self.model = model
        self.usage = usage


class _FakeGroqCompletions:
    def __init__(self, owner: _FakeGroq) -> None:
        self._owner = owner

    async def create(self, **kwargs: Any) -> _GroqCompletion:
        self._owner.calls.append(kwargs)
        return _GroqCompletion(
            content="Analisi del rischio per la zona.",
            model=str(kwargs["model"]),
            usage=_GroqUsage(prompt_tokens=512, completion_tokens=88),
        )


class _FakeGroqChat:
    def __init__(self, owner: _FakeGroq) -> None:
        self.completions = _FakeGroqCompletions(owner)


class _FakeGroq:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.chat = _FakeGroqChat(self)


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "anthropic_api_key": SecretStr("sk-ant-test"),
        "groq_api_key": SecretStr("gsk-test"),
    }
    base.update(overrides)
    return Settings(**base)  # pyright: ignore[reportCallIssue]


# --- (a) provider claude: LLMResponse con campi popolati ---


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
    assert result.prompt_hash  # non vuoto


async def test_claude_uses_exact_model_and_params() -> None:
    fake = _FakeAnthropic()
    client = LLMClient.for_claude(fake, temperature=0.2, seed=42)

    await client.generate(_SYSTEM, _USER)

    call = fake.calls[0]
    assert call["model"] == "claude-sonnet-4-6"
    assert call["max_tokens"] == 1024
    assert call["temperature"] == 0.2
    # system come blocco con cache_control ephemeral (prompt caching)
    assert call["system"] == [
        {"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}
    ]
    assert call["messages"] == [{"role": "user", "content": _USER}]


# --- (b) prompt caching: cache_hit True alla seconda chiamata ---


async def test_claude_prompt_caching_second_call_is_hit() -> None:
    fake = _FakeAnthropic()
    client = LLMClient.for_claude(fake, temperature=0.2, seed=42)

    first = await client.generate(_SYSTEM, _USER)
    second = await client.generate(_SYSTEM, "ZONA: altra zona")

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.tokens_input == 10  # solo i token non cachati


# --- (c) switch provider groq: stesso formato di LLMResponse ---


async def test_groq_returns_same_response_shape() -> None:
    fake = _FakeGroq()
    client = LLMClient.for_groq(fake, temperature=0.2, seed=42)

    result = await client.generate(_SYSTEM, _USER)

    assert isinstance(result, LLMResponse)
    assert result.text == "Analisi del rischio per la zona."
    assert result.llm_used == GROQ_MODEL
    assert result.tokens_input == 512
    assert result.tokens_output == 88
    assert result.cache_hit is False  # Groq non espone prompt caching
    assert result.temperature == 0.2
    assert result.seed == 42
    assert result.prompt_hash


async def test_groq_uses_chat_messages_and_params() -> None:
    fake = _FakeGroq()
    client = LLMClient.for_groq(fake, temperature=0.2, seed=42)

    await client.generate(_SYSTEM, _USER)

    call = fake.calls[0]
    assert call["model"] == "llama-3.1-70b-versatile"
    assert call["max_tokens"] == 1024
    assert call["temperature"] == 0.2
    assert call["seed"] == 42
    assert call["messages"] == [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _USER},
    ]


# --- prompt_hash deterministico e dipendente dal system prompt ---


async def test_prompt_hash_stable_for_same_system() -> None:
    fake = _FakeAnthropic()
    client = LLMClient.for_claude(fake, temperature=0.2, seed=42)

    a = await client.generate(_SYSTEM, _USER)
    b = await client.generate(_SYSTEM, "altro user")
    c = await client.generate("system diverso", _USER)

    assert a.prompt_hash == b.prompt_hash
    assert a.prompt_hash != c.prompt_hash


# --- (d) errore del provider mappato a LLMError ---


async def test_claude_provider_error_is_wrapped() -> None:
    fake = _FakeAnthropic()

    async def _raise(**_kwargs: Any) -> _AnthropicMessage:
        raise RuntimeError("503 overloaded")

    # Sostituisce il metodo create con uno che fallisce.
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


# --- (e) factory + chiave assente ---


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
