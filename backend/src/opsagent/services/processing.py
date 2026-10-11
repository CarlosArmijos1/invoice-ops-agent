"""Run the agent over pending invoices: claim, process, record outcome.

Safety properties:
- Claiming uses `SELECT ... FOR UPDATE SKIP LOCKED`, so two workers (or the
  scheduler and a manual trigger) never process the same invoice.
- Invoices are processed oldest-first, which is what makes duplicate
  detection deterministic ("the second copy is the duplicate").
- An infrastructure failure (LLM outage) leaves the invoice FAILED with a
  growing back-off; after `max_processing_attempts` it waits for a human.
- A claim older than `claim_timeout_minutes` belongs to a crashed worker and
  can be taken over; the LangGraph checkpoint lets it resume mid-graph.
"""

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy import Integer, and_, func, or_, select

from opsagent.agent.deps import AgentDeps
from opsagent.agent.graph import build_graph
from opsagent.agent.state import AgentState
from opsagent.domain.schemas import InvoiceStatus
from opsagent.infra.db.models import AgentRun, AuditEvent, Invoice, LlmCall
from opsagent.infra.logging import get_logger

log = get_logger(__name__)


@dataclass
class RunSummary:
    run_id: uuid.UUID
    processed: int = 0
    failed: int = 0
    actions: dict[str, int] = field(default_factory=dict)
    cost_usd: str = "0"

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "processed": self.processed,
            "failed": self.failed,
            "actions": self.actions,
            "cost_usd": self.cost_usd,
        }


class InvoiceProcessor:
    def __init__(
        self,
        deps: AgentDeps,
        checkpointer: BaseCheckpointSaver[str] | None = None,
        *,
        max_attempts: int = 5,
        claim_timeout: timedelta = timedelta(minutes=15),
    ) -> None:
        self.deps = deps
        self.checkpointer = checkpointer
        self.graph = build_graph(deps, checkpointer)
        self.max_attempts = max_attempts
        self.claim_timeout = claim_timeout

    # ------------------------------------------------------------------ claiming

    def _claim_next(self, only: uuid.UUID | None = None) -> uuid.UUID | None:
        now = datetime.now(UTC)
        stale = and_(
            Invoice.status == InvoiceStatus.PROCESSING,
            Invoice.claimed_at < now - self.claim_timeout,
        )
        if only is not None:
            # Manual trigger: retry a failed invoice right away, whatever its attempts.
            condition = and_(
                Invoice.id == only,
                or_(Invoice.status.in_([InvoiceStatus.RECEIVED, InvoiceStatus.FAILED]), stale),
            )
        else:
            # Exponential back-off between automatic retries: 1, 2, 4, 8... minutes.
            backoff = func.make_interval(
                0, 0, 0, 0, 0, func.power(2, Invoice.attempts - 1).cast(Integer)
            )
            retryable_failed = and_(
                Invoice.status == InvoiceStatus.FAILED,
                Invoice.attempts < self.max_attempts,
                Invoice.claimed_at + backoff < now,
            )
            condition = or_(Invoice.status == InvoiceStatus.RECEIVED, retryable_failed, stale)
        query = (
            select(Invoice)
            .where(condition)
            .order_by(Invoice.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )

        with self.deps.session_factory() as session, session.begin():
            invoice = session.scalar(query)
            if invoice is None:
                return None
            invoice.status = InvoiceStatus.PROCESSING
            invoice.claimed_at = now
            invoice.attempts += 1
            return invoice.id

    # ------------------------------------------------------------------ processing

    def process(self, invoice_id: uuid.UUID, run_id: uuid.UUID | None = None) -> str | None:
        """Process one claimed invoice. Returns the action, or None if it failed."""
        config: RunnableConfig = {"configurable": {"thread_id": str(invoice_id)}}
        with structlog.contextvars.bound_contextvars(
            invoice_id=str(invoice_id), run_id=str(run_id) if run_id else None
        ):
            try:
                resume = bool(self.checkpointer and self.graph.get_state(config).next)
                if resume:
                    log.info("resuming_from_checkpoint")
                    final = self.graph.invoke(None, config)
                else:
                    initial: AgentState = {
                        "invoice_id": str(invoice_id),
                        "run_id": str(run_id) if run_id else None,
                        "started_at": time.time(),
                        "llm_calls": [],
                    }
                    final = self.graph.invoke(initial, config)
            except Exception as exc:
                self._mark_failed(invoice_id, run_id, exc)
                return None
            if self.checkpointer is not None:
                self.checkpointer.delete_thread(str(invoice_id))  # done: free the space
            action: str | None = final.get("action")
            return action

    def _mark_failed(self, invoice_id: uuid.UUID, run_id: uuid.UUID | None, exc: Exception) -> None:
        log.error("invoice_processing_failed", error=type(exc).__name__, detail=str(exc)[:500])
        with self.deps.session_factory() as session, session.begin():
            invoice = session.get_one(Invoice, invoice_id)
            invoice.status = InvoiceStatus.FAILED
            invoice.last_error = f"{type(exc).__name__}: {str(exc)[:1000]}"
            session.add(
                AuditEvent(
                    invoice_id=invoice_id,
                    run_id=run_id,
                    event="processing_failed",
                    payload={"error": type(exc).__name__, "attempt": invoice.attempts},
                )
            )

    def process_one(self, invoice_id: uuid.UUID) -> str | None:
        """Process a specific invoice now (used by the API and MCP)."""
        claimed = self._claim_next(only=invoice_id)
        if claimed is None:
            return None
        return self.process(claimed)

    def process_pending(self, trigger: str, limit: int = 100) -> RunSummary:
        with self.deps.session_factory() as session, session.begin():
            run = AgentRun(trigger=trigger)
            session.add(run)
            session.flush()
            run_id = run.id
        summary = RunSummary(run_id=run_id)
        log.info("agent_run_started", run_id=str(run_id), trigger=trigger)

        status = "ok"
        try:
            for _ in range(limit):
                invoice_id = self._claim_next()
                if invoice_id is None:
                    break
                action = self.process(invoice_id, run_id)
                if action is None:
                    summary.failed += 1
                else:
                    summary.processed += 1
                    summary.actions[action] = summary.actions.get(action, 0) + 1
        except Exception:
            status = "error"
            raise
        finally:
            with self.deps.session_factory() as session, session.begin():
                run = session.get_one(AgentRun, run_id)
                cost = session.scalar(
                    select(func.coalesce(func.sum(LlmCall.cost_usd), 0)).where(
                        LlmCall.run_id == run_id
                    )
                )
                summary.cost_usd = str(cost)
                run.finished_at = datetime.now(UTC)
                run.status = status if summary.failed == 0 else "partial"
                run.stats = summary.as_dict()
            log.info("agent_run_finished", **summary.as_dict())
        return summary
