"""The Playwright robot against the mock supplier portal, in a real headless browser."""

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from opsagent.api.main import create_app
from opsagent.domain.schemas import InvoiceSource
from opsagent.infra.db.models import Invoice
from opsagent.settings import Environment, Settings
from tests.integration.scripted import TRUTHS, ScriptedLLM, build_test_container

pytest.importorskip("playwright")
from opsagent.portal.robot import PortalLoginError, sync_portal
from opsagent.portal.sinks import database_sink

pytestmark = pytest.mark.integration

PORTAL_FILES = {name for name, t in TRUTHS.items() if t.channel == "portal"}


@pytest.fixture
def portal_url(session_factory: sessionmaker[Session]) -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    settings = Settings(environment=Environment.TEST)
    app = create_app(settings, build_test_container(session_factory, ScriptedLLM(), settings))
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("portal server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/portal"
    server.should_exit = True
    thread.join(timeout=10)


def _browser_available() -> bool:
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _needs_chromium() -> None:
    if not _browser_available():
        pytest.skip("Chromium not installed (uv run playwright install chromium)")


def test_robot_logs_in_paginates_downloads_and_is_idempotent(
    portal_url: str, session_factory: sessionmaker[Session]
) -> None:
    settings = Settings()
    password = settings.portal_password.get_secret_value()
    sink = database_sink(session_factory)

    first = sync_portal(portal_url, settings.portal_username, password, sink)
    second = sync_portal(portal_url, settings.portal_username, password, sink)

    assert first.seen == len(PORTAL_FILES) > 4  # more than one page
    assert first.new == len(PORTAL_FILES)
    assert first.failed == []
    assert (second.new, second.already_known) == (0, len(PORTAL_FILES))
    with session_factory() as session:
        stored = session.scalars(
            select(Invoice.original_filename).where(Invoice.source == InvoiceSource.PORTAL)
        ).all()
    assert set(stored) == PORTAL_FILES


def test_wrong_credentials_fail_loudly(portal_url: str) -> None:
    with pytest.raises(PortalLoginError):
        sync_portal(portal_url, "compras@cooperativa.example", "wrong", lambda c, n: True)
