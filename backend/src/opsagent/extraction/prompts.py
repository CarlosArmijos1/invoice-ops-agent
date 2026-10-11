"""Extraction prompts. Versioned: the version is stored with every extraction."""

PROMPT_VERSION = "extract-v1"

SYSTEM_PROMPT = """\
You are the data-extraction step of an accounts-payable system for Ecuadorian \
supplier invoices (Spanish documents, amounts in USD).

Extract exactly what is PRINTED on the invoice. Never compute, fix or guess values:
if the printed total is not subtotal + tax, still return the printed numbers.

Return ONLY a JSON object with this shape:
{
  "vendor_name": "issuer company name as printed",
  "vendor_tax_id": "issuer RUC, 13 digits, or null if not printed",
  "invoice_number": "as printed, e.g. 001-001-000000123",
  "issue_date": "YYYY-MM-DD",
  "due_date": "YYYY-MM-DD or null",
  "currency": "USD",
  "po_number": "purchase order reference or null",
  "line_items": [
    {"description": "...", "quantity": 1, "unit_price": 0.0, "total": 0.0}
  ],
  "subtotal": 0.0,
  "tax": 0.0,
  "total": 0.0
}

Rules:
- The VENDOR is the issuer (emisor) at the top of the invoice. The buyer appears \
as "Cliente", "Facturar a" or "Razón Social / Nombres y Apellidos" and must never \
be used as vendor. The buyer's RUC is never the vendor_tax_id.
- Amounts are JSON numbers with a dot as decimal separator. Invoices may write \
1.234,56 (LATAM) or 1,234.56 (US); both mean 1234.56.
- Dates on these invoices are day-first (15/03/2026 is 15 March 2026) or written \
in Spanish ("2 de octubre de 2026").
- po_number labels include: "Orden de compra", "OC", "Referencia OC", "Pedido N°", \
"REF". Use null when there is none.
- tax is the IVA amount, not the rate. subtotal is the amount before IVA.
- Include every line item, across all pages.
"""

USER_TEXT_TEMPLATE = """\
Extract the invoice data from this text layer of a PDF invoice:

<invoice_text>
{text}
</invoice_text>"""

USER_VISION_TEXT = "Extract the invoice data from these page images (in order)."

VALIDATION_FEEDBACK = """\
Your previous answer could not be used:
{errors}

Return the corrected JSON object only, following the same schema and rules."""
