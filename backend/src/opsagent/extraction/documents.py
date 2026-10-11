"""Turn an incoming file into what the extractor needs: a text layer and/or page images.

Hybrid strategy: digital PDFs carry their text, which is cheaper, faster and
more exact than reading pixels. Only scans and photos go to the vision model.
"""

import io
from dataclasses import dataclass, field

import pypdfium2 as pdfium
from PIL import Image, ImageOps

MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_PAGES_FOR_VISION = 3  # Groq accepts up to 3 images per request
MAX_IMAGE_SIDE = 1600  # enough for invoice text, keeps the payload small
MIN_TEXT_CHARS = 80


class UnsupportedDocumentError(ValueError):
    pass


@dataclass
class PreparedDocument:
    media_type: str
    page_count: int
    text: str | None = None  # usable text layer, if any
    images: list[bytes] = field(default_factory=list)  # JPEG page images, rendered lazily

    @property
    def method(self) -> str:
        return "text" if self.text else "vision"


def sniff_media_type(content: bytes) -> str:
    if content.startswith(b"%PDF"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    raise UnsupportedDocumentError("Only PDF, PNG and JPEG invoices are supported")


def _to_jpeg(image: Image.Image) -> bytes:
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=85)
    return out.getvalue()


def _pdf_text(doc: pdfium.PdfDocument) -> str:
    pages = []
    for page in doc:
        textpage = page.get_textpage()
        pages.append(textpage.get_text_bounded())
    return "\n\n".join(f"--- página {i} ---\n{text.strip()}" for i, text in enumerate(pages, 1))


def _has_usable_text(text: str) -> bool:
    letters = sum(ch.isalnum() for ch in text)
    return letters >= MIN_TEXT_CHARS and any(ch.isdigit() for ch in text)


def render_pdf_pages(content: bytes) -> list[bytes]:
    doc = pdfium.PdfDocument(content)
    return [
        _to_jpeg(page.render(scale=150 / 72).to_pil()) for page in list(doc)[:MAX_PAGES_FOR_VISION]
    ]


def prepare_document(content: bytes) -> PreparedDocument:
    if len(content) > MAX_FILE_BYTES:
        raise UnsupportedDocumentError(f"File larger than {MAX_FILE_BYTES // 1024 // 1024} MB")
    media_type = sniff_media_type(content)

    if media_type == "application/pdf":
        try:
            doc = pdfium.PdfDocument(content)
        except pdfium.PdfiumError as exc:
            raise UnsupportedDocumentError(f"Unreadable PDF: {exc}") from exc
        text = _pdf_text(doc)
        if _has_usable_text(text):
            return PreparedDocument(media_type=media_type, page_count=len(doc), text=text)
        return PreparedDocument(
            media_type=media_type, page_count=len(doc), images=render_pdf_pages(content)
        )

    try:
        image = Image.open(io.BytesIO(content))
        image.load()
    except OSError as exc:
        raise UnsupportedDocumentError(f"Unreadable image: {exc}") from exc
    return PreparedDocument(media_type=media_type, page_count=1, images=[_to_jpeg(image)])
