"""LLM extraction with schema validation and self-correction.

Flow for one document:
1. Digital PDF -> text model on the text layer. Scan/photo -> vision model.
2. Parse JSON and validate against `ExtractedInvoice`.
3. On a parse/validation error, send the exact error back to the model and
   retry (up to `max_attempts`). The model fixes its own output.
4. If the text path still fails, fall back to the vision path on rendered pages.

Two kinds of failure are deliberately kept apart:
- *Content* failure (no valid JSON after all attempts) -> a business outcome:
  the invoice is unreadable and the supplier is asked for a better copy.
- *Infrastructure* failure (provider down, auth error) -> `LLMError` propagates;
  the invoice stays pending and the scheduler retries it later. An outage
  must never turn into "request more info" emails to suppliers.
"""

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import ValidationError

from opsagent.domain.schemas import ExtractedInvoice
from opsagent.extraction.documents import PreparedDocument, render_pdf_pages
from opsagent.extraction.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    USER_TEXT_TEMPLATE,
    USER_VISION_TEXT,
    VALIDATION_FEEDBACK,
)
from opsagent.infra.logging import get_logger
from opsagent.llm.base import (
    CompletionRequest,
    LLMClient,
    LLMResponse,
    Message,
    image_part,
    text_message,
)

log = get_logger(__name__)

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


@dataclass
class ExtractionAttempt:
    method: str
    model: str
    ok: bool
    error: str | None = None


@dataclass
class ExtractionResult:
    invoice: ExtractedInvoice | None
    method: str
    model: str
    prompt_version: str = PROMPT_VERSION
    raw: dict[str, object] | None = None
    attempts: list[ExtractionAttempt] = field(default_factory=list)
    calls: list[LLMResponse] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.invoice is not None

    @property
    def error(self) -> str | None:
        failed = [a.error for a in self.attempts if a.error]
        return failed[-1] if failed and not self.ok else None

    @property
    def cost_usd(self) -> Decimal:
        return sum((c.cost_usd for c in self.calls), Decimal(0))


def parse_json_object(content: str) -> dict[str, object]:
    text = _THINK_BLOCK.sub("", content).strip()
    text = _CODE_FENCE.sub("", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("The answer does not contain a JSON object.")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("The JSON root must be an object.")
    return data


def _format_validation_error(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors()[:10]:
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        lines.append(f"- {loc}: {err['msg']}")
    return "\n".join(lines)


class InvoiceExtractor:
    def __init__(
        self,
        llm: LLMClient,
        *,
        text_model: str,
        vision_model: str,
        max_attempts: int = 3,
        own_tax_id: str | None = None,
        text_model_extra: dict[str, object] | None = None,
    ) -> None:
        self.llm = llm
        self.text_model = text_model
        self.vision_model = vision_model
        self.max_attempts = max_attempts
        self.own_tax_id = own_tax_id
        self.text_model_extra = dict(text_model_extra or {})

    def extract(self, doc: PreparedDocument, content: bytes) -> ExtractionResult:
        if doc.text:
            result = self._run(
                [text_message("user", USER_TEXT_TEMPLATE.format(text=doc.text))],
                method="text",
                model=self.text_model,
                extra=self.text_model_extra,
            )
            if result.ok:
                return result
            log.warning("text_extraction_failed_falling_back_to_vision", error=result.error)
            images = render_pdf_pages(content)
            fallback = self._vision(images)
            fallback.attempts = result.attempts + fallback.attempts
            fallback.calls = result.calls + fallback.calls
            return fallback
        return self._vision(doc.images)

    def _vision(self, images: list[bytes]) -> ExtractionResult:
        parts: list[dict[str, object]] = [{"type": "text", "text": USER_VISION_TEXT}]
        parts += [image_part(img, "image/jpeg") for img in images]
        return self._run(
            [{"role": "user", "content": parts}], method="vision", model=self.vision_model
        )

    def _run(
        self,
        user_messages: list[Message],
        *,
        method: str,
        model: str,
        extra: dict[str, object] | None = None,
    ) -> ExtractionResult:
        messages: list[Message] = [text_message("system", SYSTEM_PROMPT), *user_messages]
        result = ExtractionResult(invoice=None, method=method, model=model)

        for _ in range(self.max_attempts):
            # LLMError (outage, auth) is intentionally not caught here: see module docstring.
            response = self.llm.complete(
                CompletionRequest(
                    model=model,
                    messages=messages,
                    json_mode=True,
                    temperature=0.0,
                    max_tokens=4096,
                    extra=dict(extra or {}),
                )
            )
            result.calls.append(response)
            try:
                raw = parse_json_object(response.content)
                invoice = ExtractedInvoice.model_validate(raw)
            except (ValueError, ValidationError) as exc:
                error = (
                    _format_validation_error(exc)
                    if isinstance(exc, ValidationError)
                    else f"- {exc}"
                )
                result.attempts.append(ExtractionAttempt(method, model, ok=False, error=error))
                messages = [
                    *messages,
                    text_message("assistant", response.content),
                    text_message("user", VALIDATION_FEEDBACK.format(errors=error)),
                ]
                continue

            result.attempts.append(ExtractionAttempt(method, model, ok=True))
            result.raw = raw
            result.invoice = self._sanitize(invoice)
            return result
        return result

    def _sanitize(self, invoice: ExtractedInvoice) -> ExtractedInvoice:
        """Guardrail: our own RUC is printed on every invoice as the *buyer*.

        If the model returns it as the vendor's RUC, it misread the document;
        drop it so the vendor is resolved by name and the gap is visible.
        """
        if self.own_tax_id and invoice.vendor_tax_id == self.own_tax_id:
            log.warning("extracted_buyer_tax_id_as_vendor")
            return invoice.model_copy(update={"vendor_tax_id": None})
        return invoice
