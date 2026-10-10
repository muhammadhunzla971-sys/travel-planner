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
    llm_provider: str = "groq"  # groq | gemini
    llm_model: str = "llama-3.3-70b-versatile"
    groq_api_key: str = ""
    gemini_api_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
