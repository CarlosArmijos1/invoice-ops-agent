"""MCP server: the agent's capabilities as tools for Claude Code or any MCP client.

    uv run python -m opsagent.mcp_server            # stdio (Claude Code, Claude Desktop)
    uv run python -m opsagent.mcp_server --http     # streamable HTTP on :8765/mcp

Tools reuse the exact same services as the REST API and the scheduler: there is
no second implementation of any business rule here. Read-only tools are
annotated as such so clients can auto-approve them; tools that change state
(ingest, process, review) are not, so the client asks the user first.
"""

import argparse
import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from sqlalchemy import select

from opsagent.container import Container, build_container
from opsagent.domain.schemas import DecisionAction, InvoiceSource, InvoiceStatus, ReviewOutcome
from opsagent.extraction.documents import UnsupportedDocumentError
from opsagent.infra.db.models import DailyReport
from opsagent.services.ingestion import ingest_bytes
from opsagent.services.reporting import generate_daily_report
from opsagent.services.reviews import ReviewError, review_invoice
from opsagent.services.views import invoice_detail, list_invoices, stats
from opsagent.settings import get_settings
from opsagent.tools import lookup

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

INSTRUCTIONS = """\
Accounts-payable agent for Ecuadorian supplier invoices (synthetic demo data).
It extracts invoices with an LLM, reconciles them against purchase orders and
bank payments in Postgres, and routes each one to auto_approve, human_review or
request_info with a justification. Use the read-only tools to investigate; only
call review_invoice when the user explicitly decides an outcome."""


def build_server(container: Container) -> MCPServer:
    server = MCPServer(name="invoice-ops-agent", instructions=INSTRUCTIONS)
    factory = container.session_factory

    # ------------------------------------------------------------- invoices

    @server.tool(name="list_invoices", annotations=READ_ONLY)
    def list_invoices_tool(
        status: Literal["received", "processing", "decided", "failed"] | None = None,
        action: Literal["auto_approve", "human_review", "request_info"] | None = None,
        needs_review: bool = False,
        query: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List invoices, newest first. `needs_review=true` returns the human review queue.

        `query` matches vendor, invoice number, PO number or file name.
        """
        with factory() as session:
            items, total = list_invoices(
                session,
                status=InvoiceStatus(status) if status else None,
                action=DecisionAction(action) if action else None,
                needs_review=needs_review,
                query=query,
                limit=max(1, min(limit, 100)),
            )
        return {
            "total": total,
            "items": [
                item.model_dump(
                    mode="json",
                    include={
                        "id",
                        "original_filename",
                        "status",
                        "current_action",
                        "approved",
                        "vendor_name",
                        "invoice_number",
                        "po_number",
                        "total",
                        "finding_codes",
                    },
                )
                for item in items
            ],
        }

    @server.tool(annotations=READ_ONLY)
    def get_invoice(invoice_id: str) -> dict[str, Any]:
        """Full detail of one invoice: extraction, findings, decisions and audit trail."""
        with factory() as session:
            detail = invoice_detail(session, uuid.UUID(invoice_id))
        if detail is None:
            return {"error": "invoice not found"}
        data = detail.model_dump(mode="json", exclude={"llm_calls"})
        data["llm_cost_usd"] = str(detail.llm_cost_usd)
        return data

    @server.tool(annotations=READ_ONLY)
    def get_stats() -> dict[str, Any]:
        """Operational metrics: volumes by decision, auto-approval rate, cost and latency."""
        with factory() as session:
            return stats(session).model_dump(mode="json")

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True))
    def ingest_invoice(file_path: str) -> dict[str, Any]:
        """Register an invoice file (PDF/PNG/JPG) from a path readable by this server.

        Idempotent: the same file content is never registered twice.
        """
        path = Path(file_path).expanduser()
        if not path.is_file():
            return {"error": f"file not found: {path}"}
        try:
            with factory() as session, session.begin():
                result = ingest_bytes(session, path.read_bytes(), path.name, InvoiceSource.UPLOAD)
        except UnsupportedDocumentError as exc:
            return {"error": str(exc)}
        return {"invoice_id": str(result.invoice_id), "created": result.created}

    @server.tool(annotations=WRITES)
    def process_invoice(invoice_id: str) -> dict[str, Any]:
        """Run the agent now on one received or failed invoice and return its decision."""
        action = container.processor.process_one(uuid.UUID(invoice_id))
        return {"invoice_id": invoice_id, "action": action}

    @server.tool(annotations=WRITES)
    def process_pending(limit: int = 20) -> dict[str, Any]:
        """Run the agent over everything pending (what the scheduler does periodically)."""
        summary = container.processor.process_pending(trigger="mcp", limit=max(1, min(limit, 200)))
        return summary.as_dict()

    @server.tool(name="review_invoice", annotations=WRITES)
    def review_invoice_tool(
        invoice_id: str,
        outcome: Literal["approved", "rejected"],
        reviewer: str,
        note: str = "",
    ) -> dict[str, Any]:
        """Record a HUMAN decision on an invoice the agent flagged. Only call this when the
        user has explicitly decided; never approve on your own initiative."""
        try:
            with factory() as session, session.begin():
                decision = review_invoice(
                    session,
                    uuid.UUID(invoice_id),
                    outcome=ReviewOutcome(outcome),
                    reviewer=f"{reviewer} (via MCP)",
                    note=note,
                )
                return {"decision_id": decision.id, "outcome": outcome}
        except ReviewError as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------- reports

    @server.tool(annotations=READ_ONLY)
    def get_daily_report(day: str | None = None) -> str:
        """Markdown daily report for `day` (YYYY-MM-DD); defaults to the most recent one."""
        with factory() as session:
            query = select(DailyReport).order_by(DailyReport.report_date.desc())
            if day:
                query = select(DailyReport).where(
                    DailyReport.report_date == date.fromisoformat(day)
                )
            report = session.scalars(query).first()
        return report.markdown if report else "No report yet: call generate_daily_report."

    @server.tool(name="generate_daily_report", annotations=WRITES)
    def generate_daily_report_tool(day: str | None = None) -> str:
        """Build (or refresh) the daily report for `day` (YYYY-MM-DD, default today)."""
        with factory() as session, session.begin():
            report = generate_daily_report(session, date.fromisoformat(day) if day else None)
            return report.markdown

    # ------------------------------------------------------------- lookups

    def _lookup(tool_name: str, **arguments: Any) -> Any:
        tool = lookup.TOOLS_BY_NAME[tool_name]
        with factory() as session:
            return json.loads(tool.run(session, json.dumps(arguments, default=str)))

    @server.tool(annotations=READ_ONLY)
    def search_vendors(query: str) -> Any:
        """Search registered vendors by approximate name or partial RUC."""
        return _lookup("search_vendors", query=query)

    @server.tool(annotations=READ_ONLY)
    def list_open_purchase_orders(vendor_tax_id: str) -> Any:
        """Open purchase orders of a vendor (by RUC) with their totals."""
        return _lookup("list_open_purchase_orders", vendor_tax_id=vendor_tax_id)

    @server.tool(annotations=READ_ONLY)
    def get_purchase_order(po_number: str) -> Any:
        """A purchase order with its lines, vendor and totals."""
        return _lookup("get_purchase_order", po_number=po_number)

    @server.tool(annotations=READ_ONLY)
    def find_payments(
        vendor_tax_id: str, invoice_number: str | None = None, amount: str | None = None
    ) -> Any:
        """Bank payments to a vendor, optionally narrowed by invoice number or amount."""
        return _lookup(
            "find_payments",
            vendor_tax_id=vendor_tax_id,
            invoice_number=invoice_number,
            amount=amount,
        )

    # ------------------------------------------------------------- context

    @server.resource("invoice-ops://policy", mime_type="application/json")
    def policy() -> str:
        """The thresholds the deterministic policy applies."""
        settings = container.settings
        return json.dumps(
            {
                "auto_approval_limit_usd": str(settings.auto_approval_limit),
                "amount_tolerance": f"min({settings.amount_tolerance_abs} USD, "
                f"{settings.amount_tolerance_pct:%} of the PO total)",
                "min_extraction_quality": settings.min_quality_score,
                "precedence": "any risk finding -> human_review; else any missing info -> "
                "request_info; else auto_approve",
            }
        )

    @server.prompt()
    def triage_review_queue() -> str:
        """Walk through the human review queue and prepare a recommendation for each invoice."""
        return (
            "Use list_invoices with needs_review=true. For each invoice, call get_invoice "
            "and, when useful, get_purchase_order / find_payments / search_vendors to verify the "
            "findings. Then give me a table: file, vendor, total, problem, evidence, and your "
            "recommended outcome (approve / reject / ask supplier). Do NOT call "
            "review_invoice until I confirm each one."
        )

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="invoice-ops-agent MCP server")
    parser.add_argument("--http", action="store_true", help="serve streamable HTTP instead")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    # stdout is the MCP protocol channel in stdio mode: logs must go to stderr.
    settings = get_settings().model_copy(update={"log_stream": "stderr"})
    container = build_container(settings)
    server = build_server(container)
    try:
        if args.http:
            server.run(transport="streamable-http", port=args.port)
        else:
            server.run(transport="stdio")
    finally:
        container.close()
