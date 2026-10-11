import { useQuery } from "@tanstack/react-query";
import Markdown from "react-markdown";
import { useParams, Link } from "react-router-dom";

import { api } from "../lib/api";
import { fmtDate } from "../lib/format";

export function Reports() {
  const { day } = useParams();
  const list = useQuery({ queryKey: ["reports"], queryFn: api.reports });
  const selected = day ?? list.data?.[0]?.date;
  const report = useQuery({
    queryKey: ["report", selected],
    queryFn: () => api.report(selected!),
    enabled: !!selected,
  });

  return (
    <div className="grid gap-4 lg:grid-cols-[14rem_minmax(0,1fr)]">
      <aside className="space-y-2">
        <h1 className="text-xl font-semibold">Reportes diarios</h1>
        <p className="text-xs text-ink-2">El scheduler genera uno cada mañana (hora de Ecuador).</p>
        <ul className="space-y-1">
          {list.data?.map((r) => (
            <li key={r.date}>
              <Link
                to={`/reportes/${r.date}`}
                className={`block rounded-lg px-3 py-1.5 text-sm ${
                  r.date === selected ? "bg-surface-2 font-medium" : "text-ink-2 hover:bg-surface-2"
                }`}
              >
                {fmtDate(r.date)} <span className="text-xs text-muted">· {r.processed ?? 0}</span>
              </Link>
            </li>
          ))}
        </ul>
        {list.data?.length === 0 && <p className="text-sm text-muted">Aún no hay reportes.</p>}
      </aside>
      <article className="markdown rounded-xl bg-surface p-6 text-sm ring-1 ring-line">
        {report.data ? <Markdown>{report.data.markdown}</Markdown> : <p className="text-muted">Selecciona un reporte.</p>}
      </article>
    </div>
  );
}
