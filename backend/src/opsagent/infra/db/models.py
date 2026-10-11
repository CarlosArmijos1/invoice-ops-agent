"""SQLAlchemy ORM models.

Design notes:
- Money is `NUMERIC(14, 2)` mapped to `Decimal`: never floats for amounts.
- `decisions`, `audit_events` and `llm_calls` are append-only. A human override
  adds a new decision row instead of editing the agent's; the latest row wins.
- `invoices.file_sha256` is UNIQUE: the database itself guarantees the same
  file is never ingested twice, even with concurrent workers.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from opsagent.domain.schemas import (
    DecisionAction,
    InvoiceSource,
    InvoiceStatus,
    PurchaseOrderStatus,
    ReviewOutcome,
)

MoneyColumn = Numeric(14, 2)
# JSONB on Postgres, plain JSON elsewhere (keeps unit tests DB-agnostic).
JsonColumn = JSON().with_variant(JSONB(), "postgresql")


def _enum(cls: type[Any]) -> Enum:
    # Store the enum *value* ("auto_approve"), not its Python name.
    return Enum(cls, values_callable=lambda e: [m.value for m in e], native_enum=False, length=32)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------- catalog


class Vendor(TimestampMixin, Base):
    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    tax_id: Mapped[str] = mapped_column(String(13), unique=True)
    email: Mapped[str | None] = mapped_column(String(200))
    # Alternative spellings seen on invoices ("Dist. Andina", "DISTRIBUIDORA ANDINA SA").
    aliases: Mapped[list[str]] = mapped_column(JsonColumn, default=list)

    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="vendor")


class PurchaseOrder(TimestampMixin, Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_number: Mapped[str] = mapped_column(String(40), unique=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    issue_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    subtotal: Mapped[Decimal] = mapped_column(MoneyColumn)
    tax: Mapped[Decimal] = mapped_column(MoneyColumn)
    total: Mapped[Decimal] = mapped_column(MoneyColumn)
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        _enum(PurchaseOrderStatus), default=PurchaseOrderStatus.OPEN
    )

    vendor: Mapped[Vendor] = relationship(back_populates="purchase_orders")
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    total: Mapped[Decimal] = mapped_column(MoneyColumn)

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(60), unique=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(MoneyColumn)
    paid_on: Mapped[date] = mapped_column(Date)
    # What the bank transfer memo says; often incomplete or formatted differently.
    invoice_number: Mapped[str | None] = mapped_column(String(40))
    po_number: Mapped[str | None] = mapped_column(String(40))

    vendor: Mapped[Vendor] = relationship()


# --------------------------------------------------------------------------- processing


class Invoice(TimestampMixin, Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    file_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(500))
    media_type: Mapped[str] = mapped_column(String(100))
    source: Mapped[InvoiceSource] = mapped_column(_enum(InvoiceSource))
    status: Mapped[InvoiceStatus] = mapped_column(
        _enum(InvoiceStatus), default=InvoiceStatus.RECEIVED, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Denormalised from the accepted extraction, for filtering and duplicate lookups.
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"))
    vendor_name: Mapped[str | None] = mapped_column(String(200))
    vendor_tax_id: Mapped[str | None] = mapped_column(String(13))
    invoice_number: Mapped[str | None] = mapped_column(String(40))
    invoice_number_normalized: Mapped[str | None] = mapped_column(String(40))
    po_number: Mapped[str | None] = mapped_column(String(40))
    issue_date: Mapped[date | None] = mapped_column(Date)
    total: Mapped[Decimal | None] = mapped_column(MoneyColumn)
    currency: Mapped[str | None] = mapped_column(String(3))

    # Aggregated observability, kept in sync with `llm_calls`.
    llm_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    processing_ms: Mapped[int | None] = mapped_column(Integer)

    extractions: Mapped[list["Extraction"]] = relationship(
        back_populates="invoice", order_by="Extraction.created_at"
    )
    decisions: Mapped[list["Decision"]] = relationship(
        back_populates="invoice", order_by="Decision.created_at"
    )

    __table_args__ = (
        Index("ix_invoices_vendor_number", "vendor_tax_id", "invoice_number_normalized"),
    )


class Extraction(TimestampMixin, Base):
    __tablename__ = "extractions"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    method: Mapped[str] = mapped_column(String(20))  # "text" | "vision"
    model: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict[str, Any] | None] = mapped_column(JsonColumn)
    valid: Mapped[bool]
    quality_score: Mapped[float | None]
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JsonColumn, default=list)
    error: Mapped[str | None] = mapped_column(Text)

    invoice: Mapped[Invoice] = relationship(back_populates="extractions")


class Decision(TimestampMixin, Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[DecisionAction] = mapped_column(_enum(DecisionAction), index=True)
    actor: Mapped[str] = mapped_column(String(100))  # "agent" or "human:<name>"
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JsonColumn, default=list)
    justification: Mapped[str] = mapped_column(Text)
    supplier_message: Mapped[str | None] = mapped_column(Text)
    matched_po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"))
    review_outcome: Mapped[ReviewOutcome | None] = mapped_column(_enum(ReviewOutcome))

    invoice: Mapped[Invoice] = relationship(back_populates="decisions")


class AuditEvent(TimestampMixin, Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    event: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any]] = mapped_column(JsonColumn, default=dict)


class LlmCall(TimestampMixin, Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    purpose: Mapped[str] = mapped_column(String(40))  # extract | justify | ...
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(100))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    latency_ms: Mapped[int] = mapped_column(Integer)
    ok: Mapped[bool]
    error: Mapped[str | None] = mapped_column(Text)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    trigger: Mapped[str] = mapped_column(String(20))  # schedule | api | mcp | cli
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")
    stats: Mapped[dict[str, Any]] = mapped_column(JsonColumn, default=dict)


class DailyReport(TimestampMixin, Base):
    __tablename__ = "daily_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, unique=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JsonColumn)
    markdown: Mapped[str] = mapped_column(Text)
