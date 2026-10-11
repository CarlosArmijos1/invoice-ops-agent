"""Reconciliation findings: the vocabulary shared by the rules, the policy, the UI and the evals."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Severity(StrEnum):
    INFO = "info"  # recorded for context, never blocks
    MISSING_INFO = "missing_info"  # the supplier must send something -> request_info
    RISK = "risk"  # a person must look at it -> human_review


class FindingCode(StrEnum):
    # Purchase order
    PO_MATCHED = "po_matched"
    PO_MISSING = "po_missing"
    PO_NOT_FOUND = "po_not_found"
    PO_INFERRED = "po_inferred"
    PO_VENDOR_MISMATCH = "po_vendor_mismatch"
    PO_OVERBILLED = "po_overbilled"
    # Amounts
    AMOUNT_WITHIN_TOLERANCE = "amount_within_tolerance"
    AMOUNT_MISMATCH = "amount_mismatch"
    OVER_AUTO_APPROVAL_LIMIT = "over_auto_approval_limit"
    ARITHMETIC_MISMATCH = "arithmetic_mismatch"
    # Identity
    VENDOR_UNKNOWN = "vendor_unknown"
    TAX_ID_MISSING = "tax_id_missing"
    TAX_ID_INVALID = "tax_id_invalid"
    DUPLICATE_INVOICE = "duplicate_invoice"
    # Payments
    PAID = "paid"
    UNPAID = "unpaid"
    PAYMENT_AMOUNT_MISMATCH = "payment_amount_mismatch"
    MULTIPLE_PAYMENTS = "multiple_payments"
    # Extraction
    LOW_EXTRACTION_QUALITY = "low_extraction_quality"
    EXTRACTION_FAILED = "extraction_failed"


SEVERITY: dict[FindingCode, Severity] = {
    FindingCode.PO_MATCHED: Severity.INFO,
    FindingCode.PO_MISSING: Severity.MISSING_INFO,
    FindingCode.PO_NOT_FOUND: Severity.MISSING_INFO,
    FindingCode.PO_INFERRED: Severity.RISK,
    FindingCode.PO_VENDOR_MISMATCH: Severity.RISK,
    FindingCode.PO_OVERBILLED: Severity.RISK,
    FindingCode.AMOUNT_WITHIN_TOLERANCE: Severity.INFO,
    FindingCode.AMOUNT_MISMATCH: Severity.RISK,
    FindingCode.OVER_AUTO_APPROVAL_LIMIT: Severity.RISK,
    FindingCode.ARITHMETIC_MISMATCH: Severity.RISK,
    FindingCode.VENDOR_UNKNOWN: Severity.RISK,
    FindingCode.TAX_ID_MISSING: Severity.MISSING_INFO,
    FindingCode.TAX_ID_INVALID: Severity.INFO,
    FindingCode.DUPLICATE_INVOICE: Severity.RISK,
    FindingCode.PAID: Severity.INFO,
    FindingCode.UNPAID: Severity.INFO,
    FindingCode.PAYMENT_AMOUNT_MISMATCH: Severity.RISK,
    FindingCode.MULTIPLE_PAYMENTS: Severity.RISK,
    FindingCode.LOW_EXTRACTION_QUALITY: Severity.RISK,
    FindingCode.EXTRACTION_FAILED: Severity.MISSING_INFO,
}


class Finding(BaseModel):
    code: FindingCode
    message: str = Field(description="Explicación en español, lista para mostrar al usuario")
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def severity(self) -> Severity:
        return SEVERITY[self.code]
