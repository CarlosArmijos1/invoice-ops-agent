"""Core domain types. Pure Pydantic, no I/O: shared by the agent, API, MCP server and evals."""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from opsagent.domain.parsing import normalize_invoice_number, parse_amount, parse_date, to_money

Amount = Annotated[Decimal, BeforeValidator(parse_amount)]
Money = Annotated[Decimal, BeforeValidator(lambda v: to_money(parse_amount(v)))]
LooseDate = Annotated[date, BeforeValidator(parse_date)]


class LineItem(BaseModel):
    description: str = Field(min_length=1)
    quantity: Amount = Field(gt=0)
    unit_price: Amount = Field(ge=0)
    total: Money


class ExtractedInvoice(BaseModel):
    """What the extraction step must produce. This is the contract given to the LLM.

    Only shape and type errors are rejected here (they trigger a retry with the
    validation error fed back to the model). Business inconsistencies, such as
    lines that do not add up, are legitimate properties of a real invoice and
    are reported by the quality checks instead of being rejected.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    vendor_name: str = Field(min_length=2, description="Razón social del emisor")
    vendor_tax_id: str | None = Field(None, description="RUC del emisor (13 dígitos)")
    invoice_number: str = Field(
        min_length=1, description="Número de factura, p. ej. 001-001-000000123"
    )
    issue_date: LooseDate
    due_date: LooseDate | None = None
    currency: str = Field("USD", min_length=3, max_length=3)
    po_number: str | None = Field(None, description="Orden de compra referenciada, si aparece")
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: Money
    tax: Money = Field(description="IVA total")
    total: Money

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("vendor_tax_id")
    @classmethod
    def _digits_only_tax_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        digits = "".join(ch for ch in value if ch.isdigit())
        return digits or None

    @field_validator("po_number")
    @classmethod
    def _blank_po_is_none(cls, value: str | None) -> str | None:
        return value.strip().upper() or None if value else None

    @property
    def normalized_number(self) -> str:
        return normalize_invoice_number(self.invoice_number)


class InvoiceSource(StrEnum):
    FOLDER = "folder"
    UPLOAD = "upload"
    PORTAL = "portal"


class InvoiceStatus(StrEnum):
    """Lifecycle of an invoice. Transitions are recorded as audit events."""

    RECEIVED = "received"
    PROCESSING = "processing"
    DECIDED = "decided"
    FAILED = "failed"


class DecisionAction(StrEnum):
    AUTO_APPROVE = "auto_approve"
    HUMAN_REVIEW = "human_review"
    REQUEST_INFO = "request_info"


class ReviewOutcome(StrEnum):
    """What a human reviewer can do with an invoice flagged by the agent."""

    APPROVED = "approved"
    REJECTED = "rejected"


class PurchaseOrderStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"
