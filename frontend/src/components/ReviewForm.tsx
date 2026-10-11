import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import { api, ApiError } from "../lib/api";

export function ReviewForm({ invoiceId, compact = false }: { invoiceId: string; compact?: boolean }) {
  const queryClient = useQueryClient();
  const [reviewer, setReviewer] = useState(() => {
    try {
      return localStorage.getItem("reviewer") ?? "";
    } catch {
      return "";
    }
  });
  const [note, setNote] = useState("");
  const review = useMutation({
    mutationFn: (outcome: "approved" | "rejected") => {
      try {
        localStorage.setItem("reviewer", reviewer);
      } catch {
        /* remembering the name is only a convenience */
      }
      return api.review(invoiceId, outcome, reviewer.trim(), note.trim());
    },
    onSuccess: () => queryClient.invalidateQueries(),
  });
  const disabled = review.isPending || !reviewer.trim();

  return (
    <div className="space-y-2">
      <div className={compact ? "flex gap-2" : "space-y-2"}>
        <input
          value={reviewer}
          onChange={(e) => setReviewer(e.target.value)}
          placeholder="Tu nombre"
          aria-label="Nombre de quien revisa"
          className="w-full rounded-lg bg-surface px-3 py-2 text-sm ring-1 ring-line outline-none focus:ring-accent"
        />
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Nota (opcional)"
          aria-label="Nota de la revisión"
          className="w-full rounded-lg bg-surface px-3 py-2 text-sm ring-1 ring-line outline-none focus:ring-accent"
        />
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={() => review.mutate("approved")}
          className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-[var(--good-wash)] px-3 py-2 text-sm font-medium text-good-ink ring-1 ring-good/40 ring-inset disabled:opacity-50"
        >
          <ThumbsUp className="size-4" aria-hidden /> Aprobar
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={() => review.mutate("rejected")}
          className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-[var(--critical-wash)] px-3 py-2 text-sm font-medium text-critical ring-1 ring-critical/40 ring-inset disabled:opacity-50"
        >
          <ThumbsDown className="size-4" aria-hidden /> Rechazar
        </button>
      </div>
      {review.isError && (
        <p className="text-xs text-critical">
          {review.error instanceof ApiError ? review.error.message : "No se pudo guardar."}
        </p>
      )}
    </div>
  );
}
