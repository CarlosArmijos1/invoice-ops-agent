"""Browser robot: logs into a supplier portal and collects every published invoice.

    uv run python -m opsagent portal-sync                 # store straight into the database
    uv run python -m opsagent portal-sync --api URL       # upload through a remote API

It drives a real headless Chromium with Playwright: it fills the login form,
walks the pagination and downloads each file through the browser, exactly as a
person would. Downloads are ingested by content hash, so running it every few
minutes never creates duplicates.

Selectors rely on roles, labels and `data-testid`, never on layout, so cosmetic
changes to the portal do not break the robot.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from opsagent.infra.logging import get_logger

log = get_logger(__name__)

NAV_TIMEOUT_MS = 20_000
MAX_PAGES = 50  # safety stop against pagination loops


class PortalLoginError(RuntimeError):
    pass


@dataclass
class SyncResult:
    seen: int = 0
    new: int = 0
    already_known: int = 0
    failed: list[str] = field(default_factory=list)


Sink = Callable[[bytes, str], bool]  # (content, filename) -> created?


def _login(page: Page, base_url: str, username: str, password: str) -> None:
    page.goto(f"{base_url}/login", timeout=NAV_TIMEOUT_MS)
    page.get_by_label("Usuario").fill(username)
    page.get_by_label("Contraseña").fill(password)
    page.get_by_role("button", name="Ingresar").click()
    page.wait_for_load_state("domcontentloaded")
    if "/login" in page.url:
        raise PortalLoginError("The portal rejected the credentials")


def sync_portal(base_url: str, username: str, password: str, sink: Sink) -> SyncResult:
    result = SyncResult()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(NAV_TIMEOUT_MS)
        try:
            _login(page, base_url.rstrip("/"), username, password)
            for _ in range(MAX_PAGES):
                links = page.get_by_test_id("download")
                for index in range(links.count()):
                    result.seen += 1
                    try:
                        with page.expect_download() as info:
                            links.nth(index).click()
                        download = info.value
                        content = Path(download.path()).read_bytes()
                        if sink(content, download.suggested_filename):
                            result.new += 1
                        else:
                            result.already_known += 1
                    except (PlaywrightTimeout, OSError, ValueError) as exc:
                        log.warning("portal_download_failed", index=index, error=str(exc)[:200])
                        result.failed.append(f"row {index}: {type(exc).__name__}")
                next_link = page.get_by_role("link", name="Siguiente")
                if next_link.count() == 0:
                    break
                next_link.click()
                page.wait_for_load_state("domcontentloaded")
        finally:
            context.close()
            browser.close()
    log.info("portal_sync_finished", **result.__dict__)
    return result
