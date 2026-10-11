"""In-memory `Ledger` built from a catalog. Used by unit tests and the oracle evals."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from opsagent.datagen.records import Catalog
from opsagent.domain.ports import PaymentRef, PriorInvoiceRef, PurchaseOrderRef, VendorRef
from opsagent.domain.schemas import DecisionAction, ExtractedInvoice, PurchaseOrderStatus


@dataclass
class _Recorded:
    id: uuid.UUID
    filename: str
    vendor_tax_id: str | None
    number_normalized: str
    invoice_number: str
    total: Decimal
    issue_date: date
    po_id: int | None
    action: DecisionAction


class InMemoryLedger:
    def __init__(self, catalog: Catalog) -> None:
        self.vendors = [
            VendorRef(id=i, name=v.name, tax_id=v.tax_id, aliases=tuple(v.aliases))
            for i, v in enumerate(catalog.vendors, start=1)
        ]
        by_tax = {v.tax_id: v for v in self.vendors}
        self.purchase_orders = [
            PurchaseOrderRef(
                id=i,
                po_number=po.po_number,
                vendor_id=by_tax[po.vendor_tax_id].id,
                total=po.total,
                status=po.status,
            )
            for i, po in enumerate(catalog.purchase_orders, start=1)
        ]
        self.payments = [
            PaymentRef(
                id=i,
                reference=p.reference,
                vendor_id=by_tax[p.vendor_tax_id].id,
                amount=p.amount,
                paid_on=p.paid_on,
                invoice_number=p.invoice_number,
                po_number=p.po_number,
            )
            for i, p in enumerate(catalog.payments, start=1)
        ]
        self.recorded: list[_Recorded] = []

    # --- Ledger protocol -------------------------------------------------

    def vendor_by_tax_id(self, tax_id: str) -> VendorRef | None:
        return next((v for v in self.vendors if v.tax_id == tax_id), None)

    def all_vendors(self) -> list[VendorRef]:
        return list(self.vendors)

    def purchase_order(self, po_number: str) -> PurchaseOrderRef | None:
        return next((po for po in self.purchase_orders if po.po_number == po_number), None)

    def open_purchase_orders(self, vendor_id: int) -> list[PurchaseOrderRef]:
        return [
            po
            for po in self.purchase_orders
            if po.vendor_id == vendor_id and po.status is PurchaseOrderStatus.OPEN
        ]

    def payments_for_vendor(self, vendor_id: int) -> list[PaymentRef]:
        return [p for p in self.payments if p.vendor_id == vendor_id]

    def prior_invoices(
        self, *, vendor_tax_id: str | None, number_normalized: str, exclude: uuid.UUID
    ) -> list[PriorInvoiceRef]:
        return [
            PriorInvoiceRef(
                id=r.id,
                filename=r.filename,
                invoice_number=r.invoice_number,
                total=r.total,
                issue_date=r.issue_date,
            )
            for r in self.recorded
            if r.id != exclude
            and r.number_normalized == number_normalized
            and r.vendor_tax_id == vendor_tax_id
        ]

    def invoiced_against_po(self, po_id: int, *, exclude: uuid.UUID) -> Decimal:
        return sum(
            (
                r.total
                for r in self.recorded
                if r.po_id == po_id and r.id != exclude and r.action is DecisionAction.AUTO_APPROVE
            ),
            Decimal(0),
        )

    # --- test/eval helper ------------------------------------------------

    def record(
        self,
        *,
        invoice_id: uuid.UUID,
        filename: str,
        invoice: ExtractedInvoice,
        vendor: VendorRef | None,
        po: PurchaseOrderRef | None,
        action: DecisionAction,
    ) -> None:
        self.recorded.append(
            _Recorded(
                id=invoice_id,
                filename=filename,
                vendor_tax_id=vendor.tax_id if vendor else invoice.vendor_tax_id,
                number_normalized=invoice.normalized_number,
                invoice_number=invoice.invoice_number,
                total=invoice.total,
                issue_date=invoice.issue_date,
                po_id=po.id if po else None,
                action=action,
            )
        )
