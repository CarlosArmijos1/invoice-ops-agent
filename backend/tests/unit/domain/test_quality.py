from datetime import date

from opsagent.domain.findings import FindingCode
from opsagent.domain.quality import assess_extraction
from opsagent.domain.schemas import ExtractedInvoice

TODAY = date(2026, 10, 11)


def _invoice(**overrides: object) -> ExtractedInvoice:
    base: dict[str, object] = {
        "vendor_name": "Distribuidora Andina del Sur S.A.",
        "vendor_tax_id": "1790016919001",
        "invoice_number": "001-001-000000123",
        "issue_date": "2026-09-01",
        "line_items": [
            {"description": "Papel", "quantity": 2, "unit_price": "500", "total": "1000"}
        ],
        "subtotal": "1000",
        "tax": "150",
        "total": "1150",
    }
    return ExtractedInvoice.model_validate(base | overrides)


def test_clean_invoice_scores_one_with_no_findings() -> None:
    report = assess_extraction(_invoice(), today=TODAY, source_text="TOTAL 1.150,00")
    assert report.score == 1.0
    assert report.findings == []


def test_total_that_does_not_add_up_is_an_arithmetic_finding() -> None:
    report = assess_extraction(_invoice(total="1160"), today=TODAY)
    assert [f.code for f in report.findings] == [FindingCode.ARITHMETIC_MISMATCH]


def test_total_absent_from_source_text_lowers_the_score() -> None:
    report = assess_extraction(_invoice(), today=TODAY, source_text="TOTAL 1,105.00")
    assert "total_not_in_source" in report.failed_checks
    assert report.score < 0.7


def test_implausible_tax_rate_and_future_date_are_penalised() -> None:
    report = assess_extraction(
        _invoice(tax="70", total="1070", issue_date="2027-01-01"), today=TODAY
    )
    assert set(report.failed_checks) == {"implausible_tax_rate", "implausible_date"}


def test_missing_and_invalid_tax_ids() -> None:
    missing = assess_extraction(_invoice(vendor_tax_id=None), today=TODAY)
    bad_checksum = assess_extraction(_invoice(vendor_tax_id="1790016918001"), today=TODAY)
    assert [f.code for f in missing.findings] == [FindingCode.TAX_ID_MISSING]
    assert [f.code for f in bad_checksum.findings] == [FindingCode.TAX_ID_INVALID]
    assert bad_checksum.score == 1.0  # the SRI has issued RUCs that fail modulo 11


def test_amount_variants_cover_both_conventions() -> None:
    for text in ("Total 1,150.00", "Total 1.150,00", "Total 1150.00"):
        assert assess_extraction(_invoice(), today=TODAY, source_text=text).score == 1.0
