"""Extraction quality from verifiable signals, not from the model's self-reported confidence.

LLMs are poorly calibrated about their own certainty. Instead, the score is
built from checks we can actually verify: does the arithmetic hold, is the RUC
well formed, is the date plausible, and (for digital PDFs) does the extracted
total literally appear in the source text?
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from opsagent.domain.findings import Finding, FindingCode
from opsagent.domain.schemas import ExtractedInvoice
from opsagent.domain.tax_id import RucCheck, check_ruc

ARITHMETIC_TOLERANCE = Decimal("0.02")
PLAUSIBLE_TAX_RATES = (Decimal("0"), Decimal("0.05"), Decimal("0.12"), Decimal("0.15"))

PENALTIES = {
    "total_not_in_source": 0.35,
    "implausible_tax_rate": 0.2,
    "implausible_date": 0.3,
    "tax_id_bad_format": 0.2,
    "no_line_items": 0.1,
}


@dataclass
class QualityReport:
    score: float
    findings: list[Finding] = field(default_factory=list)
    failed_checks: list[str] = field(default_factory=list)


def _money_variants(value: Decimal) -> set[str]:
    us = f"{value:,.2f}"
    latam = us.replace(",", "_").replace(".", ",").replace("_", ".")
    return {us, latam, f"{value:.2f}", f"{value:.2f}".replace(".", ",")}


def assess_extraction(
    invoice: ExtractedInvoice,
    *,
    today: date,
    source_text: str | None = None,
) -> QualityReport:
    findings: list[Finding] = []
    failed: list[str] = []

    if invoice.line_items:
        lines_sum = sum((li.total for li in invoice.line_items), Decimal(0))
        if abs(lines_sum - invoice.subtotal) > ARITHMETIC_TOLERANCE:
            findings.append(
                Finding(
                    code=FindingCode.ARITHMETIC_MISMATCH,
                    message=(
                        f"La suma de las líneas ({lines_sum:.2f}) no coincide con el "
                        f"subtotal impreso ({invoice.subtotal:.2f})."
                    ),
                    details={"lines_sum": str(lines_sum), "subtotal": str(invoice.subtotal)},
                )
            )
    else:
        failed.append("no_line_items")

    expected_total = invoice.subtotal + invoice.tax
    if abs(expected_total - invoice.total) > ARITHMETIC_TOLERANCE:
        findings.append(
            Finding(
                code=FindingCode.ARITHMETIC_MISMATCH,
                message=(
                    f"Subtotal + IVA = {expected_total:.2f}, pero el total impreso es "
                    f"{invoice.total:.2f}."
                ),
                details={"expected_total": str(expected_total), "total": str(invoice.total)},
            )
        )

    if invoice.subtotal > 0:
        rate = invoice.tax / invoice.subtotal
        if not any(abs(rate - r) <= Decimal("0.005") for r in PLAUSIBLE_TAX_RATES):
            failed.append("implausible_tax_rate")

    if not (date(2020, 1, 1) <= invoice.issue_date <= today):
        failed.append("implausible_date")

    if invoice.vendor_tax_id is None:
        findings.append(
            Finding(
                code=FindingCode.TAX_ID_MISSING,
                message="La factura no muestra el RUC del proveedor.",
            )
        )
    else:
        ruc = check_ruc(invoice.vendor_tax_id)
        if ruc is not RucCheck.VALID:
            findings.append(
                Finding(
                    code=FindingCode.TAX_ID_INVALID,
                    message=f"El RUC {invoice.vendor_tax_id} no pasa la validación ({ruc}).",
                    details={"check": ruc.value},
                )
            )
        if ruc is RucCheck.BAD_FORMAT:
            failed.append("tax_id_bad_format")

    if source_text is not None:
        compact = source_text.replace(" ", "")
        if not any(v.replace(" ", "") in compact for v in _money_variants(invoice.total)):
            failed.append("total_not_in_source")

    score = max(0.0, 1.0 - sum(PENALTIES[name] for name in failed))
    return QualityReport(score=round(score, 2), findings=findings, failed_checks=failed)
