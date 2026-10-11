"""Read-only lookup tools over the books.

Defined once, with Pydantic argument models, and exposed twice:
- to the investigator node as LLM function calls (`openai_tools()`), and
- to external agents through the MCP server.
They can only read: no tool here can approve, pay or modify anything.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from opsagent.domain.parsing import normalize_invoice_number, normalize_name
from opsagent.domain.schemas import PurchaseOrderStatus
from opsagent.infra.db.models import Invoice, Payment, PurchaseOrder, Vendor

MAX_ROWS = 10


class SearchVendorsArgs(BaseModel):
    query: str = Field(description="Nombre o RUC (parcial) del proveedor")


class VendorArgs(BaseModel):
    vendor_tax_id: str = Field(description="RUC del proveedor, 13 dígitos")


class PurchaseOrderArgs(BaseModel):
    po_number: str = Field(description="Número de orden de compra, p. ej. OC-2026-0123")


class FindPaymentsArgs(BaseModel):
    vendor_tax_id: str = Field(description="RUC del proveedor")
    invoice_number: str | None = Field(None, description="Número de factura, si se conoce")
    amount: Decimal | None = Field(None, description="Monto exacto a buscar, si se conoce")


class SimilarInvoicesArgs(BaseModel):
    vendor_tax_id: str = Field(description="RUC del proveedor")
    total: Decimal = Field(description="Total de la factura de referencia")


def _money(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _day(value: date | None) -> str | None:
    return value.isoformat() if value else None


def search_vendors(session: Session, args: SearchVendorsArgs) -> list[dict[str, Any]]:
    target = normalize_name(args.query)
    digits = "".join(ch for ch in args.query if ch.isdigit())
    scored = []
    for vendor in session.scalars(select(Vendor)):
        names = [vendor.name, *(vendor.aliases or [])]
        score = max(SequenceMatcher(None, target, normalize_name(n)).ratio() for n in names)
        if digits and digits in vendor.tax_id:
            score = 1.0
        scored.append((score, vendor))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {"name": v.name, "tax_id": v.tax_id, "aliases": v.aliases, "similarity": round(s, 2)}
        for s, v in scored[:5]
        if s >= 0.4
    ]


def list_open_purchase_orders(session: Session, args: VendorArgs) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(PurchaseOrder)
        .join(Vendor)
        .where(
            Vendor.tax_id == args.vendor_tax_id, PurchaseOrder.status == PurchaseOrderStatus.OPEN
        )
        .order_by(PurchaseOrder.issue_date.desc())
        .limit(MAX_ROWS)
    )
    return [
        {"po_number": po.po_number, "issue_date": _day(po.issue_date), "total": _money(po.total)}
        for po in rows
    ]


def get_purchase_order(session: Session, args: PurchaseOrderArgs) -> dict[str, Any] | None:
    po = session.scalar(
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.lines), selectinload(PurchaseOrder.vendor))
        .where(PurchaseOrder.po_number == args.po_number.strip().upper())
    )
    if po is None:
        return None
    return {
        "po_number": po.po_number,
        "vendor": po.vendor.name,
        "vendor_tax_id": po.vendor.tax_id,
        "status": po.status.value,
        "issue_date": _day(po.issue_date),
        "subtotal": _money(po.subtotal),
        "tax": _money(po.tax),
        "total": _money(po.total),
        "lines": [
            {
                "description": line.description,
                "quantity": str(line.quantity),
                "unit_price": _money(line.unit_price),
                "total": _money(line.total),
            }
            for line in po.lines
        ],
    }


def find_payments(session: Session, args: FindPaymentsArgs) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(
            select(Payment)
            .join(Vendor)
            .where(Vendor.tax_id == args.vendor_tax_id)
            .order_by(Payment.paid_on.desc())
        )
    )
    if args.invoice_number:
        wanted = normalize_invoice_number(args.invoice_number)
        rows = [
            p
            for p in rows
            if p.invoice_number
            and normalize_invoice_number(p.invoice_number) in (wanted, wanted.rsplit("-", 1)[-1])
        ] or rows
    if args.amount is not None:
        rows.sort(key=lambda p: abs(p.amount - (args.amount or Decimal(0))))
    return [
        {
            "reference": p.reference,
            "amount": _money(p.amount),
            "paid_on": _day(p.paid_on),
            "memo_invoice_number": p.invoice_number,
            "memo_po_number": p.po_number,
        }
        for p in rows[:MAX_ROWS]
    ]


def find_similar_invoices(session: Session, args: SimilarInvoicesArgs) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(Invoice)
        .where(Invoice.vendor_tax_id == args.vendor_tax_id, Invoice.total.is_not(None))
        .order_by(Invoice.created_at.desc())
        .limit(50)
    )
    ranked = sorted(rows, key=lambda inv: abs((inv.total or Decimal(0)) - args.total))
    return [
        {
            "file": inv.original_filename,
            "invoice_number": inv.invoice_number,
            "total": _money(inv.total),
            "issue_date": _day(inv.issue_date),
            "decision": inv.current_action.value if inv.current_action else None,
        }
        for inv in ranked[:5]
    ]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[Session, Any], Any]

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }

    def run(self, session: Session, raw_arguments: str) -> str:
        """Execute with validated args; errors are returned to the model, never raised."""
        try:
            args = self.args_model.model_validate_json(raw_arguments or "{}")
        except ValidationError as exc:
            return json.dumps({"error": f"argumentos inválidos: {exc.errors()[:3]}"}, default=str)
        result = self.handler(session, args)
        return json.dumps({"result": result}, ensure_ascii=False, default=str)


LOOKUP_TOOLS: tuple[Tool, ...] = (
    Tool(
        "search_vendors",
        "Busca proveedores registrados por nombre aproximado o RUC parcial.",
        SearchVendorsArgs,
        search_vendors,
    ),
    Tool(
        "list_open_purchase_orders",
        "Lista las órdenes de compra abiertas de un proveedor, con su total.",
        VendorArgs,
        list_open_purchase_orders,
    ),
    Tool(
        "get_purchase_order",
        "Devuelve una orden de compra con sus líneas, proveedor y total.",
        PurchaseOrderArgs,
        get_purchase_order,
    ),
    Tool(
        "find_payments",
        "Busca pagos (transferencias) hechos a un proveedor, opcionalmente por factura o monto.",
        FindPaymentsArgs,
        find_payments,
    ),
    Tool(
        "find_similar_invoices",
        "Busca facturas ya recibidas del mismo proveedor con un total parecido.",
        SimilarInvoicesArgs,
        find_similar_invoices,
    ),
)
TOOLS_BY_NAME = {tool.name: tool for tool in LOOKUP_TOOLS}


def openai_tools() -> list[dict[str, Any]]:
    return [tool.openai_schema() for tool in LOOKUP_TOOLS]
