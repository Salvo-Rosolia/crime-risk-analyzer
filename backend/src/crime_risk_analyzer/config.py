"""Configurazione centralizzata dell'applicazione.

Carica i parametri da variabili d'ambiente (e da un eventuale file ``.env``)
con validazione tipizzata via ``pydantic-settings``. I segreti (API key) sono
opzionali a questo stadio: la verifica della loro presenza è demandata al
layer LLM, dove servono davvero. I valori segreti usano
``SecretStr`` per evitare leak accidentali in log e ``repr``.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
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
    # Geocoding hardening (#115). ``cache_enabled`` (sopra) gate la cache dei
    # risultati di geocoding (prima setting dichiarato ma inutilizzato).
    # Rate-limit verso Nominatim: policy ~1 req/s -> default 1.0s tra chiamate.
    # Vincolo ``gt=0``: un misconfig da env (0/negativo) e' respinto al load.
    geocoding_min_delay_seconds: float = Field(default=1.0, gt=0)
    # Timeout esplicito per-chiamata al geocoder (un Nominatim lento non appende
    # la pipeline): mappato a GeocoderTimedOut -> GeocodingError -> 503.
    geocoding_timeout_seconds: float = Field(default=10.0, gt=0)
    # Vincola la ricerca alla nazione (evita zone omonime in altri paesi).
    geocoding_country_codes: str = "it"
    default_city: str = "Roma"
    # Citta supportate da ``GET /cities``. Roma/Milano/Napoli sono garantite e
    # testate end-to-end (orchestrator.md); le altre sono best-effort.
    supported_cities: list[str] = ["Roma", "Milano", "Napoli", "Torino", "Firenze"]
    # Allowlist CORS (#106): origini del frontend autorizzate a leggere le
    # risposte dell'API. Allowlist ESPLICITA, mai wildcard ``*`` (una policy
    # ``*`` esporrebbe l'API a qualunque sito) — invariante blindata dal
    # validator ``_reject_cors_wildcard``, non solo dal default. Default in dev:
    # il dev-server di Angular. In prod si sovrascrive con l'origine reale.
    # Parsing da env: come ``supported_cities``, pydantic-settings legge i tipi
    # complessi (``list``) come JSON, quindi
    # ``CORS_ALLOW_ORIGINS='["https://app.example"]'`` (una CSV verrebbe
    # respinta con ``SettingsError``).
    cors_allow_origins: list[str] = ["http://localhost:4200"]

    @field_validator("cors_allow_origins")
    @classmethod
    def _reject_cors_wildcard(cls, origins: list[str]) -> list[str]:
        """Blinda l'allowlist CORS al load (#106): niente wildcard, niente vuoti.

        La garanzia "mai ``*``" non puo' dipendere solo dal default: un valore da
        env (``CORS_ALLOW_ORIGINS='["*"]'``) riaprirebbe altrimenti la policy a
        qualunque sito, in silenzio. Respinge quindi al caricamento con
        ``ValueError`` (mappato da pydantic a ``ValidationError``):

        * il wildcard ``*`` in qualunque elemento;
        * origini vuote o di soli spazi;
        * la lista vuota (che disabiliterebbe di fatto il CORS: piu' probabile un
          misconfig che una scelta intenzionale).
        """
        if not origins:
            raise ValueError(
                "cors_allow_origins non puo' essere vuota: elenca almeno "
                "un'origine (una lista vuota disabiliterebbe di fatto il CORS)."
            )
        for origin in origins:
            if not origin.strip():
                raise ValueError(
                    "cors_allow_origins contiene un'origine vuota o di soli spazi."
                )
            if "*" in origin:
                raise ValueError(
                    f"origine CORS non valida {origin!r}: il wildcard '*' non e' "
                    "ammesso (#106 richiede un'allowlist esplicita)."
                )
        # Normalizza: memorizza le origini trimmate, cosi' uno spazio di troppo
        # non impedisce silenziosamente il match esatto di ``CORSMiddleware``.
        return [origin.strip() for origin in origins]


@lru_cache
def get_settings() -> Settings:
    """Restituisce un'istanza singola di :class:`Settings`.

    Cacheata con ``lru_cache`` così l'app la costruisce una sola volta.
    Iniettabile negli endpoint con ``Depends(get_settings)`` e overridabile
    nei test via ``app.dependency_overrides``.
    """
    return Settings()
