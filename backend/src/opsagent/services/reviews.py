"""Human-in-the-loop: a reviewer settles an invoice the agent did not approve."""

import uuid

from sqlalchemy.orm import Session

from opsagent.domain.schemas import DecisionAction, InvoiceStatus, ReviewOutcome
from opsagent.infra.db.models import AuditEvent, Decision, Invoice


class ReviewError(ValueError):
    pass


def review_invoice(
    session: Session,
    invoice_id: uuid.UUID,
    *,
    outcome: ReviewOutcome,
    reviewer: str,
    note: str,
) -> Decision:
    invoice = session.get(Invoice, invoice_id, with_for_update=True)
    if invoice is None:
        raise ReviewError("La factura no existe.")
    if invoice.status is not InvoiceStatus.DECIDED or invoice.current_action is None:
        raise ReviewError("La factura todavía no tiene una decisión del agente.")
    if invoice.current_action is DecisionAction.AUTO_APPROVE:
        raise ReviewError("Las facturas aprobadas automáticamente no requieren revisión.")
    if invoice.approved is not None:
        raise ReviewError("La factura ya fue revisada.")

    reviewer = reviewer.strip()[:60] or "anon"
    decision = Decision(
        invoice_id=invoice_id,
        action=invoice.current_action,
        actor=f"human:{reviewer}",
        findings=[],
        justification=note.strip() or f"Revisión humana: {outcome.value}.",
        review_outcome=outcome,
        matched_po_id=invoice.matched_po_id,
    )
    session.add(decision)
    invoice.approved = outcome is ReviewOutcome.APPROVED
    session.add(
        AuditEvent(
            invoice_id=invoice_id,
            event="reviewed",
            payload={"outcome": outcome.value, "reviewer": reviewer},
        )
    )
    session.flush()
    return decision
