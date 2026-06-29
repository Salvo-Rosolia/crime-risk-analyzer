"""Client LLM provider-agnostico: Claude (Anthropic) + Llama (Groq) (#20).

Wrapper sottile e *async* sopra i due SDK ufficiali, con un'unica superficie
pubblica :meth:`LLMClient.generate`. Lo switch tra provider avviene via
``settings.LLM_PROVIDER`` (factory :func:`build_llm_client`); per Claude il
system prompt viaggia come blocco con ``cache_control: ephemeral`` per abilitare
il prompt caching di Anthropic (su una seconda richiesta con lo stesso system
prompt ``cache_hit`` risulta ``True``).

Confini (orchestrator.md / generation.md): questo modulo NON costruisce il
system prompt di dominio ne' assembla il contesto RAG (responsabilita' di #23);
riceve ``system_prompt`` e ``user_content`` gia' pronti. Niente scoring numerico
di pericolosita': qui si genera solo la narrativa grezza e i metadati di
riproducibilita'.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from crime_risk_analyzer.config import Settings, get_settings

#: Versione esatta del modello Claude (non un alias) — generation.md §Riproducibilita'.
CLAUDE_MODEL = "claude-sonnet-4-6"

#: Modello Llama su Groq per il confronto sperimentale — generation.md.
#: ``llama-3.1-70b-versatile`` e' stato dismesso da Groq; il sostituto attuale
#: e' ``llama-3.3-70b-versatile`` (Groq production models, console.groq.com).
GROQ_MODEL = "llama-3.3-70b-versatile"

#: Parametri fissi condivisi (generation.md §Riproducibilita').
_MAX_TOKENS = 1024
_DEFAULT_TEMPERATURE = 0.2
_DEFAULT_SEED = 42

Provider = Literal["claude", "groq"]


class LLMError(RuntimeError):
    """Errore del layer LLM: chiave assente o fallimento del provider.

    Le eccezioni degli SDK (rate limit, 5xx, rete) vengono incapsulate qui,
    cosi' l'orchestrator puo' mapparle a una risposta HTTP senza conoscere i
    tipi specifici di Anthropic/Groq.
    """


class LLMResponse(BaseModel):
    """Esito di una generazione, indipendente dal provider.

    Espone la narrativa e i metadati di riproducibilita' (``temperature``,
    ``seed``, ``prompt_hash``) richiesti dal blocco ``repro`` di ``/analyze``.
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


# --- superfici minime degli SDK (DI + testabilita') ---
#
# Si tipizzano solo i metodi effettivamente usati: i client reali
# ``anthropic.AsyncAnthropic`` / ``groq.AsyncGroq`` soddisfano questi Protocol
# in modo strutturale, e i test iniettano dei doppi leggeri senza toccare la rete.


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
    """Hash stabile del system prompt per il versionamento (campo ``repro``)."""
    return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()


class LLMClient:
    """Client async che astrae Claude e Groq dietro :meth:`generate`.

    Non istanziare gli SDK qui dentro: vengono iniettati (via i costruttori di
    classe :meth:`for_claude`/:meth:`for_groq` o la factory
    :func:`build_llm_client`), cosi' i test passano dei doppi e non si crea
    stato globale.
    """

    def __init__(
        self,
        *,
        provider: Provider,
        anthropic_client: _AnthropicClient | None = None,
        groq_client: _GroqClient | None = None,
        temperature: float = _DEFAULT_TEMPERATURE,
        seed: int = _DEFAULT_SEED,
    ) -> None:
        self._provider: Provider = provider
        self._anthropic = anthropic_client
        self._groq = groq_client
        self._temperature = temperature
        self._seed = seed

    @classmethod
    def for_claude(
        cls,
        anthropic_client: _AnthropicClient,
        *,
        temperature: float = _DEFAULT_TEMPERATURE,
        seed: int = _DEFAULT_SEED,
    ) -> LLMClient:
        """Costruisce un client che usa Claude via l'SDK Anthropic iniettato."""
        return cls(
            provider="claude",
            anthropic_client=anthropic_client,
            temperature=temperature,
            seed=seed,
        )

    @classmethod
    def for_groq(
        cls,
        groq_client: _GroqClient,
        *,
        temperature: float = _DEFAULT_TEMPERATURE,
        seed: int = _DEFAULT_SEED,
    ) -> LLMClient:
        """Costruisce un client che usa Llama via l'SDK Groq iniettato."""
        return cls(
            provider="groq",
            groq_client=groq_client,
            temperature=temperature,
            seed=seed,
        )

    def with_temperature(self, temperature: float, seed: int = 0) -> LLMClient:
        """Nuovo client che riusa lo stesso SDK iniettato con temperature/seed fissati.

        Usato dalla pipeline di valutazione per il determinismo (temperature=0).
        Accedere a ``self._anthropic``/``self._groq`` e' lecito all'interno della
        stessa classe.
        """
        return LLMClient(
            provider=self._provider,
            anthropic_client=self._anthropic,
            groq_client=self._groq,
            temperature=temperature,
            seed=seed,
        )

    @property
    def provider(self) -> Provider:
        """Provider attivo (``claude`` o ``groq``)."""
        return self._provider

    @property
    def model(self) -> str:
        """Model id esatto del provider attivo."""
        return CLAUDE_MODEL if self._provider == "claude" else GROQ_MODEL

    async def generate(self, system_prompt: str, user_content: str) -> LLMResponse:
        """Genera la narrativa per il ``system_prompt``/``user_content`` dati.

        Solleva :class:`LLMError` se il provider fallisce. Per Claude il system
        prompt e' inviato come blocco con ``cache_control: ephemeral``: la
        seconda richiesta con lo stesso system prompt risulta ``cache_hit=True``.
        """
        if self._provider == "claude":
            return await self._generate_claude(system_prompt, user_content)
        return await self._generate_groq(system_prompt, user_content)

    async def _generate_claude(
        self, system_prompt: str, user_content: str
    ) -> LLMResponse:
        assert self._anthropic is not None  # garantito dalla factory/costruttore
        try:
            message = await self._anthropic.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=_MAX_TOKENS,
                temperature=self._temperature,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception as exc:  # noqa: BLE001 — incapsula qualunque errore SDK
            raise LLMError(f"Generazione Claude fallita: {exc}") from exc

        usage = message.usage
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        return LLMResponse(
            text=_extract_anthropic_text(message),
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
        assert self._groq is not None  # garantito dalla factory/costruttore
        try:
            completion = await self._groq.chat.completions.create(
                model=GROQ_MODEL,
                max_tokens=_MAX_TOKENS,
                temperature=self._temperature,
                seed=self._seed,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            )
        except Exception as exc:  # noqa: BLE001 — incapsula qualunque errore SDK
            raise LLMError(f"Generazione Groq fallita: {exc}") from exc

        usage = completion.usage
        return LLMResponse(
            text=str(completion.choices[0].message.content or ""),
            llm_used=str(completion.model),
            tokens_input=int(usage.prompt_tokens),
            tokens_output=int(usage.completion_tokens),
            cache_hit=False,  # Groq non espone prompt caching
            temperature=self._temperature,
            seed=self._seed,
            prompt_hash=_prompt_hash(system_prompt),
        )


def _extract_anthropic_text(message: Any) -> str:
    """Concatena i blocchi di testo della risposta Anthropic (ignora il resto)."""
    parts: list[str] = []
    for block in message.content:
        if getattr(block, "type", None) == "text":
            parts.append(str(block.text))
    return "".join(parts)


def build_llm_client(settings: Settings) -> LLMClient:
    """Costruisce il :class:`LLMClient` dal provider configurato in ``settings``.

    Istanzia l'SDK del provider attivo con la chiave da ``settings`` (mai
    hardcodata). Solleva :class:`LLMError` se la chiave necessaria manca.
    Iniettabile negli endpoint via ``Depends``.
    """
    if settings.llm_provider == "claude":
        if settings.anthropic_api_key is None:
            raise LLMError(
                "ANTHROPIC_API_KEY mancante: necessaria con LLM_PROVIDER=claude"
            )
        from anthropic import AsyncAnthropic

        anthropic_client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
        # L'SDK reale soddisfa `_AnthropicClient` a runtime (stessa superficie
        # `messages.create`), ma la sua firma keyword-only non e' riconosciuta
        # strutturalmente compatibile con il Protocol `**kwargs` da pyright
        # strict. Ignore puntuale sul solo punto di adattamento SDK->Protocol.
        return LLMClient.for_claude(anthropic_client)  # pyright: ignore[reportArgumentType]

    if settings.groq_api_key is None:
        raise LLMError("GROQ_API_KEY mancante: necessaria con LLM_PROVIDER=groq")
    from groq import AsyncGroq

    groq_client = AsyncGroq(api_key=settings.groq_api_key.get_secret_value())
    # Stessa ragione del ramo Claude: adattamento SDK->Protocol al confine.
    return LLMClient.for_groq(groq_client)  # pyright: ignore[reportArgumentType]


@lru_cache
def get_llm_client() -> LLMClient:
    """Provider DI cached del client LLM costruito dal provider configurato."""
    return build_llm_client(get_settings())
