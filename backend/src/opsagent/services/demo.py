"""Reset the public demo to its initial state (visitors approve/reject invoices freely)."""

from sqlalchemy import text

from opsagent.bootstrap import bootstrap_demo
from opsagent.container import Container
from opsagent.infra.logging import get_logger
from opsagent.settings import Environment

log = get_logger(__name__)

# Everything produced by the agent or by visitors; master data (vendors, POs, payments) stays.
_TABLES = (
    "llm_calls",
    "audit_events",
    "decisions",
    "extractions",
    "invoices",
    "invoice_files",
    "agent_runs",
    "daily_reports",
)
_CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")


class DemoResetNotAllowedError(RuntimeError):
    pass


def reset_demo(container: Container) -> None:
    if container.settings.environment not in (Environment.DEMO, Environment.LOCAL):
        raise DemoResetNotAllowedError("Demo reset is only available in demo/local environments")
    with container.session_factory() as session, session.begin():
        session.execute(text(f"TRUNCATE {', '.join(_TABLES)} CASCADE"))
        existing = set(
            session.scalars(
                text("SELECT tablename FROM pg_tables WHERE tablename = ANY(:names)"),
                {"names": list(_CHECKPOINT_TABLES)},
            )
        )
        if existing:
            session.execute(text(f"TRUNCATE {', '.join(sorted(existing))}"))
    bootstrap_demo(container)
    log.info("demo_reset")
