"""SQL implementation of the domain `Ledger` port."""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opsagent.domain.ports import PaymentRef, PriorInvoiceRef, PurchaseOrderRef, VendorRef
from opsagent.domain.schemas import InvoiceStatus, PurchaseOrderStatus
from opsagent.infra.db.models import Invoice, Payment, PurchaseOrder, Vendor


def _vendor(v: Vendor) -> VendorRef:
    return VendorRef(id=v.id, name=v.name, tax_id=v.tax_id, aliases=tuple(v.aliases or ()))


def _po(po: PurchaseOrder) -> PurchaseOrderRef:
    return PurchaseOrderRef(
        id=po.id, po_number=po.po_number, vendor_id=po.vendor_id, total=po.total, status=po.status
    )


class SqlLedger:
    def __init__(self, session: Session) -> None:
        self.session = session

    def vendor_by_tax_id(self, tax_id: str) -> VendorRef | None:
        vendor = self.session.scalar(select(Vendor).where(Vendor.tax_id == tax_id))
        return _vendor(vendor) if vendor else None

    def all_vendors(self) -> list[VendorRef]:
        return [_vendor(v) for v in self.session.scalars(select(Vendor).order_by(Vendor.id))]

    def purchase_order(self, po_number: str) -> PurchaseOrderRef | None:
        po = self.session.scalar(
            select(PurchaseOrder).where(func.upper(PurchaseOrder.po_number) == po_number.upper())
        )
        return _po(po) if po else None

    def open_purchase_orders(self, vendor_id: int) -> list[PurchaseOrderRef]:
        rows = self.session.scalars(
            select(PurchaseOrder).where(
                PurchaseOrder.vendor_id == vendor_id,
                PurchaseOrder.status == PurchaseOrderStatus.OPEN,
            )
        )
        return [_po(po) for po in rows]

    def payments_for_vendor(self, vendor_id: int) -> list[PaymentRef]:
        rows = self.session.scalars(
            select(Payment).where(Payment.vendor_id == vendor_id).order_by(Payment.paid_on)
        )
        return [
            PaymentRef(
                id=p.id,
                reference=p.reference,
                vendor_id=p.vendor_id,
                amount=p.amount,
                paid_on=p.paid_on,
                invoice_number=p.invoice_number,
                po_number=p.po_number,
            )
            for p in rows
        ]

    def prior_invoices(
        self, *, vendor_tax_id: str | None, number_normalized: str, exclude: uuid.UUID
    ) -> list[PriorInvoiceRef]:
        rows = self.session.scalars(
            select(Invoice)
            .where(
                Invoice.id != exclude,
                Invoice.status == InvoiceStatus.DECIDED,
                Invoice.invoice_number_normalized == number_normalized,
                Invoice.vendor_tax_id == vendor_tax_id
                if vendor_tax_id
                else Invoice.vendor_tax_id.is_(None),
            )
            .order_by(Invoice.created_at)
        )
        return [
            PriorInvoiceRef(
                id=inv.id,
                filename=inv.original_filename,
                invoice_number=inv.invoice_number or "",
                total=inv.total or Decimal(0),
                issue_date=inv.issue_date,
            )
            for inv in rows
        ]

    def invoiced_against_po(self, po_id: int, *, exclude: uuid.UUID) -> Decimal:
        total = self.session.scalar(
            select(func.coalesce(func.sum(Invoice.total), 0)).where(
                Invoice.matched_po_id == po_id,
                Invoice.id != exclude,
                Invoice.approved.is_(True),
            )
        )
        return Decimal(total or 0)
