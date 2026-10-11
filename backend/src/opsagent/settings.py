"""Application settings, loaded from environment variables (and `.env` in development)."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    DEMO = "demo"
    PRODUCTION = "production"


class LLMMode(StrEnum):
    LIVE = "live"  # call the provider
    RECORD = "record"  # call the provider and save responses as cassettes
    REPLAY = "replay"  # only use saved cassettes (CI, evals, public demo)


REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = Environment.LOCAL
    log_level: str = "INFO"
    log_json: bool = False

    database_url: str = "postgresql+psycopg://opsagent:opsagent@localhost:5433/opsagent"

    # --- LLM ---
    groq_api_key: SecretStr | None = None
    vision_model: str = "qwen/qwen3.8-27b"
    reasoning_model: str = "openai/gpt-oss-120b"
    reasoning_effort: str = "low"  # gpt-oss: extraction does not need long reasoning
    llm_mode: LLMMode = LLMMode.LIVE
    cassette_dir: Path = REPO_ROOT / "evals" / "cassettes"
    llm_timeout_s: float = 60.0
    llm_max_attempts: int = 4  # transport-level retries (timeouts, 429, 5xx)
    extraction_max_attempts: int = 3  # self-correction rounds on invalid JSON

    # --- Business ---
    own_tax_id: str = "1191734929001"  # the buying company (demo); never a vendor


@lru_cache
def get_settings() -> Settings:
    return Settings()
