"""Render invoice drafts as PDFs with four different layouts, then degrade some into "scans".

Every page carries a visible "synthetic document" notice: these files must
never be mistaken for real tax documents.
"""

import io
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pypdfium2 as pdfium
from PIL import Image, ImageEnhance, ImageFilter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from opsagent.datagen.catalog import BUYER
from opsagent.datagen.records import LineRecord, Render

DISCLAIMER = "DOCUMENTO SINTÉTICO GENERADO PARA PRUEBAS - SIN VALIDEZ TRIBUTARIA"
MONTHS = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


@dataclass
class InvoiceDraft:
    printed_vendor_name: str
    vendor_address: str
    vendor_email: str
    printed_tax_id: str | None
    printed_invoice_number: str
    issue_date: date
    due_date: date | None
    po_number: str | None
    lines: list[LineRecord]
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    number_style: str = "us"  # "us" -> 1,234.56 | "latam" -> 1.234,56
    date_style: str = "dmy"  # "dmy" | "iso" | "long"
    authorization: str = ""


def fmt_money(value: Decimal, style: str) -> str:
    text = f"{value:,.2f}"
    if style == "latam":
        text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    return text


def fmt_qty(value: Decimal) -> str:
    return f"{value:.0f}" if value == value.to_integral_value() else f"{value:.2f}"


def fmt_date(value: date, style: str) -> str:
    if style == "iso":
        return value.isoformat()
    if style == "long":
        return f"{value.day} de {MONTHS[value.month - 1]} de {value.year}"
    return value.strftime("%d/%m/%Y")


def _disclaimer(c: Canvas, width: float) -> None:
    c.saveState()
    c.setFillColor(colors.HexColor("#9a3412"))
    if width < 100 * mm:  # narrow receipts: two short lines
        c.setFont("Helvetica-Oblique", 5.5)
        head, _, tail = DISCLAIMER.partition(" - ")
        c.drawCentredString(width / 2, 9 * mm, head)
        c.drawCentredString(width / 2, 6 * mm, tail)
    else:
        c.setFont("Helvetica-Oblique", 7)
        c.drawCentredString(width / 2, 8 * mm, DISCLAIMER)
    c.restoreState()


# --------------------------------------------------------------------------- layouts


def _render_ride(c: Canvas, d: InvoiceDraft) -> None:
    """Layout inspired by the SRI electronic invoice printout (RIDE)."""
    w, h = A4
    m = 15 * mm
    c.setLineWidth(0.6)
    # Issuer box
    c.roundRect(m, h - 75 * mm, 88 * mm, 58 * mm, 3 * mm)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(m + 4 * mm, h - 28 * mm, d.printed_vendor_name[:42])
    c.setFont("Helvetica", 8)
    c.drawString(m + 4 * mm, h - 36 * mm, "Dirección Matriz:")
    c.drawString(m + 4 * mm, h - 41 * mm, d.vendor_address[:55])
    c.drawString(m + 4 * mm, h - 49 * mm, "OBLIGADO A LLEVAR CONTABILIDAD: SI")
    c.drawString(m + 4 * mm, h - 57 * mm, f"Correo: {d.vendor_email}")
    # Document box
    x2 = m + 92 * mm
    c.roundRect(x2, h - 75 * mm, w - x2 - m, 58 * mm, 3 * mm)
    c.setFont("Helvetica-Bold", 10)
    if d.printed_tax_id:
        c.drawString(x2 + 4 * mm, h - 25 * mm, f"R.U.C.: {d.printed_tax_id}")
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x2 + 4 * mm, h - 33 * mm, "FACTURA")
    c.setFont("Helvetica", 9)
    c.drawString(x2 + 4 * mm, h - 40 * mm, f"No. {d.printed_invoice_number}")
    c.setFont("Helvetica", 7)
    c.drawString(x2 + 4 * mm, h - 47 * mm, "NÚMERO DE AUTORIZACIÓN")
    c.drawString(x2 + 4 * mm, h - 51 * mm, d.authorization)
    c.drawString(x2 + 4 * mm, h - 58 * mm, "AMBIENTE: PRUEBAS      EMISIÓN: NORMAL")
    c.drawString(x2 + 4 * mm, h - 65 * mm, "CLAVE DE ACCESO")
    c.drawString(x2 + 4 * mm, h - 69 * mm, d.authorization[::-1])
    # Buyer box
    c.rect(m, h - 98 * mm, w - 2 * m, 19 * mm)
    c.setFont("Helvetica", 8)
    c.drawString(m + 3 * mm, h - 85 * mm, f"Razón Social / Nombres y Apellidos: {BUYER['name']}")
    c.drawString(m + 3 * mm, h - 90 * mm, f"Identificación: {BUYER['tax_id']}")
    c.drawString(m + 3 * mm, h - 95 * mm, f"Fecha Emisión: {fmt_date(d.issue_date, d.date_style)}")
    if d.po_number:
        c.drawString(m + 110 * mm, h - 95 * mm, f"Orden de compra: {d.po_number}")
    # Lines
    y = h - 106 * mm
    cols = [m, m + 22 * mm, m + 36 * mm, m + 120 * mm, m + 145 * mm]
    c.setFillColor(colors.HexColor("#e5e7eb"))
    c.rect(m, y - 2 * mm, w - 2 * m, 7 * mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 7.5)
    for x, label in zip(
        cols, ["Cod. Principal", "Cant.", "Descripción", "P. Unitario", "Precio Total"], strict=True
    ):
        c.drawString(x + 1.5 * mm, y, label)
    c.setFont("Helvetica", 8)
    for i, line in enumerate(d.lines):
        y -= 7 * mm
        c.drawString(cols[0] + 1.5 * mm, y, f"P{100 + i:04d}")
        c.drawString(cols[1] + 1.5 * mm, y, fmt_qty(line.quantity))
        c.drawString(cols[2] + 1.5 * mm, y, line.description[:48])
        c.drawRightString(cols[4] - 3 * mm, y, fmt_money(line.unit_price, d.number_style))
        c.drawRightString(w - m - 3 * mm, y, fmt_money(line.total, d.number_style))
        c.line(m, y - 2.5 * mm, w - m, y - 2.5 * mm)
    # Totals
    y -= 12 * mm
    rows = [
        ("SUBTOTAL 15%", d.subtotal),
        ("SUBTOTAL 0%", Decimal("0.00")),
        ("SUBTOTAL SIN IMPUESTOS", d.subtotal),
        ("DESCUENTO", Decimal("0.00")),
        ("IVA 15%", d.tax),
        ("VALOR TOTAL", d.total),
    ]
    for label, value in rows:
        bold = label == "VALOR TOTAL"
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 8.5)
        c.rect(m + 110 * mm, y - 2 * mm, 70 * mm, 6 * mm)
        c.drawString(m + 112 * mm, y, label)
        c.drawRightString(w - m - 3 * mm, y, fmt_money(value, d.number_style))
        y -= 6 * mm
    c.setFont("Helvetica", 7.5)
    c.drawString(m, y + 30 * mm, "Información Adicional")
    c.drawString(m, y + 25 * mm, "Forma de pago: Transferencia bancaria")


def _render_modern(c: Canvas, d: InvoiceDraft) -> None:
    w, h = A4
    m = 18 * mm
    c.setFillColor(colors.HexColor("#0f766e"))
    c.rect(0, h - 38 * mm, w, 38 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 26)
    c.drawString(m, h - 25 * mm, "Factura")
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(w - m, h - 17 * mm, d.printed_vendor_name)
    c.setFont("Helvetica", 8.5)
    c.drawRightString(w - m, h - 23 * mm, d.vendor_address)
    if d.printed_tax_id:
        c.drawRightString(w - m, h - 29 * mm, f"RUC {d.printed_tax_id}")
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(m, h - 50 * mm, "FACTURAR A")
    c.setFont("Helvetica", 9)
    c.drawString(m, h - 56 * mm, BUYER["name"])
    c.drawString(m, h - 61 * mm, BUYER["address"])
    meta = [
        ("Factura N.º", d.printed_invoice_number),
        ("Fecha", fmt_date(d.issue_date, d.date_style)),
    ]
    if d.due_date:
        meta.append(("Vence", fmt_date(d.due_date, d.date_style)))
    if d.po_number:
        meta.append(("Referencia OC", d.po_number))
    y = h - 50 * mm
    for label, value in meta:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(w - m - 75 * mm, y, label)
        c.setFont("Helvetica", 9)
        c.drawRightString(w - m, y, value)
        y -= 6 * mm
    y = h - 85 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(m, y, "Concepto")
    c.drawRightString(m + 115 * mm, y, "Cant.")
    c.drawRightString(m + 145 * mm, y, "Precio")
    c.drawRightString(w - m, y, "Importe")
    c.setStrokeColor(colors.HexColor("#0f766e"))
    c.setLineWidth(1.2)
    c.line(m, y - 3 * mm, w - m, y - 3 * mm)
    c.setFont("Helvetica", 9)
    for i, line in enumerate(d.lines):
        y -= 8 * mm
        if i % 2 == 0:
            c.setFillColor(colors.HexColor("#f0fdfa"))
            c.rect(m, y - 2.5 * mm, w - 2 * m, 8 * mm, fill=1, stroke=0)
            c.setFillColor(colors.black)
        c.drawString(m + 2 * mm, y, line.description)
        c.drawRightString(m + 115 * mm, y, fmt_qty(line.quantity))
        c.drawRightString(m + 145 * mm, y, fmt_money(line.unit_price, d.number_style))
        c.drawRightString(w - m - 2 * mm, y, fmt_money(line.total, d.number_style))
    y -= 16 * mm
    for label, amount, size in (
        ("Subtotal", d.subtotal, 10),
        ("IVA (15 %)", d.tax, 10),
        ("Total a pagar (USD)", d.total, 13),
    ):
        c.setFont("Helvetica-Bold" if size > 10 else "Helvetica", size)
        c.drawString(w - m - 75 * mm, y, label)
        c.drawRightString(w - m, y, f"$ {fmt_money(amount, d.number_style)}")
        y -= 8 * mm


def _render_ticket(c: Canvas, d: InvoiceDraft) -> None:
    _, h = c._pagesize
    x = 5 * mm
    y = h - 10 * mm
    c.setFont("Courier-Bold", 9)

    def line(text: str, bold: bool = False, step: float = 4.2) -> None:
        nonlocal y
        c.setFont("Courier-Bold" if bold else "Courier", 8)
        c.drawString(x, y, text)
        y -= step * mm

    line(d.printed_vendor_name.upper()[:34], bold=True)
    if d.printed_tax_id:
        line(f"RUC {d.printed_tax_id}")
    line(d.vendor_address[:34])
    line("-" * 34)
    line(f"FACT {d.printed_invoice_number}", bold=True)
    line(f"FECHA {fmt_date(d.issue_date, d.date_style)}")
    if d.po_number:
        line(f"REF: {d.po_number}")
    line("-" * 34)
    for item in d.lines:
        line(item.description[:34])
        qty = f"{fmt_qty(item.quantity)} x {fmt_money(item.unit_price, d.number_style)}"
        line(f"{qty:<20}{fmt_money(item.total, d.number_style):>14}")
    line("-" * 34)
    line(f"{'SUBTOTAL':<20}{fmt_money(d.subtotal, d.number_style):>14}")
    line(f"{'IVA 15%':<20}{fmt_money(d.tax, d.number_style):>14}")
    line(f"{'TOTAL USD':<20}{fmt_money(d.total, d.number_style):>14}", bold=True)
    line("")
    line("GRACIAS POR SU COMPRA")


def _render_classic(c: Canvas, d: InvoiceDraft) -> None:
    """Plain grid layout. Paginates long invoices; totals only on the last page."""
    w, h = A4
    m = 20 * mm
    per_page = 14
    pages = [d.lines[i : i + per_page] for i in range(0, len(d.lines), per_page)] or [[]]
    for page_no, lines in enumerate(pages, start=1):
        c.setFont("Times-Bold", 14)
        c.drawString(m, h - 22 * mm, d.printed_vendor_name)
        c.setFont("Times-Roman", 9)
        c.drawString(m, h - 28 * mm, d.vendor_address)
        if d.printed_tax_id:
            c.drawString(m, h - 33 * mm, f"R.U.C. {d.printed_tax_id}")
        c.setFont("Times-Bold", 12)
        c.drawRightString(w - m, h - 22 * mm, f"FACTURA N° {d.printed_invoice_number}")
        c.setFont("Times-Roman", 9)
        c.drawRightString(w - m, h - 28 * mm, f"Emisión: {fmt_date(d.issue_date, d.date_style)}")
        if d.po_number:
            c.drawRightString(w - m, h - 33 * mm, f"Pedido N° {d.po_number}")
        c.drawRightString(w - m, h - 38 * mm, f"Página {page_no} de {len(pages)}")
        c.drawString(m, h - 44 * mm, f"Cliente: {BUYER['name']} - RUC {BUYER['tax_id']}")
        y = h - 55 * mm
        widths = [100 * mm, 18 * mm, 26 * mm, 26 * mm]
        headers = ["Descripción", "Cantidad", "V. Unitario", "V. Total"]
        x = m
        c.setFont("Times-Bold", 9)
        for width, header in zip(widths, headers, strict=True):
            c.rect(x, y - 2 * mm, width, 7 * mm)
            c.drawString(x + 2 * mm, y, header)
            x += width
        c.setFont("Times-Roman", 9)
        for item in lines:
            y -= 7 * mm
            x = m
            values = [
                item.description,
                fmt_qty(item.quantity),
                fmt_money(item.unit_price, d.number_style),
                fmt_money(item.total, d.number_style),
            ]
            for i, (width, value) in enumerate(zip(widths, values, strict=True)):
                c.rect(x, y - 2 * mm, width, 7 * mm)
                if i == 0:
                    c.drawString(x + 2 * mm, y, value[:58])
                else:
                    c.drawRightString(x + width - 2 * mm, y, value)
                x += width
        if page_no == len(pages):
            y -= 14 * mm
            for label, amount in (
                ("Base imponible 15%", d.subtotal),
                ("IVA 15%", d.tax),
                ("TOTAL A PAGAR", d.total),
            ):
                c.setFont("Times-Bold" if label.startswith("TOTAL") else "Times-Roman", 10)
                c.drawString(w - m - 70 * mm, y, label)
                c.drawRightString(w - m, y, fmt_money(amount, d.number_style))
                y -= 6 * mm
        else:
            c.setFont("Times-Italic", 9)
            c.drawRightString(w - m, 25 * mm, "Continúa en la página siguiente...")
        _disclaimer(c, w)
        c.showPage()


LAYOUTS: dict[str, Callable[[Canvas, InvoiceDraft], None]] = {
    "ride": _render_ride,
    "moderna": _render_modern,
    "ticket": _render_ticket,
    "clasica": _render_classic,
}


def render_pdf(draft: InvoiceDraft, template: str) -> bytes:
    buffer = io.BytesIO()
    if template == "ticket":
        height = (95 + 9 * len(draft.lines)) * mm
        c = Canvas(buffer, pagesize=(80 * mm, height), invariant=True)
    else:
        c = Canvas(buffer, pagesize=A4, invariant=True)
    c.setTitle(f"Factura {draft.printed_invoice_number}")
    c.setAuthor("invoice-ops-agent synthetic data")
    LAYOUTS[template](c, draft)
    if template != "clasica":  # the classic layout manages its own pages
        _disclaimer(c, c._pagesize[0])
        c.showPage()
    c.save()
    return buffer.getvalue()


def page_count(pdf: bytes) -> int:
    return len(pdfium.PdfDocument(pdf))


# --------------------------------------------------------------------------- degradation


def _rasterize(pdf: bytes, dpi: int) -> list[Image.Image]:
    doc = pdfium.PdfDocument(pdf)
    return [page.render(scale=dpi / 72).to_pil().convert("RGB") for page in doc]


def _degrade(img: Image.Image, rng: random.Random, strength: float) -> Image.Image:
    """Simulate a phone photo / cheap scanner: tilt, blur, noise, washed-out contrast."""
    if rng.random() < 0.5:
        img = img.convert("L").convert("RGB")
    angle = rng.uniform(-3.0, 3.0) * strength
    img = img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    img = img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.3, 1.0) * strength))
    # Noise from the seeded RNG (not Image.effect_noise) keeps the dataset reproducible.
    noise = Image.frombytes("L", img.size, rng.randbytes(img.size[0] * img.size[1])).convert("RGB")
    img = Image.blend(img, noise, alpha=rng.uniform(0.04, 0.10) * strength)
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.75, 0.95))
    tint = Image.new("RGB", img.size, (255, 248, 230))
    return Image.blend(img, tint, alpha=rng.uniform(0.0, 0.12))


def render_file(
    draft: InvoiceDraft, template: str, render: Render, rng: random.Random
) -> tuple[bytes, str]:
    """Return the final file bytes and its extension."""
    pdf = render_pdf(draft, template)
    if render is Render.PDF_TEXT:
        return pdf, "pdf"

    pages = [_degrade(p, rng, strength=1.0) for p in _rasterize(pdf, dpi=rng.choice([130, 150]))]
    out = io.BytesIO()
    if render is Render.PDF_SCAN:
        # Constant metadata keeps the bytes reproducible (Pillow expects a struct_time).
        fixed = datetime(2026, 10, 1, tzinfo=UTC).timetuple()
        pages[0].save(
            out,
            format="PDF",
            save_all=True,
            append_images=pages[1:],
            resolution=150,
            creationDate=fixed,
            modDate=fixed,
        )
        return out.getvalue(), "pdf"
    if render is Render.JPG:
        pages[0].save(out, format="JPEG", quality=rng.randint(55, 75), optimize=True)
        return out.getvalue(), "jpg"
    pages[0].save(out, format="PNG", optimize=True)
    return out.getvalue(), "png"
