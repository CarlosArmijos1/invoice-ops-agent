import type { DecisionAction } from "./api";

const money = new Intl.NumberFormat("es-EC", { style: "currency", currency: "USD" });
const tinyMoney = new Intl.NumberFormat("es-EC", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});
const dateTime = new Intl.DateTimeFormat("es-EC", { dateStyle: "medium", timeStyle: "short" });
const dateOnly = new Intl.DateTimeFormat("es-EC", { dateStyle: "medium", timeZone: "UTC" });

export const fmtMoney = (value: string | number | null | undefined) =>
  value === null || value === undefined ? "—" : money.format(Number(value));

/** LLM costs are fractions of a cent: show four decimals so they are not all "$0.00". */
export const fmtCost = (value: string | number | null | undefined) =>
  value === null || value === undefined ? "—" : tinyMoney.format(Number(value));

export const fmtDateTime = (value: string | null | undefined) =>
  value ? dateTime.format(new Date(value)) : "—";

export const fmtDate = (value: string | null | undefined) =>
  value ? dateOnly.format(new Date(`${value}T00:00:00Z`)) : "—";

export const fmtMs = (value: number | null | undefined) => {
  if (value === null || value === undefined) return "—";
  return value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(1)} s`;
};

export const fmtPct = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : `${Math.round(value * 100)} %`;

export const ACTION_LABEL: Record<DecisionAction, string> = {
  auto_approve: "Aprobada automáticamente",
  human_review: "Revisión humana",
  request_info: "Pedir información",
};

export type Severity = "info" | "missing_info" | "risk";

export const FINDINGS: Record<string, { label: string; severity: Severity }> = {
  po_matched: { label: "OC coincide", severity: "info" },
  po_missing: { label: "Sin orden de compra", severity: "missing_info" },
  po_not_found: { label: "OC no existe", severity: "missing_info" },
  po_inferred: { label: "OC inferida", severity: "risk" },
  po_vendor_mismatch: { label: "OC de otro proveedor", severity: "risk" },
  po_overbilled: { label: "OC sobrefacturada", severity: "risk" },
  amount_within_tolerance: { label: "Diferencia tolerada", severity: "info" },
  amount_mismatch: { label: "Monto no coincide", severity: "risk" },
  over_auto_approval_limit: { label: "Sobre el límite", severity: "risk" },
  arithmetic_mismatch: { label: "Aritmética inconsistente", severity: "risk" },
  vendor_unknown: { label: "Proveedor desconocido", severity: "risk" },
  tax_id_missing: { label: "Sin RUC", severity: "missing_info" },
  tax_id_invalid: { label: "RUC no valida", severity: "info" },
  duplicate_invoice: { label: "Duplicada", severity: "risk" },
  paid: { label: "Pagada", severity: "info" },
  unpaid: { label: "Sin pago registrado", severity: "info" },
  payment_amount_mismatch: { label: "Pago no coincide", severity: "risk" },
  multiple_payments: { label: "Pago duplicado", severity: "risk" },
  low_extraction_quality: { label: "Lectura dudosa", severity: "risk" },
  extraction_failed: { label: "Ilegible", severity: "missing_info" },
};

export const findingLabel = (code: string) => FINDINGS[code]?.label ?? code;
export const findingSeverity = (code: string): Severity => FINDINGS[code]?.severity ?? "info";
