"""Read-only view of the books that reconciliation needs (a "port").

The domain declares what it needs; `infra.db.ledger.SqlLedger` implements it
with SQL, and tests use an in-memory implementation. The business rules never
import SQLAlchemy.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol

from opsagent.domain.schemas import PurchaseOrderStatus


@dataclass(frozen=True)
class VendorRef:
    id: int
    name: str
    tax_id: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class PurchaseOrderRef:
    id: int
    po_number: str
    vendor_id: int
    total: Decimal
    status: PurchaseOrderStatus = PurchaseOrderStatus.OPEN


@dataclass(frozen=True)
class PaymentRef:
    id: int
    reference: str
    vendor_id: int
    amount: Decimal
    paid_on: date
    invoice_number: str | None = None
    po_number: str | None = None


@dataclass(frozen=True)
class PriorInvoiceRef:
    id: uuid.UUID
    filename: str
    invoice_number: str
    total: Decimal
    issue_date: date | None = None
    extra: dict[str, str] = field(default_factory=dict)


class Ledger(Protocol):
    def vendor_by_tax_id(self, tax_id: str) -> VendorRef | None: ...

    def all_vendors(self) -> list[VendorRef]: ...

    def purchase_order(self, po_number: str) -> PurchaseOrderRef | None: ...

    def open_purchase_orders(self, vendor_id: int) -> list[PurchaseOrderRef]: ...

    def payments_for_vendor(self, vendor_id: int) -> list[PaymentRef]: ...

    def prior_invoices(
        self, *, vendor_tax_id: str | None, number_normalized: str, exclude: uuid.UUID
    ) -> list[PriorInvoiceRef]: ...

    def invoiced_against_po(self, po_id: int, *, exclude: uuid.UUID) -> Decimal: ...
