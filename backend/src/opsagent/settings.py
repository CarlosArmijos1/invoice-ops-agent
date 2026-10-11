"""Application settings, loaded from environment variables (and `.env` in development)."""

from enum import StrEnum
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    DEMO = "demo"
    PRODUCTION = "production"


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

    groq_api_key: SecretStr | None = None
    vision_model: str = "qwen/qwen3.8-27b"
    reasoning_model: str = "openai/gpt-oss-120b"


@lru_cache
def get_settings() -> Settings:
    return Settings()
