"""Central settings. All secrets come from environment variables only."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI Travel Planner"
    app_version: str = "0.1.0"
    environment: str = "development"  # development | production

    # Comma-separated list of allowed frontend origins, e.g.
    # "https://my-app.vercel.app,http://localhost:3000"
    cors_origins: str = "*"

    # LLM (hosted API only - nothing runs locally)
    # NOTE: Groq retired llama-3.3-70b-versatile and llama-3.1-8b-instant on 2026-08-16.
    llm_provider: str = "groq"
    llm_model: str = "openai/gpt-oss-120b"
    llm_fallback_model: str = "openai/gpt-oss-20b"  # tried if the main model errors/rate-limits
    groq_api_key: str = ""        # set ONLY as an environment variable (never in code/chat)
    llm_enabled: bool = True      # kill switch: LLM_ENABLED=false -> rule-based only
    llm_timeout_s: float = 8.0    # per LLM call (serverless functions are short-lived)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
