"""Scoring: how close is an extraction to the answer key, and how good are the decisions."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any

from opsagent.domain.parsing import normalize_invoice_number, normalize_name
from opsagent.domain.schemas import DecisionAction, ExtractedInvoice

FIELDS = (
    "vendor_name",
    "vendor_tax_id",
    "invoice_number",
    "issue_date",
    "po_number",
    "subtotal",
    "tax",
    "total",
    "line_items",
)
# The fields that must all be right for the invoice to reconcile correctly.
CRITICAL_FIELDS = ("vendor_tax_id", "invoice_number", "po_number", "total")
ACTIONS = [a.value for a in DecisionAction]


def field_matches(name: str, expected: ExtractedInvoice, actual: ExtractedInvoice) -> bool:
    exp, act = getattr(expected, name), getattr(actual, name)
    if name == "vendor_name":
        return SequenceMatcher(None, normalize_name(exp), normalize_name(act)).ratio() >= 0.9
    if name == "invoice_number":
        return normalize_invoice_number(exp) == normalize_invoice_number(act)
    if name == "line_items":
        return len(exp) == len(act) and all(
            e.total == a.total and e.quantity == a.quantity for e, a in zip(exp, act, strict=True)
        )
    if isinstance(exp, Decimal | date) or exp is None:
        return bool(exp == act)
    return str(exp).strip().upper() == str(act or "").strip().upper()


@dataclass
class InvoiceOutcome:
    file: str
    split: str
    scenario: str
    render: str
    expected_action: str
    action: str
    expected_findings: list[str]
    findings: list[str]
    extracted: bool
    method: str | None
    field_hits: dict[str, bool] = field(default_factory=dict)
    cost_usd: Decimal = Decimal(0)
    latency_ms: int = 0
    llm_calls: int = 0
    error: str | None = None

    @property
    def critical_ok(self) -> bool:
        return self.extracted and all(self.field_hits.get(f, False) for f in CRITICAL_FIELDS)


def _pct(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(pct * (len(ordered) - 1)))]


def summarize(outcomes: list[InvoiceOutcome]) -> dict[str, Any]:
    n = len(outcomes)
    extracted = [o for o in outcomes if o.extracted]
    field_accuracy = {
        f: _pct(sum(o.field_hits.get(f, False) for o in extracted), len(extracted)) for f in FIELDS
    }
    by_render: dict[str, dict[str, Any]] = {}
    for render in sorted({o.render for o in outcomes}):
        group = [o for o in outcomes if o.render == render]
        by_render[render] = {
            "n": len(group),
            "critical_fields_ok": _pct(sum(o.critical_ok for o in group), len(group)),
            "decision_accuracy": _pct(
                sum(o.action == o.expected_action for o in group), len(group)
            ),
        }

    confusion = {exp: dict.fromkeys(ACTIONS, 0) for exp in ACTIONS}
    for o in outcomes:
        confusion[o.expected_action][o.action] += 1
    predicted_auto = [o for o in outcomes if o.action == DecisionAction.AUTO_APPROVE]
    expected_auto = [o for o in outcomes if o.expected_action == DecisionAction.AUTO_APPROVE]
    false_approvals = [o for o in predicted_auto if o.expected_action != o.action]
    finding_hits = sum(len(set(o.expected_findings) & set(o.findings)) for o in outcomes)
    finding_total = sum(len(o.expected_findings) for o in outcomes)

    latencies = [o.latency_ms for o in outcomes if o.llm_calls]
    total_cost = sum((o.cost_usd for o in outcomes), Decimal(0))
    return {
        "invoices": n,
        "extraction": {
            "success_rate": _pct(len(extracted), n),
            "critical_fields_ok": _pct(sum(o.critical_ok for o in outcomes), n),
            "field_accuracy": field_accuracy,
            "by_render": by_render,
        },
        "decisions": {
            "accuracy": _pct(sum(o.action == o.expected_action for o in outcomes), n),
            "auto_approve_precision": _pct(
                len(predicted_auto) - len(false_approvals), len(predicted_auto)
            ),
            "auto_approve_recall": _pct(
                sum(o.action == o.expected_action for o in expected_auto), len(expected_auto)
            ),
            "false_approvals": [o.file for o in false_approvals],
            "findings_recall": _pct(finding_hits, finding_total),
            "confusion": confusion,
            "per_scenario": {
                s: _pct(
                    sum(o.action == o.expected_action for o in outcomes if o.scenario == s),
                    sum(o.scenario == s for o in outcomes),
                )
                for s in sorted({o.scenario for o in outcomes})
            },
        },
        "cost": {
            "total_usd": str(total_cost),
            "per_invoice_usd": str((total_cost / n).quantize(Decimal("0.000001"))) if n else None,
            "latency_p50_ms": _percentile(latencies, 0.5),
            "latency_p95_ms": _percentile(latencies, 0.95),
            "llm_calls": sum(o.llm_calls for o in outcomes),
        },
        "errors": Counter(o.error.split(":")[0] for o in outcomes if o.error),
    }
