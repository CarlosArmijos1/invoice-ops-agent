"""First-start setup for demos: seed master data and preload the synthetic invoices once."""

from sqlalchemy import func, select

from opsagent.container import Container
from opsagent.domain.schemas import InvoiceSource
from opsagent.infra.db.models import Invoice, Vendor
from opsagent.infra.logging import get_logger
from opsagent.infra.seed import load_catalog, seed_catalog
from opsagent.services.ingestion import SUPPORTED_SUFFIXES, ingest_bytes

log = get_logger(__name__)


def bootstrap_demo(container: Container) -> None:
    dataset = container.settings.demo_dataset_dir
    with container.session_factory() as session, session.begin():
        if not session.scalar(select(func.count()).select_from(Vendor)):
            created = seed_catalog(session, load_catalog(dataset / "catalog.json"))
            log.info("demo_catalog_seeded", **created)
        if session.scalar(select(func.count()).select_from(Invoice)):
            return
        files = sorted(
            p for p in (dataset / "invoices").iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES
        )
        for path in files:
            ingest_bytes(session, path.read_bytes(), path.name, InvoiceSource.FOLDER)
        log.info("demo_invoices_preloaded", count=len(files))
