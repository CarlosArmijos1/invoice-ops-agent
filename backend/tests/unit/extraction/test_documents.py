import json
from pathlib import Path

import pytest

from opsagent.extraction.documents import UnsupportedDocumentError, prepare_document

DATA = Path(__file__).resolve().parents[4] / "data" / "synthetic"
TRUTHS = json.loads((DATA / "ground_truth.json").read_text(encoding="utf-8"))


def _first(render: str) -> bytes:
    name: str = next(t["file"] for t in TRUTHS if t["render"] == render)
    content: bytes = (DATA / "invoices" / name).read_bytes()
    return content


def test_digital_pdf_uses_its_text_layer() -> None:
    doc = prepare_document(_first("pdf_text"))
    assert doc.method == "text"
    assert doc.text is not None
    assert "FACT" in doc.text.upper()
    assert doc.images == []


@pytest.mark.parametrize("render", ["pdf_scan", "jpg", "png"])
def test_scans_and_photos_go_to_vision_as_jpeg(render: str) -> None:
    doc = prepare_document(_first(render))
    assert doc.method == "vision"
    assert 1 <= len(doc.images) <= 3
    assert all(img.startswith(b"\xff\xd8\xff") for img in doc.images)


def test_unknown_formats_are_rejected() -> None:
    with pytest.raises(UnsupportedDocumentError):
        prepare_document(b"PK\x03\x04 a zip file")
