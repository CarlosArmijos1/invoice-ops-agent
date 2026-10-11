"""Read models (what the API, the panel and the MCP server return) and the queries behind them."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from opsagent.domain.schemas import DecisionAction, InvoiceSource, InvoiceStatus, ReviewOutcome
from opsagent.extraction.documents import page_count
from opsagent.infra.db.models import (
    AgentRun,
    AuditEvent,
    Decision,
    Extraction,
    Invoice,
    InvoiceFile,
    LlmCall,
    PurchaseOrder,
)

# Informational findings present on almost every invoice; not interesting to rank or badge.
_CONTEXT_CODES = {"paid", "unpaid", "po_matched", "amount_within_tolerance"}


class _View(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class InvoiceSummary(_View):
    id: uuid.UUID
    original_filename: str
    media_type: str
    source: InvoiceSource
    status: InvoiceStatus
    current_action: DecisionAction | None
    approved: bool | None
    vendor_name: str | None
    vendor_tax_id: str | None
    invoice_number: str | None
    po_number: str | None
    issue_date: date | None
    total: Decimal | None
    currency: str | None
    created_at: datetime
    processed_at: datetime | None
    llm_cost_usd: Decimal
    processing_ms: int | None
    attempts: int
    last_error: str | None
    finding_codes: list[str] = []


class ExtractionView(_View):
    method: str
    model: str
    data: dict[str, Any] | None
    valid: bool
    quality_score: float | None
    issues: list[dict[str, Any]]
    error: str | None
    created_at: datetime


class DecisionView(_View):
    id: int
    action: DecisionAction
    actor: str
    findings: list[dict[str, Any]]
    justification: str
    supplier_message: str | None
    review_outcome: ReviewOutcome | None
    created_at: datetime


class LlmCallView(_View):
    purpose: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    latency_ms: int
    ok: bool
    error: str | None
    created_at: datetime


class EventView(_View):
    event: str
    payload: dict[str, Any]
    created_at: datetime


class InvoiceDetail(InvoiceSummary):
    extraction: ExtractionView | None
    decisions: list[DecisionView]
    llm_calls: list[LlmCallView]
    events: list[EventView]
    matched_po_number: str | None = None
    matched_po_total: Decimal | None = None
    page_count: int = 1


class AgentRunView(_View):
    id: uuid.UUID
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    stats: dict[str, Any]


class Stats(BaseModel):
    invoices_total: int
    by_status: dict[str, int]
    by_action: dict[str, int]
    pending_review: int
    auto_approval_rate: float | None
    total_cost_usd: Decimal
    avg_cost_per_invoice_usd: Decimal | None
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    cost_by_model: dict[str, Decimal]
    daily: list[dict[str, Any]]
    top_findings: list[dict[str, Any]] = []


def _latest_decisions(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, Decision]:
    if not ids:
        return {}
    rows = session.scalars(
        select(Decision).where(Decision.invoice_id.in_(ids)).order_by(Decision.created_at)
    )
    return {d.invoice_id: d for d in rows}


def _summary(invoice: Invoice, decision: Decision | None) -> InvoiceSummary:
    view = InvoiceSummary.model_validate(invoice)
    if decision:
        view.finding_codes = [
            f["code"] for f in decision.findings if f["code"] not in _CONTEXT_CODES
        ]
    return view


def list_invoices(
    session: Session,
    *,
    status: InvoiceStatus | None = None,
    action: DecisionAction | None = None,
    needs_review: bool = False,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[InvoiceSummary], int]:
    stmt = select(Invoice)
    if status:
        stmt = stmt.where(Invoice.status == status)
    if action:
        stmt = stmt.where(Invoice.current_action == action)
    if needs_review:
        stmt = stmt.where(
            Invoice.current_action.in_([DecisionAction.HUMAN_REVIEW, DecisionAction.REQUEST_INFO]),
            Invoice.approved.is_(None),
        )
    if query:
        like = f"%{query.strip()}%"
        stmt = stmt.where(
            Invoice.vendor_name.ilike(like)
            | Invoice.invoice_number.ilike(like)
            | Invoice.original_filename.ilike(like)
            | Invoice.po_number.ilike(like)
        )
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        session.scalars(stmt.order_by(Invoice.created_at.desc()).limit(limit).offset(offset))
    )
    latest = _latest_decisions(session, [r.id for r in rows])
    return [_summary(r, latest.get(r.id)) for r in rows], total


def invoice_detail(session: Session, invoice_id: uuid.UUID) -> InvoiceDetail | None:
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        return None
    extraction = session.scalars(
        select(Extraction)
        .where(Extraction.invoice_id == invoice_id)
        .order_by(Extraction.created_at.desc())
    ).first()
    decisions = list(
        session.scalars(
            select(Decision).where(Decision.invoice_id == invoice_id).order_by(Decision.created_at)
        )
    )
    calls = session.scalars(
        select(LlmCall).where(LlmCall.invoice_id == invoice_id).order_by(LlmCall.created_at)
    )
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.invoice_id == invoice_id).order_by(AuditEvent.id)
    )
    po = session.get(PurchaseOrder, invoice.matched_po_id) if invoice.matched_po_id else None
    base = _summary(invoice, decisions[-1] if decisions else None)
    return InvoiceDetail(
        **base.model_dump(),
        extraction=ExtractionView.model_validate(extraction) if extraction else None,
        decisions=[DecisionView.model_validate(d) for d in decisions],
        llm_calls=[LlmCallView.model_validate(c) for c in calls],
        events=[EventView.model_validate(e) for e in events],
        matched_po_number=po.po_number if po else None,
        matched_po_total=po.total if po else None,
        page_count=page_count(session.get_one(InvoiceFile, invoice.file_sha256).content),
    )


def recent_runs(session: Session, limit: int = 20) -> list[AgentRunView]:
    rows = session.scalars(select(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit))
    return [AgentRunView.model_validate(r) for r in rows]


def _percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct * (len(ordered) - 1))))
    return ordered[index]


def stats(session: Session, *, days: int = 14) -> Stats:
    by_status = dict(
        session.execute(select(Invoice.status, func.count()).group_by(Invoice.status)).all()
    )
    by_action = dict(
        session.execute(
            select(Invoice.current_action, func.count())
            .where(Invoice.current_action.is_not(None))
            .group_by(Invoice.current_action)
        ).all()
    )
    decided = sum(by_action.values())
    pending_review = (
        session.scalar(
            select(func.count()).where(
                Invoice.current_action.in_(
                    [DecisionAction.HUMAN_REVIEW, DecisionAction.REQUEST_INFO]
                ),
                Invoice.approved.is_(None),
            )
        )
        or 0
    )
    total_cost = session.scalar(select(func.coalesce(func.sum(LlmCall.cost_usd), 0))) or 0
    latencies = [
        ms
        for ms in session.scalars(
            select(Invoice.processing_ms).where(Invoice.processing_ms.is_not(None))
        )
        if ms is not None
    ]
    cost_by_model = dict(
        session.execute(
            select(LlmCall.model, func.sum(LlmCall.cost_usd)).group_by(LlmCall.model)
        ).all()
    )
    since = datetime.now().astimezone() - timedelta(days=days)
    day = func.date(Invoice.processed_at)
    daily_rows = session.execute(
        select(
            day.label("day"),
            func.count().label("processed"),
            func.sum(
                case((Invoice.current_action == DecisionAction.AUTO_APPROVE, 1), else_=0)
            ).label("auto_approved"),
            func.coalesce(func.sum(Invoice.llm_cost_usd), 0).label("cost_usd"),
        )
        .where(Invoice.processed_at >= since)
        .group_by(day)
        .order_by(day)
    ).all()
    finding_counts: dict[str, int] = {}
    for findings in session.scalars(select(Decision.findings).where(Decision.actor == "agent")):
        for finding in findings:
            code = finding["code"]
            if code not in _CONTEXT_CODES:
                finding_counts[code] = finding_counts.get(code, 0) + 1
    return Stats(
        top_findings=[
            {"code": code, "count": count}
            for code, count in sorted(finding_counts.items(), key=lambda kv: -kv[1])[:8]
        ],
        invoices_total=sum(by_status.values()),
        by_status={k.value: v for k, v in by_status.items()},
        by_action={k.value: v for k, v in by_action.items() if k is not None},
        pending_review=pending_review,
        auto_approval_rate=(
            round(by_action.get(DecisionAction.AUTO_APPROVE, 0) / decided, 3) if decided else None
        ),
        total_cost_usd=Decimal(total_cost),
        avg_cost_per_invoice_usd=(
            (Decimal(total_cost) / decided).quantize(Decimal("0.000001")) if decided else None
        ),
        latency_p50_ms=_percentile(latencies, 0.5),
        latency_p95_ms=_percentile(latencies, 0.95),
        cost_by_model={k: Decimal(v) for k, v in cost_by_model.items()},
        daily=[
            {
                "day": r.day.isoformat(),
                "processed": r.processed,
                "auto_approved": int(r.auto_approved or 0),
                "cost_usd": str(r.cost_usd),
            }
            for r in daily_rows
        ],
    )
