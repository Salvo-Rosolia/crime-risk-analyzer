"""Configurazione centralizzata dell'applicazione.

Carica i parametri da variabili d'ambiente (e da un eventuale file ``.env``)
con validazione tipizzata via ``pydantic-settings``. I segreti (API key) sono
opzionali a questo stadio: la verifica della loro presenza è demandata al
layer LLM (fase P2), dove servono davvero. I valori segreti usano
``SecretStr`` per evitare leak accidentali in log e ``repr``.
"""

from typing import Literal

from pydantic import SecretStr
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
    cache_enabled: bool = True
    default_city: str = "Roma"
