"""Graph state. JSON-friendly on purpose: it is checkpointed to Postgres after every node."""

import operator
from typing import Annotated, Any, TypedDict


class LLMCallRecord(TypedDict):
    purpose: str  # extract | investigate
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: str
    latency_ms: int
    ok: bool
    error: str | None


class AgentState(TypedDict, total=False):
    invoice_id: str
    run_id: str | None
    started_at: float  # epoch seconds, for processing time

    # extract
    method: str
    source_text: str | None
    extraction: dict[str, Any] | None
    extraction_raw: dict[str, Any] | None
    extraction_error: str | None
    extraction_model: str
    prompt_version: str

    # reconcile
    quality: dict[str, Any]
    findings: list[dict[str, Any]]
    vendor_id: int | None
    vendor_tax_id: str | None
    po_id: int | None

    # decide / investigate
    action: str
    justification: str
    summary: str | None
    supplier_message: str | None
    investigation: list[dict[str, Any]]

    # Every node appends its LLM calls; the reducer concatenates them.
    llm_calls: Annotated[list[LLMCallRecord], operator.add]
