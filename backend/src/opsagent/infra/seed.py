"""Load the synthetic catalog (vendors, purchase orders, payments) into Postgres.

Idempotent: rows are matched by their natural keys (RUC, PO number, payment
reference), so running it twice leaves the database unchanged.

    uv run python -m opsagent.infra.seed ../data/synthetic/catalog.json
"""

import argparse
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from opsagent.datagen.records import Catalog
from opsagent.infra.db.models import Payment, PurchaseOrder, PurchaseOrderLine, Vendor
from opsagent.infra.db.session import session_scope
from opsagent.infra.logging import configure_logging, get_logger

log = get_logger(__name__)


def seed_catalog(session: Session, catalog: Catalog) -> dict[str, int]:
    created = {"vendors": 0, "purchase_orders": 0, "payments": 0}

    vendors = {v.tax_id: v for v in session.scalars(select(Vendor))}
    for record in catalog.vendors:
        if record.tax_id not in vendors:
            vendor = Vendor(
                name=record.name, tax_id=record.tax_id, email=record.email, aliases=record.aliases
            )
            session.add(vendor)
            vendors[record.tax_id] = vendor
            created["vendors"] += 1
    session.flush()

    existing_pos = set(session.scalars(select(PurchaseOrder.po_number)))
    for po in catalog.purchase_orders:
        if po.po_number in existing_pos:
            continue
        session.add(
            PurchaseOrder(
                po_number=po.po_number,
                vendor_id=vendors[po.vendor_tax_id].id,
                issue_date=po.issue_date,
                subtotal=po.subtotal,
                tax=po.tax,
                total=po.total,
                status=po.status,
                lines=[
                    PurchaseOrderLine(
                        description=line.description,
                        quantity=line.quantity,
                        unit_price=line.unit_price,
                        total=line.total,
                    )
                    for line in po.lines
                ],
            )
        )
        created["purchase_orders"] += 1

    existing_payments = set(session.scalars(select(Payment.reference)))
    for payment in catalog.payments:
        if payment.reference in existing_payments:
            continue
        session.add(
            Payment(
                reference=payment.reference,
                vendor_id=vendors[payment.vendor_tax_id].id,
                amount=payment.amount,
                paid_on=payment.paid_on,
                invoice_number=payment.invoice_number,
                po_number=payment.po_number,
            )
        )
        created["payments"] += 1
    session.flush()
    return created


def load_catalog(path: Path) -> Catalog:
    return Catalog.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "catalog", type=Path, nargs="?", default=Path("../data/synthetic/catalog.json")
    )
    args = parser.parse_args()
    configure_logging()
    with session_scope() as session:
        created = seed_catalog(session, load_catalog(args.catalog))
    log.info("catalog_seeded", **created)


if __name__ == "__main__":
    main()
