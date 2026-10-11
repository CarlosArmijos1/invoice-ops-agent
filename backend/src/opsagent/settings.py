"""Application settings, loaded from environment variables (and `.env` in development)."""

from decimal import Decimal
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
    REPLAY = "replay"  # only use saved cassettes (CI, evals)
    HYBRID = "hybrid"  # saved cassette if any, else live (docker compose, public demo)


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
    log_stream: str = "stdout"  # "stderr" for the MCP stdio server

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

    # --- Demo bootstrap ---
    bootstrap_demo: bool = False  # on start: seed catalog and preload the synthetic invoices
    demo_dataset_dir: Path = REPO_ROOT / "data" / "synthetic"

    # --- Scheduler ---
    scheduler_enabled: bool = False  # true in the worker (or in the single web instance)
    process_interval_minutes: int = 5
    daily_report_hour: int = 7  # local time, America/Guayaquil
    inbox_dir: Path | None = None  # folder watched for new invoices

    # --- API / demo safety ---
    admin_token: SecretStr | None = None  # required for operator endpoints when set
    upload_limit_per_hour: int = 20  # per client IP, protects the LLM quota in the demo
    cors_origins: list[str] = ["http://localhost:5173"]

    # --- Supplier portal (mock portal served by this app + Playwright robot) ---
    portal_enabled: bool = True  # serve the demo supplier portal at /portal
    portal_sync_enabled: bool = False  # scheduler job; needs Chromium (worker image)
    portal_sync_interval_minutes: int = 15
    portal_url: str = "http://localhost:8000/portal"
    portal_username: str = "compras@cooperativa.example"
    # Demo-only credentials of the mock portal above; override in any real setup.
    portal_password: SecretStr = SecretStr("portal-demo-2026")

    # --- Agent ---
    investigate: bool = True  # tool-calling investigator for non-approved invoices
    max_processing_attempts: int = 5  # after this, an invoice stays FAILED for a human
    claim_timeout_minutes: int = 15  # a claim older than this belongs to a crashed worker

    # --- Business policy ---
    own_tax_id: str = "1191734929001"  # the buying company (demo); never a vendor
    amount_tolerance_abs: Decimal = Decimal("1.00")
    amount_tolerance_pct: Decimal = Decimal("0.005")
    auto_approval_limit: Decimal = Decimal("5000.00")
    min_quality_score: float = 0.7


@lru_cache
def get_settings() -> Settings:
    return Settings()
