import uuid
from datetime import date
from decimal import Decimal

import pytest

from opsagent.datagen.records import (
    Catalog,
    LineRecord,
    PaymentRecord,
    PurchaseOrderRecord,
    VendorRecord,
)
from opsagent.domain.findings import FindingCode
from opsagent.domain.policy import decide
from opsagent.domain.quality import QualityReport
from opsagent.domain.reconciliation import PolicyConfig, reconcile, resolve_vendor
from opsagent.domain.schemas import DecisionAction, ExtractedInvoice
from opsagent.infra.memory_ledger import InMemoryLedger

F = FindingCode
ANDINA = "1790016919001"
OTHER = "1760001550001"
CONFIG = PolicyConfig()
CLEAN = QualityReport(score=1.0)


def _po(number: str, total: str, tax_id: str = ANDINA) -> PurchaseOrderRecord:
    amount = Decimal(total)
    return PurchaseOrderRecord(
        po_number=number,
        vendor_tax_id=tax_id,
        issue_date=date(2026, 8, 1),
        subtotal=amount,
        tax=Decimal(0),
        total=amount,
        lines=[LineRecord(description="x", quantity=1, unit_price=amount, total=amount)],
    )


def _ledger(payments: list[PaymentRecord] | None = None) -> InMemoryLedger:
    return InMemoryLedger(
        Catalog(
            vendors=[
                VendorRecord(
                    name="Distribuidora Andina del Sur S.A.",
                    tax_id=ANDINA,
                    email="a@x",
                    aliases=["DIST. ANDINA DEL SUR"],
                ),
                VendorRecord(name="Otra Empresa S.A.", tax_id=OTHER, email="b@x"),
            ],
            purchase_orders=[
                _po("OC-1", "1150.00"),
                _po("OC-2", "200.00"),
                _po("OC-9", "300.00", tax_id=OTHER),
                _po("OC-BIG", "9200.00"),
            ],
            payments=payments or [],
        )
    )


def _invoice(**overrides: object) -> ExtractedInvoice:
    base: dict[str, object] = {
        "vendor_name": "Distribuidora Andina del Sur S.A.",
        "vendor_tax_id": ANDINA,
        "invoice_number": "001-001-000004567",
        "issue_date": "2026-09-01",
        "po_number": "OC-1",
        "subtotal": "1000.00",
        "tax": "150.00",
        "total": "1150.00",
    }
    return ExtractedInvoice.model_validate(base | overrides)


def _run(
    invoice: ExtractedInvoice, ledger: InMemoryLedger | None = None
) -> tuple[set[FindingCode], DecisionAction]:
    result = reconcile(
        invoice, invoice_id=uuid.uuid4(), ledger=ledger or _ledger(), quality=CLEAN, config=CONFIG
    )
    return result.codes, decide(result.findings).action


def test_clean_match_is_auto_approved() -> None:
    codes, action = _run(_invoice())
    assert codes == {F.PO_MATCHED, F.UNPAID}
    assert action is DecisionAction.AUTO_APPROVE


def test_cents_of_rounding_are_tolerated() -> None:
    codes, action = _run(_invoice(subtotal="1000.03", total="1150.03"))
    assert F.AMOUNT_WITHIN_TOLERANCE in codes
    assert action is DecisionAction.AUTO_APPROVE


def test_tolerance_is_relative_on_small_amounts() -> None:
    # 0.5% of 200 = 1.00 -> 0.99 ok; on a 20.00 PO it would be only 0.10.
    assert CONFIG.tolerance_for(Decimal("200")) == Decimal("1.000")
    assert CONFIG.tolerance_for(Decimal("20")) == Decimal("0.100")


def test_amount_difference_goes_to_review() -> None:
    codes, action = _run(_invoice(subtotal="1010.00", total="1160.00"))
    assert F.AMOUNT_MISMATCH in codes
    assert action is DecisionAction.HUMAN_REVIEW


def test_po_of_another_vendor_goes_to_review() -> None:
    codes, action = _run(_invoice(po_number="OC-9"))
    assert F.PO_VENDOR_MISMATCH in codes
    assert action is DecisionAction.HUMAN_REVIEW


def test_unknown_po_requests_info() -> None:
    codes, action = _run(_invoice(po_number="OC-404"))
    assert F.PO_NOT_FOUND in codes
    assert action is DecisionAction.REQUEST_INFO


def test_missing_po_with_single_candidate_is_inferred_but_not_auto_approved() -> None:
    codes, action = _run(_invoice(po_number=None))
    assert F.PO_INFERRED in codes
    assert action is DecisionAction.HUMAN_REVIEW


def test_missing_po_without_candidate_requests_info() -> None:
    codes, action = _run(_invoice(po_number=None, subtotal="10", tax="1.50", total="11.50"))
    assert F.PO_MISSING in codes
    assert action is DecisionAction.REQUEST_INFO


def test_unknown_vendor_takes_precedence_over_missing_info() -> None:
    codes, action = _run(_invoice(vendor_tax_id="0990000000001", po_number="OC-404"))
    assert {F.VENDOR_UNKNOWN, F.PO_NOT_FOUND} <= codes
    assert action is DecisionAction.HUMAN_REVIEW


def test_over_limit_needs_a_human_even_when_everything_matches() -> None:
    codes, action = _run(_invoice(po_number="OC-BIG", subtotal="8000", tax="1200", total="9200"))
    assert F.OVER_AUTO_APPROVAL_LIMIT in codes
    assert action is DecisionAction.HUMAN_REVIEW


@pytest.mark.parametrize("memo", ["001-001-000004567", "001001000004567", "4567", None])
def test_payment_is_matched_by_memo_variants_or_po(memo: str | None) -> None:
    payment = PaymentRecord(
        reference="TRF-1",
        vendor_tax_id=ANDINA,
        amount=Decimal("1150.00"),
        paid_on=date(2026, 9, 10),
        invoice_number=memo,
        po_number="OC-1" if memo is None else None,
    )
    codes, action = _run(_invoice(), _ledger([payment]))
    assert F.PAID in codes
    assert action is DecisionAction.AUTO_APPROVE


def test_short_payment_and_double_payment_go_to_review() -> None:
    def pay(ref: str, amount: str) -> PaymentRecord:
        return PaymentRecord(
            reference=ref,
            vendor_tax_id=ANDINA,
            amount=Decimal(amount),
            paid_on=date(2026, 9, 10),
            invoice_number="4567",
        )

    short_codes, _ = _run(_invoice(), _ledger([pay("T1", "1000.00")]))
    double_codes, action = _run(_invoice(), _ledger([pay("T1", "1150"), pay("T2", "1150")]))
    assert F.PAYMENT_AMOUNT_MISMATCH in short_codes
    assert F.MULTIPLE_PAYMENTS in double_codes
    assert action is DecisionAction.HUMAN_REVIEW


def test_resent_invoice_is_detected_as_duplicate_and_overbilling() -> None:
    ledger = _ledger()
    original = _invoice()
    first_id = uuid.uuid4()
    first = reconcile(original, invoice_id=first_id, ledger=ledger, quality=CLEAN, config=CONFIG)
    ledger.record(
        invoice_id=first_id,
        filename="INV-1.pdf",
        invoice=original,
        vendor=first.vendor,
        po=first.purchase_order,
        action=decide(first.findings).action,
    )

    codes, action = _run(_invoice(invoice_number="001001000004567"), ledger)

    assert {F.DUPLICATE_INVOICE, F.PO_OVERBILLED} <= codes
    assert action is DecisionAction.HUMAN_REVIEW


def test_low_quality_extraction_is_never_auto_approved() -> None:
    result = reconcile(
        _invoice(),
        invoice_id=uuid.uuid4(),
        ledger=_ledger(),
        quality=QualityReport(score=0.5, failed_checks=["total_not_in_source"]),
        config=CONFIG,
    )
    assert F.LOW_EXTRACTION_QUALITY in result.codes
    assert decide(result.findings).action is DecisionAction.HUMAN_REVIEW


@pytest.mark.parametrize(
    "printed",
    ["DIST. ANDINA DEL SUR", "Distribuidora Andina del Sur SA", "DISTRIBUIDORA ANDINA DEL SUR"],
)
def test_vendor_without_ruc_is_resolved_by_name(printed: str) -> None:
    vendor = resolve_vendor(_invoice(vendor_tax_id=None, vendor_name=printed), _ledger())
    assert vendor is not None
    assert vendor.tax_id == ANDINA


@pytest.mark.parametrize("printed", ["Comercializadora Nueva Era", "DISTRIBUIDORA ANDINA"])
def test_unrelated_or_truncated_names_are_not_matched(printed: str) -> None:
    # Without a RUC, a partial name is not enough evidence: better "unknown vendor"
    # (a human looks at it) than paying the wrong supplier.
    invoice = _invoice(vendor_tax_id=None, vendor_name=printed)
    assert resolve_vendor(invoice, _ledger()) is None
