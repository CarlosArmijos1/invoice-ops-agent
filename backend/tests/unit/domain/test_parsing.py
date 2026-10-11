from datetime import date
from decimal import Decimal

import pytest

from opsagent.domain.parsing import (
    normalize_invoice_number,
    normalize_name,
    parse_amount,
    parse_date,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("$ 1.234.567,89", "1234567.89"),
        ("USD 99,9", "99.9"),
        ("1.234", "1234"),
        ("1,234,567", "1234567"),
        ("12,50", "12.50"),
        ("(15.00)", "-15.00"),
        ("-3,5", "-3.5"),
        (1500, "1500"),
        (0.1, "0.1"),
    ],
)
def test_parse_amount_handles_both_decimal_conventions(raw: object, expected: str) -> None:
    assert parse_amount(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["", "abc", True, None])
def test_parse_amount_rejects_garbage(raw: object) -> None:
    with pytest.raises(ValueError, match=r"."):
        parse_amount(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-03-04", date(2026, 3, 4)),
        ("04/03/2026", date(2026, 3, 4)),  # day first, LATAM convention
        ("04-03-2026", date(2026, 3, 4)),
        ("4.3.2026", date(2026, 3, 4)),
    ],
)
def test_parse_date_is_day_first(raw: str, expected: date) -> None:
    assert parse_date(raw) == expected


def test_parse_date_rejects_unknown_format() -> None:
    with pytest.raises(ValueError, match="unrecognised date"):
        parse_date("March fourth")


@pytest.mark.parametrize(
    "raw", ["001-002-000004567", "001002000004567", "1-2-4567", "001 002 4567", "Nº 001-002-4567"]
)
def test_invoice_number_variants_normalise_to_same_key(raw: str) -> None:
    assert normalize_invoice_number(raw) == "1-2-4567"


def test_normalize_name_ignores_case_punctuation_and_company_suffix() -> None:
    assert normalize_name("Distribuidora Andina S.A.") == normalize_name("DISTRIBUIDORA ANDINA SA")
    assert normalize_name("Ferretería López Cía. Ltda.") == "ferreteria lopez"
