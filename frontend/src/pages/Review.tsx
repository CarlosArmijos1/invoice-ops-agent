import { useQuery } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import { Link } from "react-router-dom";

import { DecisionBadge, FindingChip } from "../components/Badges";
import { ReviewForm } from "../components/ReviewForm";
import { api } from "../lib/api";
import { fmtDateTime, fmtMoney } from "../lib/format";

export function Review() {
  const queue = useQuery({
    queryKey: ["invoices", "review"],
    queryFn: () => api.invoices({ needs_review: true, limit: 100 }),
    refetchInterval: 10_000,
  });

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Cola de revisión humana</h1>
        <p className="text-sm text-ink-2">
          Facturas que el agente no aprobó solo. Cada una explica por qué; la decisión final es tuya.
        </p>
      </div>
      {queue.data?.items.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-xl bg-surface py-16 ring-1 ring-line">
          <CheckCircle2 className="size-8 text-good" aria-hidden />
          <p className="text-sm text-ink-2">No hay nada pendiente.</p>
        </div>
      )}
      <ul className="grid gap-3 lg:grid-cols-2">
        {queue.data?.items.map((inv) => (
          <li key={inv.id} className="space-y-3 rounded-xl bg-surface p-4 ring-1 ring-line">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <Link to={`/facturas/${inv.id}`} className="font-medium hover:underline">
                  {inv.vendor_name ?? inv.original_filename}
                </Link>
                <div className="text-xs text-muted">
                  {inv.original_filename} · {inv.invoice_number ?? "sin número"} · decidida{" "}
                  {fmtDateTime(inv.processed_at)}
                </div>
              </div>
              <span className="tabular font-semibold">{fmtMoney(inv.total)}</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <DecisionBadge status={inv.status} action={inv.current_action} approved={inv.approved} />
              {inv.finding_codes.map((code) => (
                <FindingChip key={code} code={code} />
              ))}
            </div>
            <ReviewForm invoiceId={inv.id} compact />
          </li>
        ))}
      </ul>
    </div>
  );
}
