"""End-to-end agent runs against a real Postgres with a scripted LLM."""

import json
import uuid
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from opsagent.datagen.records import GroundTruth
from opsagent.domain.findings import FindingCode
from opsagent.domain.schemas import DecisionAction, InvoiceSource, InvoiceStatus
from opsagent.infra.db.models import AuditEvent, Decision, Extraction, Invoice, LlmCall
from opsagent.llm.base import CompletionRequest, ToolCall
from opsagent.llm.errors import LLMServerError
from opsagent.llm.fake import Outcome
from opsagent.services.ingestion import ingest_bytes
from opsagent.services.processing import InvoiceProcessor
from tests.integration.scripted import DATA, TRUTHS, ScriptedLLM, build_test_container, truth_for

pytestmark = pytest.mark.integration


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture
def processor(session_factory: sessionmaker[Session], llm: ScriptedLLM) -> InvoiceProcessor:
    return build_test_container(session_factory, llm).processor


def _ingest(factory: sessionmaker[Session], truth: GroundTruth) -> uuid.UUID:
    content = (DATA / "invoices" / truth.file).read_bytes()
    with factory() as session, session.begin():
        return ingest_bytes(session, content, truth.file, InvoiceSource.FOLDER).invoice_id


def _run(processor: InvoiceProcessor, llm: ScriptedLLM, truth: GroundTruth) -> uuid.UUID:
    invoice_id = _ingest(processor.deps.session_factory, truth)
    llm.current = truth
    processor.process_pending(trigger="test")
    return invoice_id


def _decisions(factory: sessionmaker[Session], invoice_id: uuid.UUID) -> list[Decision]:
    with factory() as session:
        return list(session.scalars(select(Decision).where(Decision.invoice_id == invoice_id)))


def test_clean_invoice_is_auto_approved_with_full_audit_trail(
    processor: InvoiceProcessor, llm: ScriptedLLM
) -> None:
    truth = truth_for("clean_unpaid", render="pdf_text")
    invoice_id = _run(processor, llm, truth)

    factory = processor.deps.session_factory
    with factory() as session:
        invoice = session.get_one(Invoice, invoice_id)
        assert invoice.status is InvoiceStatus.DECIDED
        assert invoice.current_action is DecisionAction.AUTO_APPROVE
        assert invoice.approved is True
        assert invoice.total == truth.extraction.total
        assert invoice.matched_po_id is not None
        assert invoice.llm_cost_usd > 0
        assert invoice.processing_ms is not None
        extraction = session.scalars(select(Extraction)).one()
        assert extraction.method == "text"
        assert extraction.quality_score == 1.0
        events = session.scalars(
            select(AuditEvent.event).where(AuditEvent.invoice_id == invoice_id)
        ).all()
        assert events == ["received", "decided"]
        purposes = session.scalars(select(LlmCall.purpose)).all()
        assert purposes == ["extract"]  # approved invoices skip the investigator
    [decision] = _decisions(factory, invoice_id)
    assert decision.actor == "agent"
    assert "todos los controles pasaron" in decision.justification


def test_same_file_twice_is_ingested_once(processor: InvoiceProcessor) -> None:
    truth = truth_for("clean_paid")
    first = _ingest(processor.deps.session_factory, truth)
    second = _ingest(processor.deps.session_factory, truth)
    assert first == second


def test_resent_invoice_in_another_format_is_flagged_as_duplicate(
    processor: InvoiceProcessor, llm: ScriptedLLM
) -> None:
    duplicate = truth_for("duplicate_resend")
    original = TRUTHS[duplicate.duplicate_of or ""]

    _run(processor, llm, original)
    dup_id = _run(processor, llm, duplicate)

    [decision] = _decisions(processor.deps.session_factory, dup_id)
    assert decision.action is DecisionAction.HUMAN_REVIEW
    assert FindingCode.DUPLICATE_INVOICE in {f["code"] for f in decision.findings}


def test_investigator_calls_tools_and_its_summary_reaches_the_reviewer(
    processor: InvoiceProcessor, llm: ScriptedLLM
) -> None:
    truth = truth_for("amount_mismatch")
    llm.investigation = [
        (
            ToolCall(
                id="call_1",
                name="get_purchase_order",
                arguments=json.dumps({"po_number": truth.extraction.po_number}),
            ),
        ),
        json.dumps(
            {
                "summary": "La factura cobra unidades extra respecto de la OC.",
                "recommendation": "Confirmar la entrega con bodega.",
                "supplier_message": None,
            }
        ),
    ]
    invoice_id = _run(processor, llm, truth)

    [decision] = _decisions(processor.deps.session_factory, invoice_id)
    assert decision.action is DecisionAction.HUMAN_REVIEW
    assert decision.justification.startswith("La factura cobra unidades extra")
    assert "Recomendación: Confirmar la entrega" in decision.justification
    tool_result = llm.requests[-1].messages[-1]
    assert tool_result["role"] == "tool"
    assert truth.extraction.po_number in tool_result["content"]
    with processor.deps.session_factory() as session:
        payload = session.scalars(
            select(AuditEvent.payload).where(AuditEvent.event == "decided")
        ).one()
    assert payload["tools_used"] == ["get_purchase_order"]


def test_investigator_failure_does_not_block_the_decision(
    processor: InvoiceProcessor, llm: ScriptedLLM
) -> None:
    llm.investigation = [LLMServerError("down")]
    invoice_id = _run(processor, llm, truth_for("vendor_mismatch"))

    [decision] = _decisions(processor.deps.session_factory, invoice_id)
    assert decision.action is DecisionAction.HUMAN_REVIEW
    assert decision.justification.startswith("Enviada a revisión humana")


def test_unreadable_invoice_requests_a_better_copy(
    processor: InvoiceProcessor, llm: ScriptedLLM
) -> None:
    truth = truth_for("clean_unpaid", render="jpg")
    invoice_id = _ingest(processor.deps.session_factory, truth)
    llm.current = truth
    llm.fail_extraction_with = None
    original_respond = llm._respond

    def garbage(request: CompletionRequest) -> Outcome:
        return "no puedo leer esto" if request.tools is None else original_respond(request)

    llm._responder = garbage
    processor.process_pending(trigger="test")

    [decision] = _decisions(processor.deps.session_factory, invoice_id)
    assert decision.action is DecisionAction.REQUEST_INFO
    assert [f["code"] for f in decision.findings] == [FindingCode.EXTRACTION_FAILED]
    assert decision.supplier_message


def test_provider_outage_leaves_invoice_failed_then_backs_off_then_recovers(
    processor: InvoiceProcessor, llm: ScriptedLLM
) -> None:
    truth = truth_for("clean_paid")
    invoice_id = _ingest(processor.deps.session_factory, truth)
    llm.current = truth
    llm.fail_extraction_with = LLMServerError("503 from provider")

    first = processor.process_pending(trigger="test")
    again = processor.process_pending(trigger="test")  # still inside the back-off window

    assert (first.failed, again.failed, again.processed) == (1, 0, 0)
    with processor.deps.session_factory() as session:
        invoice = session.get_one(Invoice, invoice_id)
        assert invoice.status is InvoiceStatus.FAILED
        assert invoice.attempts == 1
        assert invoice.last_error is not None
        assert "503" in invoice.last_error
    assert _decisions(processor.deps.session_factory, invoice_id) == []  # no business outcome

    llm.fail_extraction_with = None
    assert processor.process_one(invoice_id) == DecisionAction.AUTO_APPROVE


def test_crash_after_extraction_resumes_without_paying_the_llm_again(
    processor: InvoiceProcessor, llm: ScriptedLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    truth = truth_for("clean_unpaid", render="pdf_text")
    invoice_id = _ingest(processor.deps.session_factory, truth)
    llm.current = truth

    from opsagent.agent import nodes as nodes_module

    real_reconcile = nodes_module.Nodes.reconcile
    crashes = {"left": 1}

    def flaky_reconcile(self: Any, state: Any) -> Any:
        if crashes["left"]:
            crashes["left"] -= 1
            raise RuntimeError("worker killed")
        return real_reconcile(self, state)

    monkeypatch.setattr(nodes_module.Nodes, "reconcile", flaky_reconcile)
    processor = InvoiceProcessor(processor.deps, InMemorySaver())  # rebuild graph with the patch

    assert processor.process_one(invoice_id) is None  # crashed in reconcile
    calls_after_crash = len(llm.requests)
    assert processor.process_one(invoice_id) == DecisionAction.AUTO_APPROVE
    assert len(llm.requests) == calls_after_crash  # extraction came from the checkpoint
