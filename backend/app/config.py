"""
Central configuration.

Every secret/API key is read from environment variables (.env), never hard-coded.
See the repository's .env.example for the full list.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py lives in <repo>/backend/app/config.py
ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "backend" / "data"


class Settings(BaseSettings):
    """Application settings loaded from .env files and real environment variables."""

    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", ROOT_DIR / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------------------------------------------------------------- app
    app_name: str = "Scholaris"
    app_env: str = "development"
    api_host: str = "0.0.0.0"  # 0.0.0.0 lets phones on your LAN reach the API
    api_port: int = 8000

    # Browser origins allowed to call the API. Comma-separated; supports regex below.
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:4173,http://127.0.0.1:4173"
    )
    # Allows the Vite dev server on any private LAN IP, so your phone can connect.
    cors_origin_regex: str = r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?"

    # ------------------------------------------------------------ public access
    # Leave empty for local/LAN use (no gate). Set SITE_PASSWORD before putting
    # the app on the public internet: every API route then needs one shared
    # access code, and a signed session cookie is issued after login.
    site_password: str = ""
    session_cookie_name: str = "scholaris_session"
    session_ttl_seconds: int = 30 * 24 * 60 * 60  # 30 days
    # "auto" marks the cookie Secure only when the request came over HTTPS,
    # so LAN logins over http:// still work.
    cookie_secure: str = "auto"
    # Inbound API limits (per client IP, per minute). Separate from the
    # outbound provider rate limiters in the research services.
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 120
    search_rate_limit_per_minute: int = 20
    summarize_rate_limit_per_minute: int = 20
    login_rate_limit_per_minute: int = 8
    # Optional override for the built frontend. Defaults to <repo>/frontend/dist.
    frontend_dist: str = ""

    # ------------------------------------------------------------ scholarly APIs
    # OpenAlex, Crossref and NCBI ask for a contact email ("polite pool").
    contact_email: str = "student@example.com"
    # Optional free key: OpenAlex now budgets anonymous traffic per network.
    # Get one at https://openalex.org/settings/api (free).
    openalex_api_key: str = ""
    # Optional free key: gets higher Semantic Scholar rate limits.
    semantic_scholar_api_key: str = ""
    # Optional free NCBI key: raises PubMed's 3 requests/second limit.
    ncbi_api_key: str = ""
    # Optional free CORE key (open-access aggregator): https://core.ac.uk/services/api
    core_api_key: str = ""

    # ------------------------------------------------------------ caching / limits
    cache_ttl_seconds: int = 15 * 60
    cache_max_entries: int = 256
    search_results_per_provider: int = 30
    request_timeout_seconds: float = 20.0
    max_search_results: int = 50
    # A search must feel instant. Fast providers get a generous window; CORE is
    # best-effort because its API routinely takes 10-20 seconds. Deep search
    # gives slow repository providers a much larger budget when the user opts in.
    search_provider_timeout_seconds: float = 6.0
    search_core_timeout_seconds: float = 4.0
    search_deep_provider_timeout_seconds: float = 20.0
    citation_backfill_timeout_seconds: float = 2.0
    # Concept expansion runs one primary search plus separate modern, historical,
    # per-concept and relationship searches. Extra searches use a smaller
    # provider subset so free APIs are not overwhelmed.
    concept_search_max_queries: int = 5
    concept_search_extra_results: int = 12

    # ------------------------------------------------------------ optional LLM
    # OpenAI-compatible endpoint. Works with OpenRouter free models, Groq's free
    # tier, or a local Ollama server (no key needed for Ollama).
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    llm_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    llm_timeout_seconds: float = 15.0
    # AI notes are generated after the results are already on screen, so they
    # no longer block the search. These limits apply to that background call.
    llm_note_timeout_seconds: float = 15.0
    llm_notes_budget_seconds: float = 3.0  # kept for backwards compatibility
    llm_notes_api_budget_seconds: float = 18.0
    llm_enrich_notes: bool = True
    llm_enrich_limit: int = 3
    # Turn a casual question or a pasted assignment into a proper research
    # phrase before searching. Curated school topics skip this call entirely;
    # unknown topics get a short timeout so a slow model cannot stall search.
    interpret_topic_with_llm: bool = True
    llm_interpret_timeout_seconds: float = 4.0

    # Module 2 — Source Summarizer. The AI writes the structured summary when
    # it is reachable; otherwise a deterministic offline summary is returned.
    summarize_with_llm: bool = True
    summarize_llm_timeout_seconds: float = 30.0
    summarize_llm_max_chars: int = 12_000
    summarize_llm_max_sentences: int = 300

    # Keyless AI. When no LLM_API_KEY is set the app can still get real online
    # AI notes from this free, no-signup OpenAI-compatible endpoint. Set
    # LLM_KEYLESS_FALLBACK=false to disable. (Full URL, not a base URL.)
    llm_keyless_fallback: bool = True
    llm_fallback_url: str = "https://text.pollinations.ai/openai"
    llm_fallback_model: str = "openai"

    # ------------------------------------------------------------ storage
    database_path: Path = Field(default=DATA_DIR / "library.sqlite3")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def llm_enabled(self) -> bool:
        """True when the user configured their own AI endpoint (Ollama needs no key)."""
        is_local = "localhost" in self.llm_base_url or "127.0.0.1" in self.llm_base_url
        return bool(self.llm_api_key) or is_local

    @property
    def llm_available(self) -> bool:
        """True when any AI (user's own or the free keyless one) can be used."""
        return self.llm_enabled or self.llm_keyless_fallback


@lru_cache
def get_settings() -> Settings:
    """Settings are cached so we parse .env only once per process."""
    return Settings()
