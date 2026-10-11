import pytest

from opsagent.domain.tax_id import RucCheck, check_ruc, make_ruc


@pytest.mark.parametrize(
    "ruc",
    [
        "1710034065001",  # natural person (cédula 1710034065)
        "1790016919001",  # private company
        "1760001550001",  # public entity
    ],
)
def test_known_valid_rucs(ruc: str) -> None:
    assert check_ruc(ruc) is RucCheck.VALID


@pytest.mark.parametrize(
    "ruc",
    ["179001691900", "17900169190011", "9990016919001", "1790016919000", "17A0016919001"],
)
def test_bad_format(ruc: str) -> None:
    assert check_ruc(ruc) is RucCheck.BAD_FORMAT


def test_bad_checksum_is_distinguished_from_bad_format() -> None:
    assert check_ruc("1790016918001") is RucCheck.BAD_CHECKSUM


def test_formatting_characters_are_ignored() -> None:
    assert check_ruc("1790016919-001") is RucCheck.VALID


@pytest.mark.parametrize("kind", [0, 1, 6, 9])
def test_make_ruc_generates_valid_ids(kind: int) -> None:
    for prefix in ("11234567", "17765432", "09123456", "01000001"):
        try:
            ruc = make_ruc(prefix, kind)
        except ValueError:
            continue  # some bodies have no valid modulo-11 check digit
        assert check_ruc(ruc) is RucCheck.VALID
