import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Eye,
  FileQuestion,
  Info,
  Loader2,
  MailQuestion,
  ShieldAlert,
  ThumbsDown,
  ThumbsUp,
  type LucideIcon,
} from "lucide-react";

import type { DecisionAction, InvoiceStatus } from "../lib/api";
import { ACTION_LABEL, findingLabel, findingSeverity } from "../lib/format";

type Tone = "good" | "warning" | "serious" | "critical" | "neutral" | "accent";

// Status color is never alone: every badge has an icon and a text label.
const TONE: Record<Tone, string> = {
  good: "bg-[var(--good-wash)] text-good-ink ring-good/40",
  warning: "bg-[var(--warning-wash)] text-ink ring-warning/60",
  serious: "bg-[var(--serious-wash)] text-ink ring-serious/60",
  critical: "bg-[var(--critical-wash)] text-critical ring-critical/40",
  neutral: "bg-surface-2 text-ink-2 ring-line",
  accent: "bg-surface-2 text-accent ring-accent/40",
};
const ICON_TONE: Record<Tone, string> = {
  good: "text-good",
  warning: "text-warning",
  serious: "text-serious",
  critical: "text-critical",
  neutral: "text-muted",
  accent: "text-accent",
};

function Badge({ tone, icon: Icon, label, spin }: { tone: Tone; icon: LucideIcon; label: string; spin?: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${TONE[tone]}`}
    >
      <Icon aria-hidden className={`size-3.5 ${ICON_TONE[tone]} ${spin ? "animate-spin" : ""}`} />
      {label}
    </span>
  );
}

const ACTION_TONE: Record<DecisionAction, { tone: Tone; icon: LucideIcon }> = {
  auto_approve: { tone: "good", icon: CheckCircle2 },
  human_review: { tone: "warning", icon: Eye },
  request_info: { tone: "serious", icon: MailQuestion },
};

export function DecisionBadge({
  status,
  action,
  approved,
}: {
  status: InvoiceStatus;
  action: DecisionAction | null;
  approved: boolean | null;
}) {
  if (status === "received") return <Badge tone="neutral" icon={Clock} label="En cola" />;
  if (status === "processing") return <Badge tone="accent" icon={Loader2} label="Procesando" spin />;
  if (status === "failed") return <Badge tone="critical" icon={AlertTriangle} label="Error técnico" />;
  if (!action) return null;
  if (action !== "auto_approve" && approved === true)
    return <Badge tone="good" icon={ThumbsUp} label="Aprobada por humano" />;
  if (approved === false) return <Badge tone="critical" icon={ThumbsDown} label="Rechazada" />;
  const { tone, icon } = ACTION_TONE[action];
  return <Badge tone={tone} icon={icon} label={ACTION_LABEL[action]} />;
}

export function ActionBadge({ action }: { action: DecisionAction }) {
  const { tone, icon } = ACTION_TONE[action];
  return <Badge tone={tone} icon={icon} label={ACTION_LABEL[action]} />;
}

export function FindingChip({ code }: { code: string }) {
  const severity = findingSeverity(code);
  if (severity === "risk") return <Badge tone="critical" icon={ShieldAlert} label={findingLabel(code)} />;
  if (severity === "missing_info")
    return <Badge tone="serious" icon={FileQuestion} label={findingLabel(code)} />;
  return <Badge tone="neutral" icon={Info} label={findingLabel(code)} />;
}
