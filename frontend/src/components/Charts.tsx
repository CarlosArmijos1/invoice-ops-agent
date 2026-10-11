import { useState } from "react";

/*
 * Two small single-series bar charts in plain SVG. Spec: thin bars with 4px rounded
 * data-ends anchored to the baseline, 2px gaps, recessive grid, one axis, a hover
 * tooltip on every bar with a hit target larger than the mark, values in ink (never
 * in the series color), and a visually hidden table for screen readers.
 */

interface Datum {
  label: string;
  value: number;
  detail?: string;
}

function niceMax(value: number) {
  if (value <= 0) return 1;
  const exponent = 10 ** Math.floor(Math.log10(value));
  const fraction = value / exponent;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  return nice * exponent;
}

function SrTable({ title, data }: { title: string; data: Datum[] }) {
  return (
    <table className="sr-only">
      <caption>{title}</caption>
      <tbody>
        {data.map((d) => (
          <tr key={d.label}>
            <th scope="row">{d.label}</th>
            <td>{d.value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ColumnChart({ title, data, height = 180 }: { title: string; data: Datum[]; height?: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 560;
  const pad = { top: 12, right: 8, bottom: 26, left: 32 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const max = niceMax(Math.max(...data.map((d) => d.value), 0));
  const slot = innerW / Math.max(data.length, 1);
  const barW = Math.min(28, Math.max(6, slot - 2));
  const ticks = [0, max / 2, max];
  const base = pad.top + innerH;

  if (!data.length) return <p className="py-10 text-center text-sm text-muted">Sin datos todavía.</p>;

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label={title}>
        {ticks.map((t) => {
          const y = pad.top + innerH - (t / max) * innerH;
          return (
            <g key={t}>
              <line x1={pad.left} x2={width - pad.right} y1={y} y2={y} stroke="var(--grid)" strokeWidth={1} />
              <text x={pad.left - 6} y={y + 4} textAnchor="end" fontSize={10} fill="var(--muted)" className="tabular">
                {Number.isInteger(t) ? t : t.toFixed(1)}
              </text>
            </g>
          );
        })}
        {data.map((d, i) => {
          const h = (d.value / max) * innerH;
          const x = pad.left + i * slot + (slot - barW) / 2;
          const y = pad.top + innerH - h;
          const r = Math.min(4, h / 2, barW / 2);
          return (
            <g key={d.label} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={pad.left + i * slot} y={pad.top} width={slot} height={innerH} fill="transparent" />
              {h > 0 && (
                <path
                  // Square at the baseline, 4px rounded at the data end.
                  d={`M${x},${base} V${y + r} Q${x},${y} ${x + r},${y} H${x + barW - r} Q${x + barW},${y} ${x + barW},${y + r} V${base} Z`}
                  fill="var(--series-1)"
                  opacity={hover === null || hover === i ? 1 : 0.55}
                />
              )}
              {(data.length <= 8 || i % Math.ceil(data.length / 8) === 0) && (
                <text x={x + barW / 2} y={height - 8} textAnchor="middle" fontSize={10} fill="var(--muted)">
                  {d.label}
                </text>
              )}
            </g>
          );
        })}
        <line x1={pad.left} x2={width - pad.right} y1={pad.top + innerH} y2={pad.top + innerH} stroke="var(--axis)" />
      </svg>
      {hover !== null && (
        <div
          className="pointer-events-none absolute -translate-x-1/2 rounded-md bg-surface px-2.5 py-1.5 text-xs shadow-md ring-1 ring-line"
          style={{ left: `${((pad.left + hover * slot + slot / 2) / width) * 100}%`, top: 0 }}
        >
          <div className="font-medium">{data[hover].label}</div>
          <div className="tabular text-ink-2">{data[hover].detail ?? data[hover].value}</div>
        </div>
      )}
      <SrTable title={title} data={data} />
    </div>
  );
}

export function BarList({ title, data }: { title: string; data: Datum[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...data.map((d) => d.value), 1);
  if (!data.length) return <p className="py-10 text-center text-sm text-muted">Sin hallazgos todavía.</p>;
  return (
    <div role="img" aria-label={title}>
      <ul className="space-y-2">
        {data.map((d, i) => (
          <li
            key={d.label}
            className="grid grid-cols-[minmax(0,10rem)_1fr_2.5rem] items-center gap-3 text-sm"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
            title={d.detail}
          >
            <span className="truncate text-ink-2">{d.label}</span>
            <span className="h-2.5 rounded-r bg-transparent">
              <span
                className="block h-full rounded-r-[4px]"
                style={{
                  width: `${(d.value / max) * 100}%`,
                  background: "var(--series-1)",
                  opacity: hover === null || hover === i ? 1 : 0.55,
                }}
              />
            </span>
            <span className="tabular text-right font-medium">{d.value}</span>
          </li>
        ))}
      </ul>
      <SrTable title={title} data={data} />
    </div>
  );
}
