from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from opsagent.domain.schemas import DecisionAction, InvoiceSource, InvoiceStatus
from opsagent.infra.db.models import Decision, Invoice, PurchaseOrder, Vendor

pytestmark = pytest.mark.integration


def _invoice(sha: str = "a" * 64) -> Invoice:
    return Invoice(
        file_sha256=sha,
        original_filename="factura.pdf",
        storage_path="inbox/factura.pdf",
        media_type="application/pdf",
        source=InvoiceSource.FOLDER,
    )


def test_same_file_cannot_be_ingested_twice(db_session: Session) -> None:
    db_session.add(_invoice())
    db_session.flush()

    db_session.add(_invoice())
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_money_round_trips_as_exact_decimal(db_session: Session) -> None:
    vendor = Vendor(name="Distribuidora Andina S.A.", tax_id="1790016919001", aliases=["Andina"])
    po = PurchaseOrder(
        po_number="OC-2026-0001",
        vendor=vendor,
        issue_date=date(2026, 3, 1),
        subtotal=Decimal("0.10"),
        tax=Decimal("0.20"),
        total=Decimal("0.30"),
    )
    db_session.add(po)
    db_session.flush()
    db_session.expire_all()

    stored = db_session.scalars(select(PurchaseOrder)).one()
    assert stored.total == stored.subtotal + stored.tax == Decimal("0.30")
    assert stored.vendor.aliases == ["Andina"]


def test_decisions_are_append_only_and_enums_stored_by_value(db_session: Session) -> None:
    invoice = _invoice()
    invoice.status = InvoiceStatus.DECIDED
    invoice.decisions = [
        Decision(
            action=DecisionAction.HUMAN_REVIEW,
            actor="agent",
            justification="Monto difiere de la OC en 12,40 USD.",
            findings=[{"code": "amount_mismatch", "difference": "12.40"}],
        ),
        Decision(action=DecisionAction.AUTO_APPROVE, actor="human:ana", justification="Aprobado."),
    ]
    db_session.add(invoice)
    db_session.flush()

    raw = db_session.connection().exec_driver_sql("SELECT action FROM decisions ORDER BY id")
    assert [row[0] for row in raw] == ["human_review", "auto_approve"]
    assert invoice.decisions[-1].actor == "human:ana"
