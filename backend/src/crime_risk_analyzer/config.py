"""Configurazione centralizzata dell'applicazione.

Carica i parametri da variabili d'ambiente (e da un eventuale file ``.env``)
con validazione tipizzata via ``pydantic-settings``. I segreti (API key) sono
opzionali a questo stadio: la verifica della loro presenza è demandata al
layer LLM (fase P2), dove servono davvero. I valori segreti usano
``SecretStr`` per evitare leak accidentali in log e ``repr``.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Parametri di configurazione del backend, popolati da env/``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    ontology_path: str = "ontology/terminus_crime_materialized.ttl"
    llm_provider: Literal["claude", "groq"] = "claude"
    # Timeout (secondi) del layer LLM (#114): applicato sia come ``timeout=``
    # sull'SDK Anthropic/Groq sia come ceiling esplicito via ``asyncio.wait_for``
    # nel client, cosi' un provider lento/appeso non lascia ``POST /analyze``
    # bloccato a tempo indeterminato. Il timeout scaduto e' mappato a
    # ``LLMError`` -> fallback strutturato 200 dell'orchestrator (non un 500).
    # Vincolo ``gt=0``: un misconfig da env (0/negativo) viene respinto al load,
    # non lasciato esplodere nel layer LLM a runtime.
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    # Tetto di token di output della generazione (Anthropic/Groq ``max_tokens``).
    # Default storico 1024 (generation.md §Riproducibilita'); configurabile per
    # tuning senza toccare il codice. Vincolo ``ge=1``: almeno 1 token.
    llm_max_tokens: int = Field(default=1024, ge=1)
    cache_enabled: bool = True
    default_city: str = "Roma"
    # Citta supportate da ``GET /cities``. Roma/Milano/Napoli sono garantite e
    # testate end-to-end (orchestrator.md); le altre sono best-effort.
    supported_cities: list[str] = ["Roma", "Milano", "Napoli", "Torino", "Firenze"]


@lru_cache
def get_settings() -> Settings:
    """Restituisce un'istanza singola di :class:`Settings`.

    Cacheata con ``lru_cache`` così l'app la costruisce una sola volta.
    Iniettabile negli endpoint con ``Depends(get_settings)`` e overridabile
    nei test via ``app.dependency_overrides``.
    """
    return Settings()
