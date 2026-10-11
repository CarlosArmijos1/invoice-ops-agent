"""Serialisable records written by the dataset generator and read by the seeder and the evals."""

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

from opsagent.domain.findings import FindingCode
from opsagent.domain.schemas import DecisionAction, ExtractedInvoice, PurchaseOrderStatus


class VendorRecord(BaseModel):
    name: str
    tax_id: str
    email: str
    aliases: list[str] = Field(default_factory=list)


class LineRecord(BaseModel):
    description: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal


class PurchaseOrderRecord(BaseModel):
    po_number: str
    vendor_tax_id: str
    issue_date: date
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    status: PurchaseOrderStatus = PurchaseOrderStatus.OPEN
    lines: list[LineRecord]


class PaymentRecord(BaseModel):
    reference: str
    vendor_tax_id: str
    amount: Decimal
    paid_on: date
    invoice_number: str | None = None
    po_number: str | None = None


class Catalog(BaseModel):
    vendors: list[VendorRecord]
    purchase_orders: list[PurchaseOrderRecord]
    payments: list[PaymentRecord]


class Render(StrEnum):
    PDF_TEXT = "pdf_text"  # digital PDF with a text layer
    PDF_SCAN = "pdf_scan"  # scanned pages wrapped in a PDF, no text layer
    JPG = "jpg"  # phone photo / scan
    PNG = "png"


class Split(StrEnum):
    DEV = "dev"  # may be looked at while tuning prompts
    TEST = "test"  # held out: the numbers reported in the README


class GroundTruth(BaseModel):
    file: str
    scenario: str
    split: Split
    template: str
    render: Render
    extraction: ExtractedInvoice
    expected_action: DecisionAction
    expected_findings: list[FindingCode] = Field(
        description="Findings that must be raised; extra informational findings are allowed"
    )
    duplicate_of: str | None = None
    # How the invoice reaches the company: dropped in the inbox folder, or published
    # on the supplier's web portal (downloaded by the Playwright robot).
    channel: str = "folder"
    notes: str = ""
