import json

import pytest

from opsagent.extraction.documents import PreparedDocument
from opsagent.extraction.extractor import InvoiceExtractor, parse_json_object
from opsagent.llm.errors import LLMServerError
from opsagent.llm.fake import FakeLLMClient

VALID = {
    "vendor_name": "Distribuidora Andina del Sur S.A.",
    "vendor_tax_id": "1790016919001",
    "invoice_number": "001-001-000000123",
    "issue_date": "2026-09-01",
    "po_number": "OC-2026-0101",
    "line_items": [{"description": "Papel", "quantity": 2, "unit_price": 5.0, "total": 10.0}],
    "subtotal": 10.0,
    "tax": 1.5,
    "total": 11.5,
}
TEXT_DOC = PreparedDocument(media_type="application/pdf", page_count=1, text="FACTURA ...")
IMAGE_DOC = PreparedDocument(media_type="image/jpeg", page_count=1, images=[b"\xff\xd8\xffjpeg"])


def _extractor(
    llm: FakeLLMClient, *, max_attempts: int = 3, own_tax_id: str | None = None
) -> InvoiceExtractor:
    return InvoiceExtractor(
        llm,
        text_model="text-m",
        vision_model="vision-m",
        max_attempts=max_attempts,
        own_tax_id=own_tax_id,
    )


def test_text_document_uses_text_model_and_succeeds_first_try() -> None:
    llm = FakeLLMClient([json.dumps(VALID)])
    result = _extractor(llm).extract(TEXT_DOC, b"")

    assert result.ok
    assert result.method == "text"
    assert llm.requests[0].model == "text-m"
    assert llm.requests[0].json_mode is True


def test_invalid_output_is_fed_back_and_corrected() -> None:
    broken = dict(VALID)
    del broken["total"]
    llm = FakeLLMClient([json.dumps(broken), json.dumps(VALID)])

    result = _extractor(llm).extract(IMAGE_DOC, b"")

    assert result.ok
    assert [a.ok for a in result.attempts] == [False, True]
    feedback = llm.requests[1].messages[-1]["content"]
    assert "total" in feedback
    assert "Field required" in feedback


def test_gives_up_after_max_attempts_without_raising() -> None:
    llm = FakeLLMClient(["not json"] * 3)
    result = _extractor(llm, max_attempts=3).extract(IMAGE_DOC, b"")

    assert not result.ok
    assert result.error is not None
    assert len(llm.requests) == 3


def test_text_failure_falls_back_to_vision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "opsagent.extraction.extractor.render_pdf_pages", lambda content: [b"\xff\xd8\xffpage"]
    )
    llm = FakeLLMClient(["nope", "nope", json.dumps(VALID)])

    result = _extractor(llm, max_attempts=2).extract(TEXT_DOC, b"%PDF")

    assert result.ok
    assert result.method == "vision"
    assert [r.model for r in llm.requests] == ["text-m", "text-m", "vision-m"]
    assert len(result.calls) == 3  # the failed attempts still count towards cost


def test_provider_outage_propagates_instead_of_becoming_a_business_outcome() -> None:
    llm = FakeLLMClient([LLMServerError("503")])
    with pytest.raises(LLMServerError):
        _extractor(llm).extract(IMAGE_DOC, b"")


def test_buyer_tax_id_returned_as_vendor_is_discarded() -> None:
    payload = VALID | {"vendor_tax_id": "1191734929001"}
    llm = FakeLLMClient([json.dumps(payload)])
    result = _extractor(llm, own_tax_id="1191734929001").extract(TEXT_DOC, b"")
    assert result.invoice is not None
    assert result.invoice.vendor_tax_id is None


@pytest.mark.parametrize(
    "content",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        '<think>reasoning about {braces}</think>\n{"a": 1}',
        'Here you go: {"a": 1} hope it helps',
    ],
)
def test_parse_json_object_tolerates_wrappers(content: str) -> None:
    assert parse_json_object(content) == {"a": 1}
