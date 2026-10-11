import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { DecisionBadge, FindingChip } from "../components/Badges";
import { api, type DecisionAction, type InvoiceStatus } from "../lib/api";
import { fmtCost, fmtDate, fmtMoney, fmtMs } from "../lib/format";

const PAGE = 25;

export function Invoices() {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const action = (params.get("action") ?? undefined) as DecisionAction | undefined;
  const status = (params.get("status") ?? undefined) as InvoiceStatus | undefined;
  const page = Number(params.get("page") ?? 0);
  const q = params.get("q") ?? undefined;

  const query = useQuery({
    queryKey: ["invoices", { action, status, q, page }],
    queryFn: () => api.invoices({ action, status, q, limit: PAGE, offset: page * PAGE }),
    refetchInterval: 10_000,
  });

  const update = (key: string, value: string | undefined) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("page");
    setParams(next);
  };
  const total = query.data?.total ?? 0;

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Facturas</h1>
      <div className="flex flex-wrap items-center gap-2">
        <form
          className="relative"
          onSubmit={(e) => {
            e.preventDefault();
            update("q", search.trim() || undefined);
          }}
        >
          <Search className="absolute top-2.5 left-2.5 size-4 text-muted" aria-hidden />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Proveedor, número, OC o archivo"
            aria-label="Buscar facturas"
            className="w-72 rounded-lg bg-surface py-2 pr-3 pl-8 text-sm ring-1 ring-line outline-none focus:ring-accent"
          />
        </form>
        <select
          value={action ?? ""}
          onChange={(e) => update("action", e.target.value || undefined)}
          aria-label="Filtrar por decisión"
          className="rounded-lg bg-surface px-3 py-2 text-sm ring-1 ring-line"
        >
          <option value="">Todas las decisiones</option>
          <option value="auto_approve">Aprobadas automáticamente</option>
          <option value="human_review">Revisión humana</option>
          <option value="request_info">Pedir información</option>
        </select>
        <select
          value={status ?? ""}
          onChange={(e) => update("status", e.target.value || undefined)}
          aria-label="Filtrar por estado"
          className="rounded-lg bg-surface px-3 py-2 text-sm ring-1 ring-line"
        >
          <option value="">Todos los estados</option>
          <option value="received">En cola</option>
          <option value="processing">Procesando</option>
          <option value="decided">Decididas</option>
          <option value="failed">Error técnico</option>
        </select>
        <span className="ml-auto text-sm text-muted">{total} facturas</span>
      </div>

      <div className="overflow-x-auto rounded-xl bg-surface ring-1 ring-line">
        <table className="w-full min-w-[900px] text-sm">
          <thead className="border-b border-line text-left text-xs text-muted">
            <tr>
              <th className="px-3 py-2 font-normal">Proveedor / archivo</th>
              <th className="px-3 py-2 font-normal">Factura</th>
              <th className="px-3 py-2 font-normal">OC</th>
              <th className="px-3 py-2 text-right font-normal">Total</th>
              <th className="px-3 py-2 font-normal">Decisión</th>
              <th className="px-3 py-2 font-normal">Hallazgos</th>
              <th className="px-3 py-2 text-right font-normal">Costo / tiempo</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {query.data?.items.map((inv) => (
              <tr key={inv.id} className="hover:bg-surface-2">
                <td className="max-w-64 px-3 py-2">
                  <Link to={`/facturas/${inv.id}`} className="block">
                    <div className="truncate font-medium">{inv.vendor_name ?? "—"}</div>
                    <div className="truncate text-xs text-muted">{inv.original_filename}</div>
                  </Link>
                </td>
                <td className="px-3 py-2">
                  <div className="tabular">{inv.invoice_number ?? "—"}</div>
                  <div className="text-xs text-muted">{fmtDate(inv.issue_date)}</div>
                </td>
                <td className="tabular px-3 py-2">{inv.po_number ?? "—"}</td>
                <td className="tabular px-3 py-2 text-right">{fmtMoney(inv.total)}</td>
                <td className="px-3 py-2">
                  <DecisionBadge status={inv.status} action={inv.current_action} approved={inv.approved} />
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    {inv.finding_codes.slice(0, 3).map((code) => (
                      <FindingChip key={code} code={code} />
                    ))}
                  </div>
                </td>
                <td className="tabular px-3 py-2 text-right text-xs text-ink-2">
                  <div>{fmtCost(inv.llm_cost_usd)}</div>
                  <div>{fmtMs(inv.processing_ms)}</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {query.data?.items.length === 0 && (
          <p className="py-10 text-center text-sm text-muted">No hay facturas con esos filtros.</p>
        )}
      </div>

      {total > PAGE && (
        <div className="flex justify-end gap-2 text-sm">
          <button
            type="button"
            disabled={page === 0}
            onClick={() => setParams((p) => (p.set("page", String(page - 1)), p))}
            className="rounded-lg px-3 py-1.5 ring-1 ring-line disabled:opacity-40"
          >
            Anterior
          </button>
          <button
            type="button"
            disabled={(page + 1) * PAGE >= total}
            onClick={() => setParams((p) => (p.set("page", String(page + 1)), p))}
            className="rounded-lg px-3 py-1.5 ring-1 ring-line disabled:opacity-40"
          >
            Siguiente
          </button>
        </div>
      )}
    </div>
  );
}
