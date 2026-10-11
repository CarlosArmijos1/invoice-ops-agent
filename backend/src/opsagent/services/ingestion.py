"""Ingest invoice files from any source. Idempotent by content hash."""

import hashlib
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from opsagent.domain.schemas import InvoiceSource
from opsagent.extraction.documents import (
    MAX_FILE_BYTES,
    UnsupportedDocumentError,
    sniff_media_type,
)
from opsagent.infra.db.models import AuditEvent, Invoice, InvoiceFile
from opsagent.infra.logging import get_logger

log = get_logger(__name__)

SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}


@dataclass(frozen=True)
class IngestResult:
    invoice_id: uuid.UUID
    created: bool  # False when the exact same file had already been received
    filename: str


def ingest_bytes(
    session: Session, content: bytes, filename: str, source: InvoiceSource
) -> IngestResult:
    """Register a file. Raises `UnsupportedDocumentError` for non-invoice formats."""
    if len(content) > MAX_FILE_BYTES:
        raise UnsupportedDocumentError("File too large")
    media_type = sniff_media_type(content)
    sha256 = hashlib.sha256(content).hexdigest()

    existing = session.scalar(select(Invoice).where(Invoice.file_sha256 == sha256))
    if existing is not None:
        log.info("ingest_duplicate_file", filename=filename, invoice_id=str(existing.id))
        return IngestResult(existing.id, created=False, filename=existing.original_filename)

    try:
        with session.begin_nested():
            if session.get(InvoiceFile, sha256) is None:
                session.add(
                    InvoiceFile(
                        sha256=sha256,
                        media_type=media_type,
                        size_bytes=len(content),
                        content=content,
                    )
                )
                session.flush()  # the file row must exist before the invoice references it
            invoice = Invoice(
                file_sha256=sha256,
                original_filename=Path(filename).name[:255],
                media_type=media_type,
                source=source,
            )
            session.add(invoice)
            session.flush()
            session.add(
                AuditEvent(
                    invoice_id=invoice.id,
                    event="received",
                    payload={"filename": invoice.original_filename, "source": source.value},
                )
            )
    except IntegrityError:
        # Lost a race with a concurrent ingest of the same file: the other one wins.
        existing = session.scalar(select(Invoice).where(Invoice.file_sha256 == sha256))
        if existing is None:
            raise
        return IngestResult(existing.id, created=False, filename=existing.original_filename)

    log.info("ingest_received", filename=filename, invoice_id=str(invoice.id))
    return IngestResult(invoice.id, created=True, filename=invoice.original_filename)


def ingest_folder(
    session_factory: sessionmaker[Session], inbox: Path, archive: Path | None = None
) -> list[IngestResult]:
    """Ingest every supported file in `inbox` (sorted by name) and move it to `archive`.

    Each file is committed on its own, so one bad file never blocks the rest.
    """
    archive = archive or inbox / "_procesadas"
    results = []
    for path in sorted(p for p in inbox.iterdir() if p.is_file()):
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        try:
            with session_factory() as session, session.begin():
                result = ingest_bytes(session, path.read_bytes(), path.name, InvoiceSource.FOLDER)
        except UnsupportedDocumentError as exc:
            log.warning("ingest_rejected", filename=path.name, reason=str(exc))
            continue
        results.append(result)
        archive.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), archive / path.name)
    return results
