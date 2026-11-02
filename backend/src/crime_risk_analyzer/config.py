"""Centralised application configuration.

Loads parameters from environment variables (and from an optional ``.env`` file)
with typed validation via ``pydantic-settings``. Secrets (API keys) are
optional at this stage: checking that they are present is left to the LLM layer,
where they are actually needed. Secret values use ``SecretStr`` to avoid
accidental leaks in logs and ``repr``.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend configuration parameters, populated from env/``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    ontology_path: str = "ontology/terminus_crime_materialized.ttl"
    llm_provider: Literal["claude", "groq"] = "claude"
    # Timeout (seconds) of the LLM layer (#114): applied both as ``timeout=`` on
    # the Anthropic/Groq SDK and as an explicit ceiling via ``asyncio.wait_for``
    # in the client, so a slow/hung provider does not leave ``POST /analyze``
    # blocked indefinitely. The expired timeout is mapped to ``LLMError`` ->
    # structured 200 fallback of the orchestrator (not a 500).
    # ``gt=0`` constraint: an env misconfig (0/negative) is rejected at load, not
    # left to blow up in the LLM layer at runtime.
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    # Cap on generation output tokens (Anthropic/Groq ``max_tokens``).
    # #229: raised 1024 -> 1536 to give anti-truncation margin on the dense case
    # with the more analytical narrative (anti-truncation guard unchanged:
    # finish=stop -> LLMError -> fallback). MUST stay in sync with
    # ``generation.DEFAULT_MAX_TOKENS`` and ``llm.client._MAX_TOKENS``
    # (test_generation::..._synced_across_modules).
    # The total request budget (``llm_request_token_budget``) stays under the TPM
    # of the model in use (gpt-oss-120b on Groq = 8,000, #345 D14).
    # Configurable for tuning without touching the code. ``ge=1`` constraint.
    llm_max_tokens: int = Field(default=1536, ge=1)
    # Maximum (ESTIMATED) token cap of the WHOLE LLM request (#210): it covers
    # system prompt + user_content + the ``llm_max_tokens`` reserved for the
    # output, NOT just user_content. The generation layer derives the allowance for
    # user_content by subtracting the system prompt estimate and
    # ``llm_max_tokens`` from this cap, then GREEDILY includes by relevance only
    # the POIs that fit (map/list/confidence_summary stay complete). So on a dense
    # zone the whole request does not exceed the provider's TPM limit.
    # It must stay under the TPM of the model in use: gpt-oss-120b on Groq = 8,000
    # tokens per minute, counting input and ``max_tokens`` (#345, D14). Measured
    # with the real tokenizer on the 4 evaluation zones, ISTAT on and off
    # (``scripts/istat_budget.py``): 8700 is the highest value with all
    # requests under 7,600. ``ge=1`` constraint: an env misconfig (0/negative)
    # is rejected at load, not left to degenerate at runtime.
    llm_request_token_budget: int = Field(default=8700, ge=1)
    # ISTAT data in the narrative (#345, D6): on by default in the app. Off, the
    # prompt and behaviour are identical to before #345 (grounding still computes
    # the rows: the switch acts only on the prompt and the figures check). On,
    # startup fails if the package data is missing or not valid
    # (``main.lifespan``). The evaluation does NOT read it: it uses
    # ``ExperimentConfig.istat`` (off by default, the thesis comparison).
    # Since #346 it also decides whether ``poi[].istat`` reaches the client in
    # phase 1 of ``/analyze`` (``main.analyze``): it is the data the frontend
    # uses to order the risks in the POI Detail.
    istat_context_enabled: bool = True
    # Mode of the ISTAT data in the zone narrative (#366): off = the model writes
    # the sentences (#365); on = the model chooses for each risk the ISTAT item
    # and the weight, and the app composes the sentences. Acts only with
    # ``istat_context_enabled`` on. Opt-in until the evaluation says it
    # improves things (#368/#369).
    istat_scelta_modello: bool = False
    # User-uploaded sources (#416): the set is valid for the session and expires
    # after this time from last use (sliding window). The session cap limits
    # memory (each set keeps in RAM an OWL graph of up to 20 MB): beyond it, the
    # session with the nearest expiry is evicted.
    sources_session_ttl_seconds: float = Field(default=3600.0, gt=0)
    sources_max_sessions: int = Field(default=8, ge=1)
    # Concurrent uploads/parses of ``POST /sources``: parsing a 20 MB file is CPU
    # and RAM. Beyond the cap the route answers 503 immediately (Retry-After)
    # instead of queueing: no queue of open connections with the body waiting.
    sources_max_concurrent_uploads: int = Field(default=2, ge=1)
    cache_enabled: bool = True
    # Geocoding hardening (#115). ``cache_enabled`` (above) gates the cache of
    # geocoding results (previously a declared but unused setting).
    #
    # single-worker DEPLOY NOTE (#170): the rate limit and the geocoding cache are
    # PER-PROCESS (the RateLimiter and ``_CACHE`` are module state). With a
    # multi-worker deploy (``uvicorn --workers N``) each worker has its own
    # limiter -> up to N req/s towards Nominatim, while the policy is "1 req/s
    # ABSOLUTE". To respect the ToS: SINGLE-WORKER deploy (or a throttle shared
    # across processes, not foreseen here). It also holds for the local boundary
    # limiter in ``eval/city_agnostic.py``.
    #
    # Rate limit towards Nominatim: the policy is "1 req/s absolute". 1.0s would
    # be EXACTLY the cap; the 1.1s default gives ~10% margin to absorb jitter and
    # the cache-hit-followed-by-miss case without exceeding the policy.
    # ``gt=0`` constraint: an env misconfig (0/negative) is rejected at load.
    geocoding_min_delay_seconds: float = Field(default=1.1, gt=0)
    # Explicit per-call timeout to the geocoder (a slow Nominatim does not hang
    # the pipeline): mapped to GeocoderTimedOut -> GeocodingError -> 503.
    geocoding_timeout_seconds: float = Field(default=10.0, gt=0)
    # Restricts the search to the country (avoids homonymous zones in other
    # countries).
    geocoding_country_codes: str = "it"
    # Minimum size floor of the Nominatim bbox (#204). When a zone resolves to a
    # point/building feature (e.g. "Colosseo"), Nominatim returns a
    # ``boundingbox`` as big as the monument (~150 m): in that box Overpass finds
    # 0 POIs and ``/analyze`` answers an empty 200 (map not re-centred). This is
    # the minimum half-span (in degrees) imposed on the bbox, expanding
    # SYMMETRICALLY around the midpoint (never shrinking a bbox already larger
    # than the threshold), so a landmark zone keeps a usable Overpass search area
    # (~0.5 km lat / ~0.37 km lon at the latitude of Rome, i.e. ~500 m radius).
    # #212 reduced the default to 0.0045 (= 500 m / 111320) for results closer to
    # the indicated zone (it was 0.01 = ~1.1 km). ``gt=0`` constraint: an env
    # misconfig (0/negative) is rejected at load, not left to degenerate into a
    # null bbox at runtime.
    geocoding_min_bbox_half_span_deg: float = Field(default=0.0045, gt=0)
    # Limits of the search radius drawn on the map (#318): they keep the cost of
    # Overpass/LLM under control on huge circles. ``gt=0`` constraint: an env
    # misconfig (0/negative) is rejected at load.
    search_radius_min_m: float = Field(default=150.0, gt=0)
    search_radius_max_m: float = Field(default=3000.0, gt=0)
    default_city: str = "Roma"
    # SUGGESTED cities, exposed as autocomplete by ``GET /cities`` — NOT a
    # validation constraint (#191): the city + zone mode of
    # ``POST /analyze``/``/analyze/baseline`` accepts any Italian city and passes
    # it to geocoding (restricted to Italy via ``geocoding_country_codes``);
    # a non-existent city/zone fails cleanly at geocoding (422).
    # Roma/Milano/Napoli are guaranteed and tested end-to-end (orchestrator.md);
    # the others are best-effort.
    supported_cities: list[str] = ["Roma", "Milano", "Napoli", "Torino", "Firenze"]
    # CORS allowlist (#106): frontend origins authorised to read the API
    # responses. EXPLICIT allowlist, never wildcard ``*`` (a ``*`` policy would
    # expose the API to any site) — invariant enforced by the
    # ``_reject_cors_wildcard`` validator, not just by the default. Default in dev:
    # the Angular dev-server. In prod it is overridden with the real origin.
    # Parsing from env: pydantic-settings reads complex types (``list``) as
    # JSON, so ``CORS_ALLOW_ORIGINS='["https://app.example"]'`` (a CSV
    # would be rejected with ``SettingsError``).
    cors_allow_origins: list[str] = ["http://localhost:4200"]

    @field_validator("cors_allow_origins")
    @classmethod
    def _reject_cors_wildcard(cls, origins: list[str]) -> list[str]:
        """Locks the CORS allowlist at load (#106): no wildcard, no empties.

        The "never ``*``" guarantee cannot depend only on the default: an env value
        (``CORS_ALLOW_ORIGINS='["*"]'``) would otherwise silently reopen the policy
        to any site. It therefore rejects at load with ``ValueError`` (mapped by
        pydantic to ``ValidationError``):

        * the ``*`` wildcard in any element;
        * empty or whitespace-only origins;
        * the empty list (which would effectively disable CORS: more likely a
          misconfig than an intentional choice).
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
        # Normalise: store the trimmed origins, so a stray space does not
        # silently prevent the exact match of ``CORSMiddleware``.
        return [origin.strip() for origin in origins]

    @field_validator("geocoding_country_codes")
    @classmethod
    def _reject_blank_country_codes(cls, value: str) -> str:
        """Rejects an empty ``country_codes`` at load (#115): explicit fail-fast.

        An empty or whitespace-only string would SILENTLY disable the Nominatim
        country filter (the ``country_codes`` parameter would effectively be
        ignored), returning homonymous zones in the wrong country. Better to
        reject at load with ``ValueError`` (mapped by pydantic to
        ``ValidationError``).

        Commas are NOT rejected: Nominatim accepts several country codes
        (e.g. ``"it,sm"``). Normalises with ``strip()`` so a stray space at the
        edges does not alter the value sent to the service.
        """
        if not value.strip():
            raise ValueError(
                "geocoding_country_codes non puo' essere vuoto o di soli spazi: "
                "una stringa vuota disattiverebbe silenziosamente il filtro "
                "nazione di Nominatim (risultati nella nazione sbagliata)."
            )
        return value.strip()

    @model_validator(mode="after")
    def _reject_radius_bounds_inverted(self) -> "Settings":
        """Rejects the configuration with minimum radius >= maximum (#318).

        The invariant ``search_radius_min_m < search_radius_max_m`` must hold
        at load to prevent an env misconfig (e.g. an accidental swap of the
        values) from being silently used at runtime, introducing inconsistent
        validation logic in the orchestration layer.
        """
        if self.search_radius_min_m >= self.search_radius_max_m:
            raise ValueError(
                "search_radius_min_m deve essere minore di search_radius_max_m"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Returns a single instance of :class:`Settings`.

    Cached with ``lru_cache`` so the app builds it only once.
    Injectable into endpoints with ``Depends(get_settings)`` and overridable
    in tests via ``app.dependency_overrides``.
    """
    return Settings()
