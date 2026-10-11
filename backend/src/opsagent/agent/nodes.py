"""Graph nodes. Each takes the state and returns a partial update.

Only two nodes talk to an LLM (`extract`, `investigate`). Reconciliation and
the decision are deterministic. `investigate` is best-effort: if it fails the
invoice still gets its decision with the rule-based justification.
"""

import json
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from opsagent.agent.deps import AgentDeps
from opsagent.agent.prompts import INVESTIGATOR_SYSTEM, INVESTIGATOR_USER
from opsagent.agent.state import AgentState, LLMCallRecord
from opsagent.domain.findings import Finding, FindingCode, Severity
from opsagent.domain.policy import decide as apply_policy
from opsagent.domain.quality import assess_extraction
from opsagent.domain.reconciliation import reconcile as reconcile_invoice
from opsagent.domain.schemas import DecisionAction, ExtractedInvoice, InvoiceStatus
from opsagent.extraction.documents import UnsupportedDocumentError, prepare_document
from opsagent.extraction.extractor import parse_json_object
from opsagent.infra.db.ledger import SqlLedger
from opsagent.infra.db.models import (
    AuditEvent,
    Decision,
    Extraction,
    Invoice,
    InvoiceFile,
    LlmCall,
)
from opsagent.infra.logging import get_logger
from opsagent.llm.base import (
    CompletionRequest,
    LLMResponse,
    assistant_tool_calls_message,
    text_message,
    tool_result_message,
)
from opsagent.llm.errors import LLMError
from opsagent.tools.lookup import TOOLS_BY_NAME, openai_tools

log = get_logger(__name__)


def _call_record(response: LLMResponse, purpose: str) -> LLMCallRecord:
    return LLMCallRecord(
        purpose=purpose,
        provider=response.provider,
        model=response.model,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        cost_usd=str(response.cost_usd),
        latency_ms=response.latency_ms,
        ok=True,
        error=None,
    )


def _findings(state: AgentState) -> list[Finding]:
    return [Finding.model_validate(f) for f in state.get("findings", [])]


class Nodes:
    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps

    # ------------------------------------------------------------------ extract

    def extract(self, state: AgentState) -> dict[str, Any]:
        invoice_id = uuid.UUID(state["invoice_id"])
        with self.deps.session_factory() as session:
            invoice = session.get_one(Invoice, invoice_id)
            content = session.get_one(InvoiceFile, invoice.file_sha256).content

        try:
            doc = prepare_document(content)
        except UnsupportedDocumentError as exc:
            return {"method": "none", "extraction": None, "extraction_error": str(exc)}

        result = self.deps.extractor.extract(doc, content)  # LLMError propagates on purpose
        update: dict[str, Any] = {
            "method": result.method,
            "source_text": doc.text if result.method == "text" else None,
            "extraction_model": result.model,
            "prompt_version": result.prompt_version,
            "extraction_raw": result.raw,
            "llm_calls": [_call_record(c, "extract") for c in result.calls],
        }
        if result.invoice is None:
            update |= {"extraction": None, "extraction_error": result.error}
        else:
            update |= {
                "extraction": result.invoice.model_dump(mode="json"),
                "extraction_error": None,
            }
        log.info("invoice_extracted", method=result.method, ok=result.ok, calls=len(result.calls))
        return update

    @staticmethod
    def route_after_extract(state: AgentState) -> str:
        return "reconcile" if state.get("extraction") else "decide"

    # ------------------------------------------------------------------ reconcile

    def reconcile(self, state: AgentState) -> dict[str, Any]:
        invoice = ExtractedInvoice.model_validate(state["extraction"])
        quality = assess_extraction(
            invoice, today=self.deps.today(), source_text=state.get("source_text")
        )
        with self.deps.session_factory() as session:
            result = reconcile_invoice(
                invoice,
                invoice_id=uuid.UUID(state["invoice_id"]),
                ledger=SqlLedger(session),
                quality=quality,
                config=self.deps.policy,
            )
        return {
            "quality": {"score": quality.score, "failed_checks": quality.failed_checks},
            "findings": [f.model_dump(mode="json") for f in result.findings],
            "vendor_id": result.vendor.id if result.vendor else None,
            "vendor_tax_id": result.vendor.tax_id if result.vendor else invoice.vendor_tax_id,
            "po_id": result.purchase_order.id if result.purchase_order else None,
        }

    # ------------------------------------------------------------------ decide

    def decide(self, state: AgentState) -> dict[str, Any]:
        findings = _findings(state)
        if not state.get("extraction"):
            findings = [
                Finding(
                    code=FindingCode.EXTRACTION_FAILED,
                    message=(
                        "No se pudieron leer los datos de la factura "
                        f"({(state.get('extraction_error') or '').strip()[:300]})."
                    ),
                )
            ]
        decision = apply_policy(findings)
        update: dict[str, Any] = {
            "findings": [f.model_dump(mode="json") for f in findings],
            "action": decision.action.value,
            "justification": decision.justification,
            "summary": None,
            "supplier_message": None,
        }
        if decision.action is DecisionAction.REQUEST_INFO:
            update["supplier_message"] = self._default_supplier_message(decision.blocking)
        log.info("invoice_decided", action=decision.action.value)
        return update

    @staticmethod
    def _default_supplier_message(blocking: list[Finding]) -> str:
        items = "\n".join(f"- {f.message}" for f in blocking)
        return (
            "Estimado proveedor:\n\nPara procesar su factura necesitamos que nos ayude con lo "
            f"siguiente:\n{items}\n\nPor favor responda a este correo con la información o "
            "una copia corregida/legible de la factura.\n\nSaludos cordiales,\nCuentas por Pagar"
        )

    @staticmethod
    def route_after_decide(state: AgentState) -> str:
        return "persist" if state["action"] == DecisionAction.AUTO_APPROVE else "investigate"

    # ------------------------------------------------------------------ investigate

    def investigate(self, state: AgentState) -> dict[str, Any]:
        """Function-calling loop over read-only tools. Best effort, bounded, never raises."""
        if not self.deps.investigate:
            return {}
        risky = [
            f.model_dump(mode="json", include={"code", "message"})
            for f in _findings(state)
            if f.severity is not Severity.INFO
        ]
        messages: list[dict[str, Any]] = [
            text_message("system", INVESTIGATOR_SYSTEM),
            text_message(
                "user",
                INVESTIGATOR_USER.format(
                    action=state["action"],
                    invoice=json.dumps(state.get("extraction"), ensure_ascii=False),
                    findings=json.dumps(risky, ensure_ascii=False),
                ),
            ),
        ]
        calls: list[LLMCallRecord] = []
        trace: list[dict[str, Any]] = []
        tools = openai_tools()
        try:
            with self.deps.session_factory() as session:
                for round_no in range(self.deps.max_tool_rounds + 1):
                    last_round = round_no == self.deps.max_tool_rounds
                    response = self.deps.llm.complete(
                        CompletionRequest(
                            model=self.deps.reasoning_model,
                            messages=messages,
                            temperature=0.0,
                            max_tokens=2048,
                            extra=dict(self.deps.reasoning_extra),
                            tools=None if last_round else tools,
                        )
                    )
                    calls.append(_call_record(response, "investigate"))
                    if not response.tool_calls:
                        answer = parse_json_object(response.content)
                        update: dict[str, Any] = {
                            "summary": str(answer.get("summary") or "").strip() or None,
                            "investigation": trace,
                            "llm_calls": calls,
                        }
                        recommendation = str(answer.get("recommendation") or "").strip()
                        if recommendation and update["summary"]:
                            update["summary"] += f"\n\nRecomendación: {recommendation}"
                        if state["action"] == DecisionAction.REQUEST_INFO and answer.get(
                            "supplier_message"
                        ):
                            update["supplier_message"] = str(answer["supplier_message"]).strip()
                        return update
                    messages.append(
                        assistant_tool_calls_message(response.content, response.tool_calls)
                    )
                    for call in response.tool_calls:
                        tool = TOOLS_BY_NAME.get(call.name)
                        output = (
                            tool.run(session, call.arguments)
                            if tool
                            else json.dumps({"error": f"unknown tool {call.name}"})
                        )
                        trace.append(
                            {"tool": call.name, "arguments": call.arguments, "result": output[:800]}
                        )
                        messages.append(tool_result_message(call, output))
        except (LLMError, ValueError) as exc:
            log.warning("investigation_failed", error=type(exc).__name__, detail=str(exc)[:200])
            failed = LLMCallRecord(
                purpose="investigate",
                provider=self.deps.llm.provider,
                model=self.deps.reasoning_model,
                prompt_tokens=0,
                completion_tokens=0,
                cost_usd="0",
                latency_ms=0,
                ok=False,
                error=f"{type(exc).__name__}: {str(exc)[:300]}",
            )
            return {"investigation": trace, "llm_calls": [*calls, failed]}
        return {"investigation": trace, "llm_calls": calls}

    # ------------------------------------------------------------------ persist

    def persist(self, state: AgentState) -> dict[str, Any]:
        """Write everything in one transaction. Idempotent: a decided invoice is left alone."""
        invoice_id = uuid.UUID(state["invoice_id"])
        run_id = uuid.UUID(state["run_id"]) if state.get("run_id") else None
        action = DecisionAction(state["action"])
        calls = state.get("llm_calls", [])
        cost = sum((Decimal(c["cost_usd"]) for c in calls), Decimal(0))
        elapsed_ms = int((time.time() - state.get("started_at", time.time())) * 1000)

        with self.deps.session_factory() as session, session.begin():
            invoice = session.get_one(Invoice, invoice_id, with_for_update=True)
            if invoice.status is InvoiceStatus.DECIDED:
                log.info("persist_skipped_already_decided")
                return {}

            extraction = state.get("extraction")
            quality = state.get("quality") or {}
            session.add(
                Extraction(
                    invoice_id=invoice_id,
                    method=state.get("method", "none"),
                    model=state.get("extraction_model", ""),
                    data=extraction,
                    valid=extraction is not None,
                    quality_score=quality.get("score"),
                    issues=[{"check": c} for c in quality.get("failed_checks", [])],
                    error=state.get("extraction_error"),
                )
            )
            justification = state["justification"]
            if state.get("summary"):
                justification = f"{state['summary']}\n\n{justification}"
            session.add(
                Decision(
                    invoice_id=invoice_id,
                    action=action,
                    actor="agent",
                    findings=state.get("findings", []),
                    justification=justification,
                    supplier_message=state.get("supplier_message"),
                    matched_po_id=state.get("po_id"),
                )
            )
            for call in calls:
                session.add(
                    LlmCall(
                        invoice_id=invoice_id,
                        run_id=run_id,
                        purpose=call["purpose"],
                        provider=call["provider"],
                        model=call["model"],
                        prompt_tokens=call["prompt_tokens"],
                        completion_tokens=call["completion_tokens"],
                        cost_usd=Decimal(call["cost_usd"]),
                        latency_ms=call["latency_ms"],
                        ok=call["ok"],
                        error=call["error"],
                    )
                )
            if extraction:
                parsed = ExtractedInvoice.model_validate(extraction)
                invoice.vendor_id = state.get("vendor_id")
                invoice.vendor_name = parsed.vendor_name
                invoice.vendor_tax_id = state.get("vendor_tax_id")
                invoice.invoice_number = parsed.invoice_number
                invoice.invoice_number_normalized = parsed.normalized_number
                invoice.po_number = parsed.po_number
                invoice.issue_date = parsed.issue_date
                invoice.total = parsed.total
                invoice.currency = parsed.currency
            invoice.matched_po_id = state.get("po_id")
            invoice.current_action = action
            invoice.approved = True if action is DecisionAction.AUTO_APPROVE else None
            invoice.status = InvoiceStatus.DECIDED
            invoice.processed_at = datetime.now(UTC)
            invoice.processing_ms = elapsed_ms
            invoice.llm_cost_usd = cost
            invoice.last_error = None
            session.add(
                AuditEvent(
                    invoice_id=invoice_id,
                    run_id=run_id,
                    event="decided",
                    payload={
                        "action": action.value,
                        "findings": [f["code"] for f in state.get("findings", [])],
                        "cost_usd": str(cost),
                        "processing_ms": elapsed_ms,
                        "tools_used": [t["tool"] for t in state.get("investigation", [])],
                    },
                )
            )
        log.info("invoice_persisted", action=action.value, cost_usd=str(cost), ms=elapsed_ms)
        return {}
