"""Three-way reconciliation: invoice vs vendor master, purchase orders and payments.

Pure and deterministic: given the same invoice and the same books it always
produces the same findings. No LLM is involved in anything that moves money.
"""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher

from opsagent.domain.findings import Finding, FindingCode
from opsagent.domain.parsing import normalize_invoice_number, normalize_name
from opsagent.domain.ports import Ledger, PaymentRef, PurchaseOrderRef, VendorRef
from opsagent.domain.quality import QualityReport
from opsagent.domain.schemas import ExtractedInvoice

F = FindingCode
NAME_SIMILARITY_THRESHOLD = 0.88


@dataclass(frozen=True)
class PolicyConfig:
    amount_tolerance_abs: Decimal = Decimal("1.00")
    amount_tolerance_pct: Decimal = Decimal("0.005")
    auto_approval_limit: Decimal = Decimal("5000.00")
    min_quality_score: float = 0.7

    def tolerance_for(self, reference: Decimal) -> Decimal:
        """Smaller of an absolute and a relative tolerance: $1 on large POs, 0.5% on small ones."""
        return min(self.amount_tolerance_abs, (reference * self.amount_tolerance_pct).copy_abs())


@dataclass
class ReconciliationResult:
    vendor: VendorRef | None = None
    purchase_order: PurchaseOrderRef | None = None
    payments: list[PaymentRef] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def add(self, code: FindingCode, message: str, **details: object) -> None:
        self.findings.append(
            Finding(code=code, message=message, details={k: str(v) for k, v in details.items()})
        )

    @property
    def codes(self) -> set[FindingCode]:
        return {f.code for f in self.findings}


def _money(value: Decimal) -> str:
    return f"{value:,.2f} USD"


def resolve_vendor(invoice: ExtractedInvoice, ledger: Ledger) -> VendorRef | None:
    """RUC first (exact); the printed name only when there is no RUC."""
    if invoice.vendor_tax_id:
        return ledger.vendor_by_tax_id(invoice.vendor_tax_id)
    target = normalize_name(invoice.vendor_name)
    best: tuple[float, VendorRef | None] = (0.0, None)
    for vendor in ledger.all_vendors():
        for name in (vendor.name, *vendor.aliases):
            score = SequenceMatcher(None, target, normalize_name(name)).ratio()
            if score > best[0]:
                best = (score, vendor)
    return best[1] if best[0] >= NAME_SIMILARITY_THRESHOLD else None


def _payment_matches(payment: PaymentRef, invoice: ExtractedInvoice, normalized: str) -> bool:
    if payment.invoice_number:
        memo = normalize_invoice_number(payment.invoice_number)
        # Bank memos often carry only the sequential part ("4567" for 001-001-000004567).
        return memo == normalized or memo == normalized.rsplit("-", 1)[-1]
    return bool(invoice.po_number) and payment.po_number == invoice.po_number


def reconcile(
    invoice: ExtractedInvoice,
    *,
    invoice_id: uuid.UUID,
    ledger: Ledger,
    quality: QualityReport,
    config: PolicyConfig,
) -> ReconciliationResult:
    result = ReconciliationResult(findings=list(quality.findings))
    normalized = invoice.normalized_number

    if quality.score < config.min_quality_score:
        result.add(
            F.LOW_EXTRACTION_QUALITY,
            f"Calidad de extracción baja ({quality.score:.2f}); "
            f"controles fallidos: {', '.join(quality.failed_checks)}.",
            score=quality.score,
        )

    # 1. Vendor
    vendor = resolve_vendor(invoice, ledger)
    result.vendor = vendor
    if vendor is None:
        result.add(
            F.VENDOR_UNKNOWN,
            f"El proveedor '{invoice.vendor_name}' (RUC {invoice.vendor_tax_id or 'no impreso'}) "
            "no está registrado en el maestro de proveedores.",
            tax_id=invoice.vendor_tax_id,
        )

    # 2. Duplicates (same vendor + same invoice number, in any formatting)
    vendor_tax_id = vendor.tax_id if vendor else invoice.vendor_tax_id
    duplicates = ledger.prior_invoices(
        vendor_tax_id=vendor_tax_id, number_normalized=normalized, exclude=invoice_id
    )
    if duplicates:
        first = duplicates[0]
        result.add(
            F.DUPLICATE_INVOICE,
            f"La factura {invoice.invoice_number} ya fue recibida antes "
            f"(archivo {first.filename}).",
            duplicate_of=first.id,
        )

    # 3. Purchase order
    if invoice.po_number:
        po = ledger.purchase_order(invoice.po_number)
        if po is None:
            result.add(
                F.PO_NOT_FOUND,
                f"La orden de compra {invoice.po_number} no existe en el sistema.",
                po_number=invoice.po_number,
            )
        elif vendor is not None and po.vendor_id != vendor.id:
            result.purchase_order = po
            result.add(
                F.PO_VENDOR_MISMATCH,
                f"La orden {po.po_number} pertenece a otro proveedor.",
                po_number=po.po_number,
            )
        else:
            result.purchase_order = po
            result.add(F.PO_MATCHED, f"Coincide con la orden {po.po_number}.", po=po.po_number)
    elif vendor is not None:
        tolerance = config.tolerance_for(invoice.total)
        candidates = [
            po
            for po in ledger.open_purchase_orders(vendor.id)
            if abs(po.total - invoice.total) <= tolerance
        ]
        if len(candidates) == 1:
            result.purchase_order = candidates[0]
            result.add(
                F.PO_INFERRED,
                "La factura no indica orden de compra; probablemente corresponde a "
                f"{candidates[0].po_number} (mismo proveedor y monto). Requiere confirmación.",
                po_number=candidates[0].po_number,
            )
        else:
            result.add(
                F.PO_MISSING,
                "La factura no indica orden de compra y no se pudo asociar a ninguna.",
                candidates=len(candidates),
            )

    po = result.purchase_order
    if po is not None and F.PO_VENDOR_MISMATCH not in result.codes:
        difference = invoice.total - po.total
        tolerance = config.tolerance_for(po.total)
        if abs(difference) > tolerance:
            result.add(
                F.AMOUNT_MISMATCH,
                f"El total facturado ({_money(invoice.total)}) difiere de la orden "
                f"{po.po_number} ({_money(po.total)}) en {_money(difference)}.",
                difference=difference,
                tolerance=tolerance,
            )
        elif difference != 0:
            result.add(
                F.AMOUNT_WITHIN_TOLERANCE,
                f"Diferencia de {_money(difference)} dentro de la tolerancia "
                f"({_money(tolerance)}).",
                difference=difference,
            )
        already = ledger.invoiced_against_po(po.id, exclude=invoice_id)
        if already > 0 and already + invoice.total > po.total + tolerance:
            result.add(
                F.PO_OVERBILLED,
                f"Con esta factura, lo facturado contra {po.po_number} "
                f"({_money(already + invoice.total)}) supera la orden ({_money(po.total)}).",
                already_invoiced=already,
            )

    # 4. Payments
    if vendor is not None:
        matched = [
            p
            for p in ledger.payments_for_vendor(vendor.id)
            if _payment_matches(p, invoice, normalized)
        ]
        result.payments = matched
        paid = sum((p.amount for p in matched), Decimal(0))
        refs = ", ".join(p.reference for p in matched)
        if not matched:
            result.add(F.UNPAID, "No hay pagos registrados para esta factura.")
        elif len(matched) > 1:
            result.add(
                F.MULTIPLE_PAYMENTS,
                f"Hay {len(matched)} pagos para esta factura ({refs}) por {_money(paid)}; "
                "posible pago duplicado.",
                paid=paid,
            )
        elif abs(paid - invoice.total) > Decimal("0.01"):
            result.add(
                F.PAYMENT_AMOUNT_MISMATCH,
                f"El pago {refs} ({_money(paid)}) no coincide con el total "
                f"({_money(invoice.total)}).",
                paid=paid,
            )
        else:
            result.add(F.PAID, f"Pagada con {refs}.", paid=paid)

    # 5. Materiality
    if invoice.total > config.auto_approval_limit:
        result.add(
            F.OVER_AUTO_APPROVAL_LIMIT,
            f"El total ({_money(invoice.total)}) supera el límite de aprobación automática "
            f"({_money(config.auto_approval_limit)}).",
        )
    return result
