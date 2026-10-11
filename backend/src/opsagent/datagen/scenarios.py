"""Business scenarios for the synthetic dataset, each labelled with the expected outcome.

Labels come from the scenario definition, *not* from running the agent's policy,
so the evals measure the agent against an independent answer key.
"""

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from opsagent.datagen.catalog import UNKNOWN_VENDORS, VENDORS, VendorProfile
from opsagent.datagen.records import (
    Catalog,
    GroundTruth,
    LineRecord,
    PaymentRecord,
    PurchaseOrderRecord,
    Render,
    Split,
    VendorRecord,
)
from opsagent.datagen.render import InvoiceDraft
from opsagent.domain.findings import FindingCode
from opsagent.domain.parsing import to_money
from opsagent.domain.schemas import DecisionAction, ExtractedInvoice, LineItem
from opsagent.domain.tax_id import make_ruc

TAX_RATE = Decimal("0.15")
AUTO_APPROVAL_LIMIT = Decimal("5000.00")

F = FindingCode
A = DecisionAction


@dataclass
class PlannedInvoice:
    draft: InvoiceDraft
    template: str
    render: Render
    scenario: str
    action: DecisionAction
    findings: list[FindingCode]
    vendor_name_on_master: str
    duplicate_of: int | None = None
    notes: str = ""


@dataclass
class DatasetBuilder:
    seed: int = 42
    rng: random.Random = field(init=False)
    rucs: dict[str, str] = field(default_factory=dict)
    purchase_orders: list[PurchaseOrderRecord] = field(default_factory=list)
    payments: list[PaymentRecord] = field(default_factory=list)
    invoices: list[PlannedInvoice] = field(default_factory=list)
    _po_seq: int = 100
    _pay_seq: int = 5000
    _inv_seq: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    # ------------------------------------------------------------------ helpers

    def ruc(self, vendor: VendorProfile) -> str:
        if vendor.name not in self.rucs:
            prefix = vendor.ruc_prefix
            for bump in range(50):
                candidate = f"{prefix[:2]}{int(prefix[2:]) + bump:06d}"[:8]
                try:
                    self.rucs[vendor.name] = make_ruc(candidate, vendor.ruc_kind)
                    break
                except ValueError:
                    continue
        return self.rucs[vendor.name]

    def _date(self, start: date, min_days: int, max_days: int) -> date:
        return start + timedelta(days=self.rng.randint(min_days, max_days))

    def _lines(
        self, vendor: VendorProfile, n: int, qty_range: tuple[int, int] = (1, 12)
    ) -> list[LineRecord]:
        products = self.rng.sample(vendor.products, k=min(n, len(vendor.products)))
        while len(products) < n:  # long invoices repeat products with different quantities
            products.append(self.rng.choice(vendor.products))
        lines = []
        for description, price in products:
            qty = Decimal(self.rng.randint(*qty_range))
            lines.append(
                LineRecord(
                    description=description,
                    quantity=qty,
                    unit_price=price,
                    total=to_money(qty * price),
                )
            )
        return lines

    @staticmethod
    def _totals(lines: list[LineRecord]) -> tuple[Decimal, Decimal, Decimal]:
        subtotal = to_money(sum((line.total for line in lines), Decimal(0)))
        tax = to_money(subtotal * TAX_RATE)
        return subtotal, tax, subtotal + tax

    def new_po(
        self,
        vendor: VendorProfile,
        n_lines: int | None = None,
        qty_range: tuple[int, int] = (1, 12),
    ) -> PurchaseOrderRecord:
        self._po_seq += self.rng.randint(1, 4)
        lines = self._lines(vendor, n_lines or self.rng.randint(1, 4), qty_range)
        subtotal, tax, total = self._totals(lines)
        po = PurchaseOrderRecord(
            po_number=f"OC-2026-{self._po_seq:04d}",
            vendor_tax_id=self.ruc(vendor),
            issue_date=self._date(date(2026, 8, 1), 0, 50),
            subtotal=subtotal,
            tax=tax,
            total=total,
            lines=lines,
        )
        self.purchase_orders.append(po)
        return po

    def _invoice_number(self, vendor: VendorProfile) -> tuple[str, str]:
        """Return (canonical, printed) invoice number with realistic formatting variants."""
        seq = self._inv_seq.get(vendor.name, self.rng.randint(1200, 8800)) + self.rng.randint(1, 9)
        self._inv_seq[vendor.name] = seq
        point = self.rng.choice(["001", "002"])
        canonical = f"001-{point}-{seq:09d}"
        printed = self.rng.choices(
            [canonical, canonical.replace("-", ""), f"001-{point}-{seq}"], weights=[6, 2, 2]
        )[0]
        return canonical, printed

    def draft(
        self,
        vendor: VendorProfile,
        lines: list[LineRecord],
        po_number: str | None,
        issue_after: date,
        *,
        print_tax_id: bool = True,
        totals: tuple[Decimal, Decimal, Decimal] | None = None,
    ) -> InvoiceDraft:
        subtotal, tax, total = totals or self._totals(lines)
        issue = self._date(issue_after, 2, 20)
        _, printed_number = self._invoice_number(vendor)
        use_alias = vendor.printed_aliases and self.rng.random() < 0.3
        return InvoiceDraft(
            printed_vendor_name=(
                self.rng.choice(vendor.printed_aliases) if use_alias else vendor.name
            ),
            vendor_address=vendor.address,
            vendor_email=vendor.email,
            printed_tax_id=self.ruc(vendor) if print_tax_id else None,
            printed_invoice_number=printed_number,
            issue_date=issue,
            due_date=issue + timedelta(days=30) if self.rng.random() < 0.6 else None,
            po_number=po_number,
            lines=lines,
            subtotal=subtotal,
            tax=tax,
            total=total,
            number_style=self.rng.choice(["us", "latam"]),
            date_style=self.rng.choices(["dmy", "iso", "long"], weights=[6, 2, 2])[0],
            authorization="".join(self.rng.choice("0123456789") for _ in range(49)),
        )

    def pay(
        self,
        vendor: VendorProfile,
        draft: InvoiceDraft,
        amount: Decimal | None = None,
        *,
        memo: bool = True,
    ) -> None:
        self._pay_seq += self.rng.randint(1, 7)
        number = None
        if memo:
            digits = draft.printed_invoice_number.replace("-", "")
            number = self.rng.choice(
                [draft.printed_invoice_number, digits, f"{int(digits[6:])}", None]
            )
        self.payments.append(
            PaymentRecord(
                reference=f"TRF-{self._pay_seq:06d}",
                vendor_tax_id=self.ruc(vendor),
                amount=amount if amount is not None else draft.total,
                paid_on=self._date(draft.issue_date, 3, 25),
                invoice_number=number,
                po_number=draft.po_number if number is None else None,
            )
        )

    def add(self, planned: PlannedInvoice) -> int:
        self.invoices.append(planned)
        return len(self.invoices) - 1

    def _layout(self, n_lines: int) -> tuple[str, Render]:
        template = (
            "clasica"
            if n_lines > 10
            else self.rng.choices(["ride", "moderna", "ticket", "clasica"], weights=[4, 3, 2, 2])[0]
        )
        render = self.rng.choices(
            [Render.PDF_TEXT, Render.PDF_SCAN, Render.JPG, Render.PNG], weights=[55, 15, 20, 10]
        )[0]
        if n_lines > 14 and render in (Render.JPG, Render.PNG):
            render = Render.PDF_SCAN  # a multi-page invoice arrives as a multi-page scan
        return template, render

    def plan(
        self,
        vendor: VendorProfile,
        draft: InvoiceDraft,
        scenario: str,
        action: DecisionAction,
        findings: list[FindingCode],
        notes: str = "",
    ) -> int:
        template, render = self._layout(len(draft.lines))
        return self.add(
            PlannedInvoice(
                draft=draft,
                template=template,
                render=render,
                scenario=scenario,
                action=action,
                findings=findings,
                vendor_name_on_master=vendor.name,
                notes=notes,
            )
        )

    # ------------------------------------------------------------------ scenarios

    def clean(self, *, paid: bool, n_lines: int | None = None) -> int:
        vendor = self.rng.choice(VENDORS)
        po = self.new_po(vendor, n_lines=n_lines, qty_range=(1, 3) if n_lines else (1, 12))
        if po.total > AUTO_APPROVAL_LIMIT:  # keep "clean" strictly under the limit
            self.purchase_orders.pop()
            return self.clean(paid=paid, n_lines=n_lines)
        draft = self.draft(vendor, po.lines, po.po_number, po.issue_date)
        if paid:
            self.pay(vendor, draft, memo=self.rng.random() < 0.8)
        scenario = "clean_paid" if paid else "clean_unpaid"
        return self.plan(vendor, draft, scenario, A.AUTO_APPROVE, [F.PO_MATCHED])

    def within_tolerance(self) -> int:
        vendor = self.rng.choice(VENDORS)
        po = self.new_po(vendor)
        lines = [line.model_copy() for line in po.lines]
        bump = Decimal(self.rng.choice(["0.01", "0.02", "0.03"]))
        lines[0] = lines[0].model_copy(
            update={"quantity": Decimal(1), "unit_price": lines[0].total + bump}
        )
        lines[0].total = to_money(lines[0].unit_price)
        draft = self.draft(vendor, lines, po.po_number, po.issue_date)
        return self.plan(
            vendor,
            draft,
            "within_tolerance",
            A.AUTO_APPROVE,
            [F.AMOUNT_WITHIN_TOLERANCE],
            notes="Diferencia de centavos por redondeo del proveedor.",
        )

    def amount_mismatch(self) -> int:
        vendor = self.rng.choice(VENDORS)
        po = self.new_po(vendor)
        lines = [line.model_copy() for line in po.lines]
        first = lines[0]
        extra = Decimal(self.rng.randint(1, 3))
        lines[0] = first.model_copy(
            update={
                "quantity": first.quantity + extra,
                "total": to_money((first.quantity + extra) * first.unit_price),
            }
        )
        draft = self.draft(vendor, lines, po.po_number, po.issue_date)
        return self.plan(
            vendor,
            draft,
            "amount_mismatch",
            A.HUMAN_REVIEW,
            [F.AMOUNT_MISMATCH],
            notes=f"Factura cobra {extra} unidades más que la OC.",
        )

    def duplicate_of(self, original: int) -> int:
        source = self.invoices[original]
        template, render = self._layout(len(source.draft.lines))
        while render == source.render:
            render = self.rng.choice(list(Render))
        return self.add(
            PlannedInvoice(
                draft=source.draft,
                template=template,
                render=render,
                scenario="duplicate_resend",
                action=A.HUMAN_REVIEW,
                findings=[F.DUPLICATE_INVOICE],
                vendor_name_on_master=source.vendor_name_on_master,
                duplicate_of=original,
                notes="El proveedor reenvió la misma factura en otro formato.",
            )
        )

    def missing_po(self, *, inferable: bool) -> int:
        vendor = self.rng.choice(VENDORS)
        if inferable:
            po = self.new_po(vendor)
            draft = self.draft(vendor, po.lines, None, po.issue_date)
            return self.plan(
                vendor,
                draft,
                "missing_po_inferable",
                A.HUMAN_REVIEW,
                [F.PO_INFERRED],
                notes=f"Sin OC impresa; coincide con {po.po_number} por proveedor y monto.",
            )
        lines = self._lines(vendor, self.rng.randint(1, 3))
        draft = self.draft(vendor, lines, None, date(2026, 8, 15))
        return self.plan(vendor, draft, "missing_po", A.REQUEST_INFO, [F.PO_MISSING])

    def unknown_po(self) -> int:
        vendor = self.rng.choice(VENDORS)
        lines = self._lines(vendor, self.rng.randint(1, 3))
        draft = self.draft(
            vendor, lines, f"OC-2026-{self.rng.randint(9000, 9999)}", date(2026, 8, 20)
        )
        return self.plan(vendor, draft, "unknown_po", A.REQUEST_INFO, [F.PO_NOT_FOUND])

    def vendor_mismatch(self) -> int:
        vendor, other = self.rng.sample(VENDORS, k=2)
        other_po = self.new_po(other)
        lines = self._lines(vendor, self.rng.randint(1, 3))
        draft = self.draft(vendor, lines, other_po.po_number, other_po.issue_date)
        return self.plan(
            vendor,
            draft,
            "vendor_mismatch",
            A.HUMAN_REVIEW,
            [F.PO_VENDOR_MISMATCH],
            notes=f"La OC {other_po.po_number} pertenece a {other.name}.",
        )

    def over_limit(self) -> int:
        vendor = self.rng.choice([v for v in VENDORS if v.products[0][1] > 100] or VENDORS)
        po = self.new_po(vendor, n_lines=2, qty_range=(8, 14))
        if po.total <= AUTO_APPROVAL_LIMIT:
            self.purchase_orders.pop()
            return self.over_limit()
        draft = self.draft(vendor, po.lines, po.po_number, po.issue_date)
        return self.plan(vendor, draft, "over_limit", A.HUMAN_REVIEW, [F.OVER_AUTO_APPROVAL_LIMIT])

    def arithmetic_error(self) -> int:
        vendor = self.rng.choice(VENDORS)
        po = self.new_po(vendor)
        subtotal, tax, total = self._totals(po.lines)
        wrong_total = total + Decimal(self.rng.choice(["10.00", "100.00", "0.90"]))
        draft = self.draft(
            vendor, po.lines, po.po_number, po.issue_date, totals=(subtotal, tax, wrong_total)
        )
        return self.plan(
            vendor,
            draft,
            "arithmetic_error",
            A.HUMAN_REVIEW,
            [F.ARITHMETIC_MISMATCH],
            notes="El total impreso no es subtotal + IVA.",
        )

    def unknown_vendor(self) -> int:
        vendor = self.rng.choice(UNKNOWN_VENDORS)
        lines = self._lines(vendor, self.rng.randint(1, 2))
        draft = self.draft(
            vendor, lines, f"OC-2026-{self.rng.randint(9000, 9999)}", date(2026, 8, 10)
        )
        return self.plan(
            vendor,
            draft,
            "unknown_vendor",
            A.HUMAN_REVIEW,
            [F.VENDOR_UNKNOWN],
            notes="Proveedor no registrado en el maestro.",
        )

    def missing_tax_id(self) -> int:
        vendor = self.rng.choice(VENDORS)
        po = self.new_po(vendor)
        draft = self.draft(vendor, po.lines, po.po_number, po.issue_date, print_tax_id=False)
        draft.printed_vendor_name = vendor.name  # identifiable by name only
        return self.plan(vendor, draft, "missing_tax_id", A.REQUEST_INFO, [F.TAX_ID_MISSING])

    def payment_mismatch(self, *, double: bool) -> int:
        vendor = self.rng.choice(VENDORS)
        po = self.new_po(vendor)
        draft = self.draft(vendor, po.lines, po.po_number, po.issue_date)
        if double:
            self.pay(vendor, draft)
            self.pay(vendor, draft)
            return self.plan(
                vendor,
                draft,
                "double_payment",
                A.HUMAN_REVIEW,
                [F.MULTIPLE_PAYMENTS],
                notes="La factura se pagó dos veces.",
            )
        short = to_money(draft.total * Decimal(self.rng.choice(["0.9", "0.5", "0.97"])))
        self.pay(vendor, draft, amount=short)
        return self.plan(
            vendor,
            draft,
            "payment_mismatch",
            A.HUMAN_REVIEW,
            [F.PAYMENT_AMOUNT_MISMATCH],
            notes="El pago registrado no coincide con el total facturado.",
        )

    def background_noise(self) -> None:
        """Open POs with no invoice yet and payments with no invoice: input for the daily report."""
        for _ in range(6):
            self.new_po(self.rng.choice(VENDORS))
        for _ in range(3):
            vendor = self.rng.choice(VENDORS)
            self._pay_seq += 3
            self.payments.append(
                PaymentRecord(
                    reference=f"TRF-{self._pay_seq:06d}",
                    vendor_tax_id=self.ruc(vendor),
                    amount=to_money(Decimal(self.rng.randint(5000, 90000)) / 100),
                    paid_on=self._date(date(2026, 9, 1), 0, 25),
                    invoice_number=f"001-001-{self.rng.randint(100, 999):09d}",
                )
            )

    # ------------------------------------------------------------------ assembly

    def build(self) -> None:
        originals = []
        for i in range(26):
            idx = self.clean(paid=i % 2 == 0, n_lines=self.rng.randint(15, 18) if i < 3 else None)
            originals.append(idx)
        for _ in range(3):
            self.within_tolerance()
        for _ in range(5):
            self.amount_mismatch()
        for _ in range(3):
            self.missing_po(inferable=False)
        for _ in range(2):
            self.missing_po(inferable=True)
        for _ in range(3):
            self.unknown_po()
        for _ in range(2):
            self.vendor_mismatch()
        for _ in range(3):
            self.over_limit()
        for _ in range(2):
            self.arithmetic_error()
        for _ in range(2):
            self.unknown_vendor()
        for _ in range(2):
            self.missing_tax_id()
        for _ in range(2):
            self.payment_mismatch(double=False)
        self.payment_mismatch(double=True)
        for original in self.rng.sample(originals[3:], k=4):
            self.duplicate_of(original)
        self.background_noise()

    def catalog(self) -> Catalog:
        vendors = [
            VendorRecord(
                name=v.name, tax_id=self.ruc(v), email=v.email, aliases=list(v.printed_aliases)
            )
            for v in VENDORS
        ]
        return Catalog(
            vendors=vendors, purchase_orders=self.purchase_orders, payments=self.payments
        )

    def ground_truth(self, file_names: list[str]) -> list[GroundTruth]:
        truths = []
        for i, (planned, name) in enumerate(zip(self.invoices, file_names, strict=True)):
            d = planned.draft
            extraction = ExtractedInvoice(
                vendor_name=d.printed_vendor_name,
                vendor_tax_id=d.printed_tax_id,
                invoice_number=d.printed_invoice_number,
                issue_date=d.issue_date,
                due_date=d.due_date,
                currency="USD",
                po_number=d.po_number,
                line_items=[
                    LineItem(
                        description=line.description,
                        quantity=line.quantity,
                        unit_price=line.unit_price,
                        total=line.total,
                    )
                    for line in d.lines
                ],
                subtotal=d.subtotal,
                tax=d.tax,
                total=d.total,
            )
            truths.append(
                GroundTruth(
                    file=name,
                    scenario=planned.scenario,
                    split=Split.DEV if i % 3 == 0 else Split.TEST,
                    template=planned.template,
                    render=planned.render,
                    extraction=extraction,
                    expected_action=planned.action,
                    expected_findings=planned.findings,
                    duplicate_of=(
                        file_names[planned.duplicate_of]
                        if planned.duplicate_of is not None
                        else None
                    ),
                    notes=planned.notes,
                )
            )
        return truths
