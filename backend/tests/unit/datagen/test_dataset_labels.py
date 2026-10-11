"""Sanity checks on the committed dataset: the answer key itself must be trustworthy."""

import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from opsagent.datagen.records import Catalog, GroundTruth
from opsagent.domain.findings import FindingCode
from opsagent.domain.schemas import DecisionAction
from opsagent.domain.tax_id import RucCheck, check_ruc

DATA = Path(__file__).resolve().parents[4] / "data" / "synthetic"


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.model_validate_json((DATA / "catalog.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def truths() -> list[GroundTruth]:
    raw = json.loads((DATA / "ground_truth.json").read_text(encoding="utf-8"))
    return [GroundTruth.model_validate(item) for item in raw]


def test_every_labelled_file_exists(truths: list[GroundTruth]) -> None:
    files = {p.name for p in (DATA / "invoices").iterdir()}
    assert {t.file for t in truths} == files


def test_all_three_actions_and_both_splits_are_represented(truths: list[GroundTruth]) -> None:
    actions = Counter(t.expected_action for t in truths)
    assert set(actions) == set(DecisionAction)
    assert {t.split for t in truths} == {"dev", "test"}


def test_printed_arithmetic_is_consistent_except_where_intended(truths: list[GroundTruth]) -> None:
    for t in truths:
        e = t.extraction
        consistent = e.subtotal + e.tax == e.total
        assert consistent is (t.scenario != "arithmetic_error"), t.file
        assert sum((li.total for li in e.line_items), Decimal(0)) == e.subtotal, t.file


def test_printed_tax_ids_are_valid_rucs(truths: list[GroundTruth]) -> None:
    for t in truths:
        if t.scenario == "missing_tax_id":
            assert t.extraction.vendor_tax_id is None
        else:
            assert t.extraction.vendor_tax_id is not None
            assert check_ruc(t.extraction.vendor_tax_id) is RucCheck.VALID, t.file


def test_clean_invoices_match_their_purchase_order_exactly(
    truths: list[GroundTruth], catalog: Catalog
) -> None:
    pos = {po.po_number: po for po in catalog.purchase_orders}
    for t in truths:
        if t.scenario.startswith("clean"):
            po = pos[t.extraction.po_number or ""]
            assert po.total == t.extraction.total, t.file
            assert po.vendor_tax_id == t.extraction.vendor_tax_id, t.file


def test_unknown_references_really_are_unknown(truths: list[GroundTruth], catalog: Catalog) -> None:
    pos = {po.po_number for po in catalog.purchase_orders}
    vendors = {v.tax_id for v in catalog.vendors}
    for t in truths:
        if t.scenario in ("unknown_po", "unknown_vendor"):
            assert t.extraction.po_number not in pos, t.file
        if t.scenario == "unknown_vendor":
            assert t.extraction.vendor_tax_id not in vendors, t.file


def test_duplicates_point_to_an_earlier_identical_invoice(truths: list[GroundTruth]) -> None:
    by_file = {t.file: t for t in truths}
    duplicates = [t for t in truths if t.scenario == "duplicate_resend"]
    assert duplicates
    for dup in duplicates:
        assert dup.expected_findings == [FindingCode.DUPLICATE_INVOICE]
        original = by_file[dup.duplicate_of or ""]
        assert original.file < dup.file
        assert original.extraction == dup.extraction
