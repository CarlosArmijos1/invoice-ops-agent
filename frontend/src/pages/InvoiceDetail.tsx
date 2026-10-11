import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Bot, Copy, User } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ActionBadge, DecisionBadge, FindingChip } from "../components/Badges";
import { ReviewForm } from "../components/ReviewForm";
import { api, type InvoiceDetail as Detail } from "../lib/api";
import { fmtCost, fmtDate, fmtDateTime, fmtMoney, fmtMs, findingSeverity } from "../lib/format";

const EVENT_LABEL: Record<string, string> = {
  received: "Recibida",
  decided: "Decidida por el agente",
  reviewed: "Revisada por una persona",
  processing_failed: "Error técnico (se reintentará)",
};

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl bg-surface p-4 ring-1 ring-line">
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="tabular text-sm">{value ?? "—"}</dd>
    </div>
  );
}

function DocumentViewer({ invoice }: { invoice: Detail }) {
  return (
    <div className="space-y-3">
      <div className="max-h-[78vh] space-y-3 overflow-y-auto rounded-lg">
        {Array.from({ length: invoice.page_count }, (_, page) => (
          <img
            key={page}
            src={api.pageUrl(invoice.id, page)}
            alt={`Factura ${invoice.original_filename}, página ${page + 1} de ${invoice.page_count}`}
            loading="lazy"
            className="w-full rounded-lg bg-white ring-1 ring-line"
          />
        ))}
      </div>
      <a
        href={api.fileUrl(invoice.id)}
        target="_blank"
        rel="noreferrer"
        className="text-xs text-accent hover:underline"
      >
        Abrir archivo original ({invoice.media_type})
      </a>
    </div>
  );
}

function SupplierMessage({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="rounded-lg bg-surface-2 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium text-ink-2">Borrador de correo al proveedor (no se envía solo)</span>
        <button
          type="button"
          onClick={() => {
            navigator.clipboard.writeText(text).then(() => setCopied(true));
          }}
          className="inline-flex items-center gap-1 text-xs text-accent"
        >
          <Copy className="size-3.5" aria-hidden /> {copied ? "Copiado" : "Copiar"}
        </button>
      </div>
      <p className="text-sm whitespace-pre-line">{text}</p>
    </div>
  );
}

export function InvoiceDetail() {
  const { id = "" } = useParams();
  const query = useQuery({
    queryKey: ["invoice", id],
    queryFn: () => api.invoice(id),
    refetchInterval: (q) => (q.state.data && ["received", "processing"].includes(q.state.data.status) ? 2000 : false),
  });
  const inv = query.data;
  if (query.isError) return <p className="text-sm text-critical">No se encontró la factura.</p>;
  if (!inv) return <p className="text-sm text-muted">Cargando…</p>;

  const agentDecision = inv.decisions.find((d) => d.actor === "agent");
  const humanDecisions = inv.decisions.filter((d) => d.actor !== "agent");
  const data = inv.extraction?.data as
    | {
        line_items?: { description: string; quantity: string; unit_price: string; total: string }[];
        subtotal?: string;
        tax?: string;
        due_date?: string;
      }
    | undefined;
  const findings = [...(agentDecision?.findings ?? [])].sort(
    (a, b) =>
      ["risk", "missing_info", "info"].indexOf(findingSeverity(a.code)) -
      ["risk", "missing_info", "info"].indexOf(findingSeverity(b.code)),
  );
  const needsReview = inv.current_action && inv.current_action !== "auto_approve" && inv.approved === null;

  return (
    <div className="space-y-4">
      <Link to="/facturas" className="inline-flex items-center gap-1 text-sm text-ink-2 hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden /> Facturas
      </Link>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{inv.vendor_name ?? inv.original_filename}</h1>
        <DecisionBadge status={inv.status} action={inv.current_action} approved={inv.approved} />
        <span className="ml-auto text-sm text-muted">{inv.original_filename}</span>
      </div>

      {inv.status === "failed" && (
        <div className="rounded-lg bg-[var(--critical-wash)] px-4 py-3 text-sm">
          <strong>Error técnico (intento {inv.attempts}).</strong> No es una decisión de negocio: el agente
          reintentará con back-off. Detalle: <code className="text-xs">{inv.last_error}</code>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="space-y-4">
          <Card title="Documento original">
            <DocumentViewer invoice={inv} />
          </Card>
        </div>

        <div className="space-y-4">
          {agentDecision && (
            <Card title="Decisión del agente">
              <div className="mb-3 flex items-center gap-2">
                <Bot className="size-4 text-accent" aria-hidden />
                <ActionBadge action={agentDecision.action} />
                <span className="text-xs text-muted">{fmtDateTime(agentDecision.created_at)}</span>
              </div>
              <div className="mb-3 flex flex-wrap gap-1.5">
                {findings.map((f) => (
                  <FindingChip key={f.code + f.message} code={f.code} />
                ))}
              </div>
              <p className="text-sm whitespace-pre-line text-ink-2">{agentDecision.justification}</p>
              {agentDecision.supplier_message && (
                <div className="mt-3">
                  <SupplierMessage text={agentDecision.supplier_message} />
                </div>
              )}
            </Card>
          )}

          {(needsReview || humanDecisions.length > 0) && (
            <Card title="Revisión humana">
              {humanDecisions.map((d) => (
                <div key={d.id} className="mb-3 flex items-start gap-2 text-sm">
                  <User className="mt-0.5 size-4 text-ink-2" aria-hidden />
                  <div>
                    <div>
                      <strong>{d.actor.replace("human:", "")}</strong>{" "}
                      {d.review_outcome === "approved" ? "aprobó" : "rechazó"} ·{" "}
                      <span className="text-muted">{fmtDateTime(d.created_at)}</span>
                    </div>
                    <div className="text-ink-2">{d.justification}</div>
                  </div>
                </div>
              ))}
              {needsReview && <ReviewForm invoiceId={inv.id} />}
            </Card>
          )}

          {inv.extraction?.data && (
            <Card title="Datos extraídos">
              <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Field label="RUC proveedor" value={inv.vendor_tax_id} />
                <Field label="N.º factura" value={inv.invoice_number} />
                <Field label="Emisión" value={fmtDate(inv.issue_date)} />
                <Field label="Orden de compra" value={inv.po_number} />
                <Field
                  label="OC conciliada"
                  value={inv.matched_po_number ? `${inv.matched_po_number} · ${fmtMoney(inv.matched_po_total)}` : null}
                />
                <Field label="Vence" value={data?.due_date ? fmtDate(data.due_date) : null} />
                <Field label="Subtotal" value={fmtMoney(data?.subtotal)} />
                <Field label="IVA" value={fmtMoney(data?.tax)} />
                <Field label="Total" value={<strong>{fmtMoney(inv.total)}</strong>} />
              </dl>
              {!!data?.line_items?.length && (
                <table className="mt-4 w-full text-sm">
                  <thead className="text-left text-xs text-muted">
                    <tr>
                      <th className="py-1 font-normal">Descripción</th>
                      <th className="py-1 text-right font-normal">Cant.</th>
                      <th className="py-1 text-right font-normal">P. unit.</th>
                      <th className="py-1 text-right font-normal">Total</th>
                    </tr>
                  </thead>
                  <tbody className="tabular divide-y divide-line">
                    {data.line_items.map((li, i) => (
                      <tr key={i}>
                        <td className="py-1">{li.description}</td>
                        <td className="py-1 text-right">{li.quantity}</td>
                        <td className="py-1 text-right">{fmtMoney(li.unit_price)}</td>
                        <td className="py-1 text-right">{fmtMoney(li.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <p className="mt-3 text-xs text-muted">
                Método: {inv.extraction.method === "text" ? "capa de texto del PDF" : "modelo de visión"} ·{" "}
                {inv.extraction.model} · calidad {inv.extraction.quality_score ?? "—"}
                {inv.extraction.issues.length > 0 && ` · controles fallidos: ${inv.extraction.issues.map((i) => i.check).join(", ")}`}
              </p>
            </Card>
          )}

          <Card title="Observabilidad">
            <div className="mb-3 grid grid-cols-3 gap-3 text-sm">
              <Field label="Costo LLM" value={fmtCost(inv.llm_cost_usd)} />
              <Field label="Tiempo de proceso" value={fmtMs(inv.processing_ms)} />
              <Field label="Intentos" value={inv.attempts} />
            </div>
            <table className="w-full text-xs">
              <thead className="text-left text-muted">
                <tr>
                  <th className="py-1 font-normal">Paso</th>
                  <th className="py-1 font-normal">Modelo</th>
                  <th className="py-1 text-right font-normal">Tokens (in/out)</th>
                  <th className="py-1 text-right font-normal">Latencia</th>
                  <th className="py-1 text-right font-normal">Costo</th>
                </tr>
              </thead>
              <tbody className="tabular divide-y divide-line">
                {inv.llm_calls.map((c, i) => (
                  <tr key={i} className={c.ok ? "" : "text-critical"}>
                    <td className="py-1">{c.purpose === "extract" ? "extracción" : "investigación"}</td>
                    <td className="py-1">{c.model}</td>
                    <td className="py-1 text-right">
                      {c.prompt_tokens} / {c.completion_tokens}
                    </td>
                    <td className="py-1 text-right">{fmtMs(c.latency_ms)}</td>
                    <td className="py-1 text-right">{c.ok ? fmtCost(c.cost_usd) : "error"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3 className="mt-4 mb-2 text-xs font-semibold text-ink-2">Auditoría</h3>
            <ol className="space-y-1 text-xs">
              {inv.events.map((e, i) => (
                <li key={i} className="flex gap-2">
                  <span className="tabular w-36 shrink-0 text-muted">{fmtDateTime(e.created_at)}</span>
                  <span>{EVENT_LABEL[e.event] ?? e.event}</span>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      </div>
    </div>
  );
}
