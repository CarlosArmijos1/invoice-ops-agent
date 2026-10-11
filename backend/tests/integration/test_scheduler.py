import shutil
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from opsagent.infra.db.models import Invoice
from opsagent.scheduler.jobs import LOCK_PROCESS, process_tick
from opsagent.services.reporting import build_daily_report
from opsagent.settings import Environment, Settings
from tests.integration.scripted import DATA, ScriptedLLM, build_test_container, truth_for

pytestmark = pytest.mark.integration


def test_tick_ingests_the_inbox_processes_and_archives(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    truth = truth_for("clean_unpaid")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    shutil.copy(DATA / "invoices" / truth.file, inbox / truth.file)
    (inbox / "readme.txt").write_text("ignored")
    llm = ScriptedLLM()
    llm.current = truth
    container = build_test_container(
        session_factory, llm, Settings(environment=Environment.TEST, inbox_dir=inbox)
    )

    result = process_tick(container)

    assert result["ingested"] == 1
    assert result["processed"] == 1
    assert (inbox / "_procesadas" / truth.file).exists()
    assert not (inbox / truth.file).exists()
    assert (inbox / "readme.txt").exists()


def test_tick_is_skipped_while_another_instance_holds_the_lock(
    session_factory: sessionmaker[Session], db_engine: Engine
) -> None:
    container = build_test_container(session_factory, ScriptedLLM())
    with db_engine.connect() as other_instance:
        other_instance.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_PROCESS})
        try:
            assert process_tick(container) == {"skipped": True}
        finally:
            other_instance.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_PROCESS})


def test_daily_report_lists_payments_without_invoice_and_stale_orders(
    session_factory: sessionmaker[Session],
) -> None:
    container = build_test_container(session_factory, ScriptedLLM())
    with container.session_factory() as session:
        summary = build_daily_report(session, date(2026, 10, 11))
        invoices = session.scalar(select(func.count()).select_from(Invoice))

    assert invoices == 0
    assert summary["processed"] == 0
    # Nothing processed yet: every payment lacks an invoice, every old PO is stale.
    assert len(summary["payments_without_invoice"]) == 20
    assert summary["stale_purchase_orders"]
