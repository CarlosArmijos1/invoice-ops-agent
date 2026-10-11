"""Daily operations report: what the agent did, what is waiting for people, what is missing.

Idempotent per date (upsert), so the scheduler can safely run it more than once.
"""

from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from opsagent.domain.policy import ACTION_LABEL
from opsagent.domain.ports import PaymentRef
from opsagent.domain.reconciliation import payment_matches
from opsagent.domain.schemas import DecisionAction, InvoiceStatus, PurchaseOrderStatus
from opsagent.infra.db.models import DailyReport, Decision, Invoice, Payment, PurchaseOrder, Vendor

TZ = ZoneInfo("America/Guayaquil")
STALE_PO_DAYS = 30


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=TZ)
    return start, start + timedelta(days=1)


def _money(value: Decimal) -> str:
    return f"{value:,.2f}"


def build_daily_report(session: Session, day: date) -> dict[str, Any]:
    start, end = _day_bounds(day)
    processed = list(
        session.scalars(
            select(Invoice).where(Invoice.processed_at >= start, Invoice.processed_at < end)
        )
    )
    actions = Counter(i.current_action.value for i in processed if i.current_action)
    cost = sum((i.llm_cost_usd for i in processed), Decimal(0))
    latencies = sorted(i.processing_ms for i in processed if i.processing_ms is not None)

    pending = list(
        session.scalars(
            select(Invoice)
            .where(
                Invoice.current_action.in_(
                    [DecisionAction.HUMAN_REVIEW, DecisionAction.REQUEST_INFO]
                ),
                Invoice.approved.is_(None),
            )
            .order_by(Invoice.processed_at)
        )
    )
    failed = list(session.scalars(select(Invoice).where(Invoice.status == InvoiceStatus.FAILED)))

    finding_counter: Counter[str] = Counter()
    for decision in session.scalars(
        select(Decision).where(
            Decision.actor == "agent", Decision.created_at >= start, Decision.created_at < end
        )
    ):
        for finding in decision.findings:
            if finding["code"] not in ("paid", "unpaid", "po_matched"):
                finding_counter[finding["code"]] += 1

    # Payments with no invoice: money left the account and there is no document for it.
    decided = list(session.scalars(select(Invoice).where(Invoice.status == InvoiceStatus.DECIDED)))
    by_vendor: dict[int, list[Invoice]] = {}
    for inv in decided:
        if inv.vendor_id is not None:
            by_vendor.setdefault(inv.vendor_id, []).append(inv)
    unmatched_payments = []
    for payment, vendor_name in session.execute(
        select(Payment, Vendor.name).join(Vendor).order_by(Payment.paid_on)
    ):
        ref = PaymentRef(
            id=payment.id,
            reference=payment.reference,
            vendor_id=payment.vendor_id,
            amount=payment.amount,
            paid_on=payment.paid_on,
            invoice_number=payment.invoice_number,
            po_number=payment.po_number,
        )
        if not any(
            payment_matches(ref, inv.invoice_number_normalized or "", inv.po_number)
            for inv in by_vendor.get(payment.vendor_id, [])
        ):
            unmatched_payments.append(
                {
                    "reference": payment.reference,
                    "vendor": vendor_name,
                    "amount": str(payment.amount),
                    "paid_on": payment.paid_on.isoformat(),
                    "memo": payment.invoice_number or payment.po_number,
                }
            )

    # Open purchase orders that never received an invoice.
    invoiced_po_ids = {i.matched_po_id for i in decided if i.matched_po_id}
    stale_cutoff = day - timedelta(days=STALE_PO_DAYS)
    stale_pos = [
        {
            "po_number": po.po_number,
            "vendor": vendor_name,
            "total": str(po.total),
            "issue_date": po.issue_date.isoformat(),
        }
        for po, vendor_name in session.execute(
            select(PurchaseOrder, Vendor.name)
            .join(Vendor)
            .where(
                PurchaseOrder.status == PurchaseOrderStatus.OPEN,
                PurchaseOrder.issue_date <= stale_cutoff,
            )
            .order_by(PurchaseOrder.issue_date)
        )
        if po.id not in invoiced_po_ids
    ]

    now = datetime.now(UTC)
    return {
        "date": day.isoformat(),
        "processed": len(processed),
        "actions": dict(actions),
        "auto_approval_rate": (
            round(actions.get(DecisionAction.AUTO_APPROVE.value, 0) / len(processed), 3)
            if processed
            else None
        ),
        "cost_usd": str(cost),
        "avg_cost_usd": str((cost / len(processed)).quantize(Decimal("0.000001")))
        if processed
        else None,
        "latency_p50_ms": latencies[len(latencies) // 2] if latencies else None,
        "top_findings": finding_counter.most_common(8),
        "pending_review": [
            {
                "id": str(i.id),
                "file": i.original_filename,
                "vendor": i.vendor_name,
                "total": str(i.total) if i.total is not None else None,
                "action": i.current_action.value if i.current_action else None,
                "waiting_hours": round((now - i.processed_at).total_seconds() / 3600, 1)
                if i.processed_at
                else None,
            }
            for i in pending
        ],
        "failed": [{"file": i.original_filename, "error": i.last_error} for i in failed],
        "payments_without_invoice": unmatched_payments,
        "stale_purchase_orders": stale_pos,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    actions = summary["actions"]
    lines = [
        f"# Reporte diario de cuentas por pagar — {summary['date']}",
        "",
        f"- Facturas procesadas: **{summary['processed']}**",
    ]
    for action in DecisionAction:
        lines.append(f"  - {ACTION_LABEL[action]}: {actions.get(action.value, 0)}")
    if summary["auto_approval_rate"] is not None:
        lines.append(f"- Tasa de aprobación automática: {summary['auto_approval_rate']:.0%}")
    lines.append(
        f"- Costo LLM del día: ${summary['cost_usd']} (promedio ${summary['avg_cost_usd']})"
    )
    if summary["top_findings"]:
        lines += ["", "## Hallazgos más frecuentes", ""]
        lines += [f"- `{code}`: {count}" for code, count in summary["top_findings"]]
    lines += ["", f"## Pendientes de revisión humana ({len(summary['pending_review'])})", ""]
    lines += [
        f"- {p['file']} — {p['vendor'] or 'proveedor ?'} — ${p['total']} — {p['action']}"
        for p in summary["pending_review"][:20]
    ] or ["- Ninguna 🎉"]
    if summary["failed"]:
        lines += ["", f"## Con error técnico ({len(summary['failed'])})", ""]
        lines += [f"- {f['file']}: {f['error']}" for f in summary["failed"]]
    lines += ["", f"## Pagos sin factura ({len(summary['payments_without_invoice'])})", ""]
    lines += [
        f"- {p['reference']} — {p['vendor']} — ${_money(Decimal(p['amount']))} ({p['paid_on']})"
        for p in summary["payments_without_invoice"]
    ] or ["- Ninguno"]
    lines += [
        "",
        f"## Órdenes abiertas sin factura hace +{STALE_PO_DAYS} días "
        f"({len(summary['stale_purchase_orders'])})",
        "",
    ]
    lines += [
        f"- {po['po_number']} — {po['vendor']} — ${_money(Decimal(po['total']))} "
        f"(emitida {po['issue_date']})"
        for po in summary["stale_purchase_orders"]
    ] or ["- Ninguna"]
    return "\n".join(lines) + "\n"


def generate_daily_report(session: Session, day: date | None = None) -> DailyReport:
    day = day or datetime.now(TZ).date()
    summary = build_daily_report(session, day)
    markdown = render_markdown(summary)
    report = session.scalar(select(DailyReport).where(DailyReport.report_date == day))
    if report is None:
        report = DailyReport(report_date=day, summary=summary, markdown=markdown)
        session.add(report)
    else:
        report.summary = summary
        report.markdown = markdown
    session.flush()
    return report
