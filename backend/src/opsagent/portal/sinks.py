"""Where the robot puts what it downloads: straight into the DB, or through a remote API."""

import httpx
from sqlalchemy.orm import Session, sessionmaker

from opsagent.domain.schemas import InvoiceSource
from opsagent.portal.robot import Sink
from opsagent.services.ingestion import ingest_bytes


def database_sink(session_factory: sessionmaker[Session]) -> Sink:
    def store(content: bytes, filename: str) -> bool:
        with session_factory() as session, session.begin():
            return ingest_bytes(session, content, filename, InvoiceSource.PORTAL).created

    return store


def api_sink(api_base: str, admin_token: str | None) -> Sink:
    """Upload through the public API (used by the GitHub Actions cron against the demo)."""
    headers = {"X-Admin-Token": admin_token} if admin_token else {}
    client = httpx.Client(base_url=api_base.rstrip("/"), headers=headers, timeout=60)

    def upload(content: bytes, filename: str) -> bool:
        response = client.post("/api/invoices", files={"file": (filename, content)})
        response.raise_for_status()
        return bool(response.json()["created"])

    return upload
