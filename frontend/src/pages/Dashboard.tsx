import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Eye, MailQuestion } from "lucide-react";
import { Link } from "react-router-dom";

import { DecisionBadge } from "../components/Badges";
import { BarList, ColumnChart } from "../components/Charts";
import { api } from "../lib/api";
import { fmtCost, fmtDate, fmtDateTime, fmtMoney, fmtMs, fmtPct, findingLabel } from "../lib/format";

type Day = { day: string; processed: number; auto_approved: number; cost_usd: string };

/** Continuous window ending today: days without activity show as zero, not as a gap. */
function lastDays(daily: Day[], count: number): Day[] {
  const byDay = new Map(daily.map((d) => [d.day, d]));
  const today = new Date();
  return Array.from({ length: count }, (_, i) => {
    const date = new Date(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate() - (count - 1 - i)));
    const key = date.toISOString().slice(0, 10);
    return byDay.get(key) ?? { day: key, processed: 0, auto_approved: 0, cost_usd: "0" };
  });
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl bg-surface p-4 ring-1 ring-line">
      <div className="text-xs text-ink-2">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}

function Panel({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="min-w-0 rounded-xl bg-surface p-4 ring-1 ring-line">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

export function Dashboard() {
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats, refetchInterval: 10_000 });
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs, refetchInterval: 10_000 });
  const recent = useQuery({
    queryKey: ["invoices", "recent"],
    queryFn: () => api.invoices({ limit: 6 }),
    refetchInterval: 10_000,
  });

  const s = stats.data;
  const decided = s ? Object.values(s.by_action).reduce((a, b) => a + b, 0) : 0;
  const breakdown = [
    { key: "auto_approve", label: "Aprobadas automáticamente", icon: CheckCircle2, tone: "text-good" },
    { key: "human_review", label: "A revisión humana", icon: Eye, tone: "text-warning" },
    { key: "request_info", label: "Información solicitada", icon: MailQuestion, tone: "text-serious" },
  ] as const;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Resumen de operación</h1>
        <p className="text-sm text-ink-2">
          El agente procesa facturas sin supervisión: extrae, concilia contra órdenes y pagos, y decide.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Tile label="Facturas recibidas" value={String(s?.invoices_total ?? "—")} hint={`${decided} decididas`} />
        <Tile label="Aprobación automática" value={fmtPct(s?.auto_approval_rate)} hint="sobre las decididas" />
        <Tile label="Pendientes de revisión" value={String(s?.pending_review ?? "—")} hint="esperan a una persona" />
        <Tile label="Costo LLM total" value={fmtCost(s?.total_cost_usd)} hint="precio de lista estimado" />
        <Tile label="Costo por factura" value={fmtCost(s?.avg_cost_per_invoice_usd)} hint="promedio" />
        <Tile
          label="Latencia por factura"
          value={fmtMs(s?.latency_p50_ms)}
          hint={`p95 ${fmtMs(s?.latency_p95_ms)}`}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel title="Decisiones del agente">
          <ul className="space-y-3">
            {breakdown.map(({ key, label, icon: Icon, tone }) => {
              const count = s?.by_action[key] ?? 0;
              return (
                <li key={key} className="flex items-center gap-3">
                  <Icon className={`size-5 ${tone}`} aria-hidden />
                  <span className="flex-1 text-sm">{label}</span>
                  <span className="tabular text-lg font-semibold">{count}</span>
                  <span className="tabular w-12 text-right text-xs text-muted">
                    {decided ? fmtPct(count / decided) : "—"}
                  </span>
                </li>
              );
            })}
          </ul>
          {!!s?.by_status.failed && (
            <p className="mt-4 rounded-lg bg-[var(--critical-wash)] px-3 py-2 text-xs">
              {s.by_status.failed} con error técnico (se reintentan solas con back-off).
            </p>
          )}
        </Panel>
        <Panel title="Facturas procesadas por día">
          <ColumnChart
            title="Facturas procesadas por día"
            data={lastDays(s?.daily ?? [], 14).map((d) => ({
              label: fmtDate(d.day).replace(/ \d{4}$/, ""),
              value: d.processed,
              detail: `${d.processed} procesadas · ${d.auto_approved} automáticas · ${fmtCost(d.cost_usd)}`,
            }))}
          />
        </Panel>
        <Panel title="Hallazgos más frecuentes">
          <BarList
            title="Hallazgos más frecuentes"
            data={(s?.top_findings ?? []).map((f) => ({ label: findingLabel(f.code), value: f.count }))}
          />
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel
          title="Últimas facturas"
          action={
            <Link to="/facturas" className="text-xs text-accent hover:underline">
              Ver todas
            </Link>
          }
        >
          <ul className="divide-y divide-line">
            {recent.data?.items.map((inv) => (
              <li key={inv.id}>
                <Link
                  to={`/facturas/${inv.id}`}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 hover:bg-surface-2"
                >
                  <div className="min-w-0 flex-1 basis-48">
                    <div className="truncate text-sm font-medium">{inv.vendor_name ?? inv.original_filename}</div>
                    <div className="text-xs text-muted">{inv.original_filename}</div>
                  </div>
                  <span className="tabular text-sm">{fmtMoney(inv.total)}</span>
                  <DecisionBadge status={inv.status} action={inv.current_action} approved={inv.approved} />
                </Link>
              </li>
            ))}
          </ul>
        </Panel>
        <Panel title="Ejecuciones del agente (scheduler, API, MCP)">
          <div className="overflow-x-auto">
          <table className="w-full min-w-[28rem] text-sm">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="py-1 font-normal">Inicio</th>
                <th className="py-1 font-normal">Origen</th>
                <th className="py-1 text-right font-normal">Procesadas</th>
                <th className="py-1 text-right font-normal">Fallidas</th>
                <th className="py-1 text-right font-normal">Costo</th>
              </tr>
            </thead>
            <tbody className="tabular divide-y divide-line">
              {runs.data?.slice(0, 8).map((run) => (
                <tr key={run.id}>
                  <td className="py-1.5">{fmtDateTime(run.started_at)}</td>
                  <td className="py-1.5">{run.trigger}</td>
                  <td className="py-1.5 text-right">{run.stats.processed ?? "—"}</td>
                  <td className="py-1.5 text-right">{run.stats.failed ?? "—"}</td>
                  <td className="py-1.5 text-right">{fmtCost(run.stats.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          {runs.data?.length === 0 && <p className="py-6 text-center text-sm text-muted">Aún no hay ejecuciones.</p>}
        </Panel>
      </div>
    </div>
  );
}
