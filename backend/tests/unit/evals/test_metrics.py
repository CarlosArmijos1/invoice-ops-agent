from decimal import Decimal

from opsagent.domain.schemas import ExtractedInvoice
from opsagent.evals.metrics import InvoiceOutcome, field_matches, summarize

BASE = ExtractedInvoice.model_validate(
    {
        "vendor_name": "Distribuidora Andina del Sur S.A.",
        "vendor_tax_id": "1790016919001",
        "invoice_number": "001-001-000004567",
        "issue_date": "2026-09-01",
        "po_number": "OC-2026-0101",
        "line_items": [{"description": "x", "quantity": 1, "unit_price": 10, "total": 10}],
        "subtotal": "10",
        "tax": "1.50",
        "total": "11.50",
    }
)


def test_field_matching_tolerates_formatting_but_not_wrong_values() -> None:
    variant = BASE.model_copy(
        update={
            "invoice_number": "001001000004567",
            "vendor_name": "DISTRIBUIDORA ANDINA DEL SUR SA",
        }
    )
    wrong = BASE.model_copy(update={"total": Decimal("11.60"), "po_number": "OC-2026-0110"})

    assert field_matches("invoice_number", BASE, variant)
    assert field_matches("vendor_name", BASE, variant)
    assert not field_matches("total", BASE, wrong)
    assert not field_matches("po_number", BASE, wrong)


def _outcome(expected: str, action: str, **kw: object) -> InvoiceOutcome:
    return InvoiceOutcome(
        file=f"{expected}-{action}",
        split="test",
        scenario="s",
        render="pdf_text",
        expected_action=expected,
        action=action,
        expected_findings=[],
        findings=[],
        extracted=True,
        method="text",
        **kw,  # type: ignore[arg-type]
    )


def test_summary_counts_false_approvals_and_precision() -> None:
    outcomes = [
        _outcome("auto_approve", "auto_approve"),
        _outcome("auto_approve", "human_review"),
        _outcome("human_review", "auto_approve"),  # the dangerous mistake
        _outcome("request_info", "request_info"),
    ]
    decisions = summarize(outcomes)["decisions"]

    assert decisions["accuracy"] == 0.5
    assert decisions["auto_approve_precision"] == 0.5
    assert decisions["auto_approve_recall"] == 0.5
    assert decisions["false_approvals"] == ["human_review-auto_approve"]
    assert decisions["confusion"]["human_review"]["auto_approve"] == 1
