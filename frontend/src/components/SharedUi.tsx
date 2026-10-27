import React from "react";
import type { ConditionSummary, PooledMetric } from "@/lib/types";
import { fmt, title } from "@/lib/format";

export function ArrowIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M3 10h13m-5-5 5 5-5 5" />
    </svg>
  );
}

export function DownloadIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M10 2v10m-4-4 4 4 4-4M3 12v5h14v-5" />
    </svg>
  );
}

export function PageHeading({
  eyebrow,
  name,
  description,
  actions,
}: {
  eyebrow: string;
  name: string;
  description: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{name}</h1>
        <p>{description}</p>
      </div>
      {actions ? <div className="heading-actions">{actions}</div> : null}
    </div>
  );
}

export function MetricValue({
  metric,
  condition,
}: {
  metric: { percent: boolean; conditions: Record<string, PooledMetric> };
  condition: string;
}) {
  const value = metric.conditions[condition];
  if (value?.rate == null) {
    return (
      <span
        className="status-label"
        title={JSON.stringify(value?.status_counts ?? {})}
      >
        {title(value?.status || "Unavailable")}
      </span>
    );
  }
  return (
    <>
      <span className="table-value">
        {metric.percent
          ? `${fmt(value.rate * 100, 2)}%`
          : fmt(value.rate, 3)}
      </span>
      {value.status === "partial" ? <small>Available games only</small> : null}
    </>
  );
}

export function Legend({ conditions }: { conditions: ConditionSummary[] }) {
  return (
    <div className="legend">
      {conditions.map((c, i) => (
        <span key={c.id}>
          <i className={`dot ${i ? "orange" : ""}`} />
          {c.label}
        </span>
      ))}
    </div>
  );
}

export function LineChartSvg({
  series,
  labels,
  percent = false,
  height = 275,
  active = null,
}: {
  series: Array<{ label: string; color: string; values: Array<number | null> }>;
  labels: string[];
  percent?: boolean;
  height?: number;
  active?: number | null;
}) {
  const w = 500;
  const left = 46;
  const right = 478;
  const top = 28;
  const bottom = height - 36;
  const values = series
    .flatMap((s) => s.values)
    .filter((v): v is number => v != null && Number.isFinite(v));

  if (!values.length) {
    return (
      <div className="empty-state">No observations for this measure.</div>
    );
  }

  const max = Math.max(...values, 0.001) * 1.16;
  const x = (i: number) =>
    left + (i / Math.max(labels.length - 1, 1)) * (right - left);
  const y = (v: number) => bottom - (v / max) * (bottom - top);
  const ticks = Array.from({ length: 5 }, (_, i) => (i * max) / 4);

  return (
    <svg
      className="chart"
      viewBox={`0 0 ${w} ${height}`}
      role="img"
      aria-label={`${series.map((s) => s.label).join(" and ")} over time`}
    >
      {ticks.map((t, idx) => (
        <React.Fragment key={idx}>
          <line
            className="grid"
            x1={left}
            x2={right}
            y1={y(t)}
            y2={y(t)}
          />
          <text x={left - 10} y={y(t) + 4} textAnchor="end">
            {percent
              ? `${fmt(t * 100, t < 0.01 ? 2 : 0)}%`
              : fmt(t, t < 2 ? 2 : 0)}
          </text>
        </React.Fragment>
      ))}
      {labels.map((t, i) =>
        labels.length > 12 && i !== 0 && i !== labels.length - 1 ? null : (
          <text key={i} x={x(i)} y={height - 10} textAnchor="middle">
            {t}
          </text>
        )
      )}
      {series.map((s) => {
        let pathD = "";
        let connected = false;
        s.values.forEach((v, i) => {
          if (v == null) {
            connected = false;
            return;
          }
          pathD += `${connected ? "L" : "M"}${x(i)},${y(v)} `;
          connected = true;
        });
        return (
          <React.Fragment key={s.label}>
            <path
              d={pathD}
              fill="none"
              stroke={s.color}
              strokeWidth="2.5"
              strokeLinejoin="round"
            />
            {s.values.map((v, i) =>
              v == null || labels.length > 12 ? null : (
                <circle
                  key={i}
                  cx={x(i)}
                  cy={y(v)}
                  r="4"
                  fill={s.color}
                  stroke="white"
                  strokeWidth="2"
                >
                  <title>{`${s.label} · ${labels[i]}: ${
                    percent ? `${fmt(v * 100, 3)}%` : fmt(v, 3)
                  }`}</title>
                </circle>
              )
            )}
          </React.Fragment>
        );
      })}
      {active != null ? (
        <line
          className="chart-cursor"
          x1={x(active)}
          x2={x(active)}
          y1={top}
          y2={bottom}
          stroke="#9bad8c"
          strokeDasharray="3 3"
        />
      ) : null}
    </svg>
  );
}

