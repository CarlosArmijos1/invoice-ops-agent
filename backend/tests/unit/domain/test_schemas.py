from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from opsagent.domain.schemas import ExtractedInvoice


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "vendor_name": "Distribuidora Andina S.A.",
        "vendor_tax_id": "1790016919001",
        "invoice_number": "001-001-000000123",
        "issue_date": "15/03/2026",
        "po_number": " oc-2026-0042 ",
        "line_items": [
            {"description": "Papel A4", "quantity": 10, "unit_price": "4,50", "total": "45,00"}
        ],
        "subtotal": "45,00",
        "tax": "6,75",
        "total": "$51,75",
    }
    return base | overrides


def test_parses_messy_llm_output_into_clean_types() -> None:
    invoice = ExtractedInvoice.model_validate(_payload())

    assert invoice.issue_date == date(2026, 3, 15)
    assert invoice.total == Decimal("51.75")
    assert invoice.line_items[0].unit_price == Decimal("4.50")
    assert invoice.po_number == "OC-2026-0042"
    assert invoice.normalized_number == "1-1-123"


def test_money_is_rounded_half_up_to_cents() -> None:
    invoice = ExtractedInvoice.model_validate(_payload(total=Decimal("51.745")))
    assert invoice.total == Decimal("51.75")


def test_three_decimals_in_a_string_are_read_as_thousands() -> None:
    # Documented ambiguity: "51.745" is 51745 under the LATAM convention.
    # The prompt asks for JSON numbers, so this only applies to stray strings.
    invoice = ExtractedInvoice.model_validate(_payload(total="51.745"))
    assert invoice.total == Decimal("51745.00")


def test_tax_id_keeps_only_digits() -> None:
    invoice = ExtractedInvoice.model_validate(_payload(vendor_tax_id="1790016919-001"))
    assert invoice.vendor_tax_id == "1790016919001"


@pytest.mark.parametrize("po", ["", "   ", None])
def test_blank_po_becomes_none(po: str | None) -> None:
    assert ExtractedInvoice.model_validate(_payload(po_number=po)).po_number is None


def test_missing_total_is_a_validation_error_with_field_location() -> None:
    payload = _payload()
    del payload["total"]
    with pytest.raises(ValidationError) as excinfo:
        ExtractedInvoice.model_validate(payload)
    assert excinfo.value.errors()[0]["loc"] == ("total",)


def test_lines_that_do_not_add_up_are_not_rejected() -> None:
    # Inconsistent arithmetic is a property of the document, reported by quality checks.
    invoice = ExtractedInvoice.model_validate(_payload(total="999.00"))
    assert invoice.total == Decimal("999.00")
