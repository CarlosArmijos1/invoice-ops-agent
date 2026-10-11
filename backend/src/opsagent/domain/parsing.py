"""Tolerant parsers for the messy values found on real invoices.

The LLM is asked for clean values, but invoices from LATAM suppliers mix
`1.234,56` and `1,234.56`, `dd/mm/yyyy` and ISO dates, and currency symbols.
These parsers run as Pydantic `BeforeValidator`s, so the schema accepts both
what the model should return and what it sometimes returns.
"""

import re
import unicodedata
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")

_CURRENCY_NOISE = re.compile(r"(?i)(usd|us\$|\$|u\.s\.d\.?|dólares|dolares|\s)")


def to_money(value: Decimal) -> Decimal:
    """Round to cents using commercial rounding (half up), as invoices do."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_amount(value: object) -> Decimal:
    """Parse an amount written in either decimal convention.

    Rules, in order:
    - numbers pass through (floats via `str` to avoid binary artefacts);
    - when both `.` and `,` appear, the right-most one is the decimal separator;
    - a single separator followed by exactly 1-2 digits is a decimal separator,
      otherwise it is a thousands separator (`1.234` -> 1234, `12,5` -> 12.5).
    """
    if isinstance(value, bool):
        raise ValueError("boolean is not an amount")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float):
        return Decimal(str(value))
    if not isinstance(value, str):
        raise ValueError(f"unsupported amount type: {type(value).__name__}")

    text = _CURRENCY_NOISE.sub("", value)
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    text = text.strip("-()")
    if not text:
        raise ValueError("empty amount")

    last_dot, last_comma = text.rfind("."), text.rfind(",")
    if last_dot >= 0 and last_comma >= 0:
        decimal_sep = "." if last_dot > last_comma else ","
        thousands_sep = "," if decimal_sep == "." else "."
        text = text.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif last_dot >= 0 or last_comma >= 0:
        sep = "." if last_dot >= 0 else ","
        head, _, tail = text.rpartition(sep)
        if text.count(sep) == 1 and 1 <= len(tail) <= 2:
            text = f"{head}.{tail}"
        else:
            text = text.replace(sep, "")

    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"not a valid amount: {value!r}") from exc
    return -amount if negative else amount


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%d/%m/%y")


def parse_date(value: object) -> date:
    """Parse ISO or day-first dates. Ambiguous `03/04/2026` is read as 3 April (LATAM)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"unsupported date type: {type(value).__name__}")
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date: {value!r}")


def normalize_invoice_number(value: str) -> str:
    """Canonical form used to detect duplicates across formatting variants.

    Ecuadorian invoice numbers look like `001-002-000004567` (establishment,
    emission point, sequential). `001002000004567`, `1-2-4567` and
    `001 002 4567` all normalise to `1-2-4567`.
    """
    groups = re.findall(r"\d+", value)
    if len(groups) == 1 and len(groups[0]) == 15:
        digits = groups[0]
        groups = [digits[:3], digits[3:6], digits[6:]]
    if not groups:
        return value.strip().upper()
    return "-".join(str(int(g)) for g in groups)


def normalize_name(value: str) -> str:
    """Lowercase, strip accents, punctuation and company suffixes for fuzzy vendor matching."""
    decomposed = unicodedata.normalize("NFKD", value.lower())
    text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\b(s\s?a|cia|ltda|c\s?a|s\s?a\s?s|inc|llc|corp)\b", " ", text)
    return " ".join(text.split())
