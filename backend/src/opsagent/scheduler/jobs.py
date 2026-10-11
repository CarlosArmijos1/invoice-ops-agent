"""Unattended operation: poll the inbox, process pending invoices, publish the daily report.

Every job takes a Postgres advisory lock first. If two instances are running
(a scaled web service, or the worker plus a manual trigger), only one of them
does the work and the others skip that tick instead of racing.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from opsagent.container import Container
from opsagent.infra.logging import get_logger
from opsagent.services.ingestion import ingest_folder
from opsagent.services.reporting import TZ, generate_daily_report

log = get_logger(__name__)

LOCK_PROCESS = 7_310_001
LOCK_REPORT = 7_310_002


@contextmanager
def advisory_lock(container: Container, key: int) -> Iterator[bool]:
    with container.session_factory() as session:
        acquired = bool(session.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}))
        try:
            yield acquired
        finally:
            if acquired:
                session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
                session.commit()


def process_tick(container: Container, trigger: str = "schedule") -> dict[str, object]:
    with advisory_lock(container, LOCK_PROCESS) as acquired:
        if not acquired:
            log.info("tick_skipped_lock_held")
            return {"skipped": True}
        inbox = container.settings.inbox_dir
        ingested = 0
        if inbox is not None and Path(inbox).is_dir():
            ingested = sum(r.created for r in ingest_folder(container.session_factory, inbox))
        summary = container.processor.process_pending(trigger=trigger)
        return {"ingested": ingested, **summary.as_dict()}


def report_tick(container: Container, day_offset: int = -1) -> str | None:
    """By default reports on *yesterday*, run early in the morning (Ecuador time)."""
    with advisory_lock(container, LOCK_REPORT) as acquired:
        if not acquired:
            return None
        day = (datetime.now(TZ) + timedelta(days=day_offset)).date()
        with container.session_factory() as session, session.begin():
            report = generate_daily_report(session, day)
            log.info("daily_report_generated", day=day.isoformat())
            return report.markdown


def _safe(job: Callable[[], object], name: str) -> Callable[[], None]:
    def run() -> None:
        try:
            job()
        except Exception:  # a failing tick must never kill the scheduler
            log.exception("scheduled_job_failed", job=name)

    return run


def build_scheduler(container: Container) -> BackgroundScheduler:
    settings = container.settings
    scheduler = BackgroundScheduler(timezone=TZ)
    scheduler.add_job(
        _safe(lambda: process_tick(container), "process"),
        IntervalTrigger(minutes=settings.process_interval_minutes),
        id="process",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(TZ) + timedelta(seconds=10),
    )
    scheduler.add_job(
        _safe(lambda: report_tick(container), "daily_report"),
        CronTrigger(hour=settings.daily_report_hour, minute=0),
        id="daily_report",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
