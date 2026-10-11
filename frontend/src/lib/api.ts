// Typed client for the FastAPI backend (same origin in production, proxied in dev).

export type DecisionAction = "auto_approve" | "human_review" | "request_info";
export type InvoiceStatus = "received" | "processing" | "decided" | "failed";

export interface Finding {
  code: string;
  message: string;
  details: Record<string, string>;
}

export interface InvoiceSummary {
  id: string;
  original_filename: string;
  media_type: string;
  source: string;
  status: InvoiceStatus;
  current_action: DecisionAction | null;
  approved: boolean | null;
  vendor_name: string | null;
  vendor_tax_id: string | null;
  invoice_number: string | null;
  po_number: string | null;
  issue_date: string | null;
  total: string | null;
  currency: string | null;
  created_at: string;
  processed_at: string | null;
  llm_cost_usd: string;
  processing_ms: number | null;
  attempts: number;
  last_error: string | null;
  finding_codes: string[];
}

export interface DecisionView {
  id: number;
  action: DecisionAction;
  actor: string;
  findings: Finding[];
  justification: string;
  supplier_message: string | null;
  review_outcome: "approved" | "rejected" | null;
  created_at: string;
}

export interface InvoiceDetail extends InvoiceSummary {
  extraction: {
    method: string;
    model: string;
    data: Record<string, unknown> | null;
    valid: boolean;
    quality_score: number | null;
    issues: { check: string }[];
    error: string | null;
  } | null;
  decisions: DecisionView[];
  llm_calls: {
    purpose: string;
    model: string;
    prompt_tokens: number;
    completion_tokens: number;
    cost_usd: string;
    latency_ms: number;
    ok: boolean;
    error: string | null;
    created_at: string;
  }[];
  events: { event: string; payload: Record<string, unknown>; created_at: string }[];
  matched_po_number: string | null;
  matched_po_total: string | null;
  page_count: number;
}

export interface Stats {
  invoices_total: number;
  by_status: Record<string, number>;
  by_action: Record<string, number>;
  pending_review: number;
  auto_approval_rate: number | null;
  total_cost_usd: string;
  avg_cost_per_invoice_usd: string | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  cost_by_model: Record<string, string>;
  daily: { day: string; processed: number; auto_approved: number; cost_usd: string }[];
  top_findings: { code: string; count: number }[];
}

export interface AgentRun {
  id: string;
  trigger: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  stats: { processed?: number; failed?: number; cost_usd?: string };
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export interface InvoiceFilters {
  status?: InvoiceStatus;
  action?: DecisionAction;
  needs_review?: boolean;
  q?: string;
  limit?: number;
  offset?: number;
}

export const api = {
  stats: () => request<Stats>("/api/stats"),
  runs: () => request<AgentRun[]>("/api/agent/runs"),
  invoices: (filters: InvoiceFilters = {}) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== "" && value !== false) params.set(key, String(value));
    }
    return request<{ items: InvoiceSummary[]; total: number }>(`/api/invoices?${params}`);
  },
  invoice: (id: string) => request<InvoiceDetail>(`/api/invoices/${id}`),
  fileUrl: (id: string) => `/api/invoices/${id}/file`,
  pageUrl: (id: string, page: number) => `/api/invoices/${id}/pages/${page}`,
  upload: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<{ invoice_id: string; created: boolean; message: string }>("/api/invoices", {
      method: "POST",
      body,
    });
  },
  review: (id: string, outcome: "approved" | "rejected", reviewer: string, note: string) =>
    request<{ decision_id: string }>(`/api/invoices/${id}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ outcome, reviewer, note }),
    }),
  reports: () => request<{ date: string; processed: number | null }[]>("/api/reports"),
  report: (day: string) =>
    request<{ date: string; markdown: string; summary: Record<string, unknown> }>(
      `/api/reports/${day}`,
    ),
};
