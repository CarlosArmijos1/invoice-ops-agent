"""Validation of Ecuadorian taxpayer IDs (RUC).

A RUC has 13 digits. The third digit gives the taxpayer type and the check
algorithm:

- 0-5: natural person. First 10 digits are a cédula (modulo 10), suffix `001`+.
- 6:   public entity. Modulo 11 over 8 digits, check digit in position 9, suffix `0001`+.
- 9:   private company. Modulo 11 over 9 digits, check digit in position 10, suffix `001`+.

The SRI has issued some RUCs that do not satisfy the modulo-11 check, so a
failed checksum is reported as a *warning* by the quality checks, never as a
hard rejection. A wrong length or province, on the other hand, is almost
always an extraction error.
"""

from enum import StrEnum


class RucCheck(StrEnum):
    VALID = "valid"
    BAD_FORMAT = "bad_format"
    BAD_CHECKSUM = "bad_checksum"


def _province_ok(ruc: str) -> bool:
    province = int(ruc[:2])
    return 1 <= province <= 24 or province == 30


def _mod10_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(digits[:9]):
        product = int(ch) * (2 if i % 2 == 0 else 1)
        total += product - 9 if product > 9 else product
    check = (10 - total % 10) % 10
    return check == int(digits[9])


def _mod11_ok(digits: str, coefficients: tuple[int, ...]) -> bool:
    total = sum(int(d) * c for d, c in zip(digits, coefficients, strict=False))
    remainder = total % 11
    check = 0 if remainder == 0 else 11 - remainder
    return check == int(digits[len(coefficients)])


def check_ruc(value: str) -> RucCheck:
    ruc = "".join(ch for ch in value if ch.isdigit())
    if len(ruc) != 13 or not _province_ok(ruc):
        return RucCheck.BAD_FORMAT

    kind = int(ruc[2])
    if kind <= 5:
        if ruc[10:] == "000":
            return RucCheck.BAD_FORMAT
        ok = _mod10_ok(ruc)
    elif kind == 6:
        if ruc[9:] == "0000":
            return RucCheck.BAD_FORMAT
        ok = _mod11_ok(ruc, (3, 2, 7, 6, 5, 4, 3, 2))
    elif kind == 9:
        if ruc[10:] == "000":
            return RucCheck.BAD_FORMAT
        ok = _mod11_ok(ruc, (4, 3, 2, 7, 6, 5, 4, 3, 2))
    else:
        return RucCheck.BAD_FORMAT
    return RucCheck.VALID if ok else RucCheck.BAD_CHECKSUM


def make_ruc(prefix: str, kind: int) -> str:
    """Build a checksum-valid RUC from a numeric prefix. Used by the synthetic data generator.

    `prefix` must contain the province (2 digits) followed by enough digits to
    fill the body: 7 for natural persons and companies, 6 for public entities.
    """
    if kind <= 5:
        body = f"{prefix[:2]}{kind}{prefix[2:8]}"
        for check in range(10):
            if _mod10_ok(body + str(check)):
                return f"{body}{check}001"
    elif kind == 9:
        body = f"{prefix[:2]}9{prefix[2:8]}"
        for check in range(10):
            if _mod11_ok(body + str(check), (4, 3, 2, 7, 6, 5, 4, 3, 2)):
                return f"{body}{check}001"
    elif kind == 6:
        body = f"{prefix[:2]}6{prefix[2:7]}"
        for check in range(10):
            if _mod11_ok(body + str(check), (3, 2, 7, 6, 5, 4, 3, 2)):
                return f"{body}{check}0001"
    raise ValueError(f"cannot build a valid RUC for prefix={prefix!r} kind={kind}")
