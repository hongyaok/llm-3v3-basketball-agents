"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import type { ExperimentOverview, PairedSeedEntry } from "@/lib/types";
import {
  COLORS,
  conditionColor,
  fmt,
  metricById,
  sign,
} from "@/lib/format";
import { Legend, LineChartSvg } from "./SharedUi";

export function SeedChart({
  experimentId,
  conditions,
  rows,
}: {
  experimentId: string;
  conditions: ExperimentOverview["conditions"];
  rows: PairedSeedEntry[];
}) {
  const router = useRouter();
  if (!rows.length) {
    return (
      <div className="empty-state">No paired seed estimates available.</div>
    );
  }
  const width = 510;
  const height = 305;
  const x0 = 66;
  const x1 = 464;
  const top = 36;
  const bottom = 268;
  const extent =
    Math.max(0.25, ...rows.map((r) => Math.abs(r.difference))) * 1.12;
  const x = (value: number) =>
    x0 + ((value + extent) / (extent * 2)) * (x1 - x0);
  const y = (i: number) =>
    top + (i * (bottom - top)) / Math.max(rows.length - 1, 1);
  const ticks = [
    -extent / 1.12,
    -extent / 2.24,
    0,
    extent / 2.24,
    extent / 1.12,
  ];

  const openSeed = (seed: string) => {
    router.push(
      `/experiments/${encodeURIComponent(
        experimentId
      )}/games?seed=${encodeURIComponent(seed)}`
    );
  };

  return (
    <svg
      className="chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Paired seed differences in points per possession"
    >
      <text x="70" y="16" fill={COLORS[1]}>
        ← {conditions[1].label} ahead
      </text>
      <text x="345" y="16">
        {conditions[0].label} ahead →
      </text>
      {ticks.map((t, idx) => (
        <React.Fragment key={idx}>
          <line
            className={t === 0 ? "axis" : "grid"}
            x1={x(t)}
            x2={x(t)}
            y1="25"
            y2="280"
          />
          <text x={x(t)} y="299" textAnchor="middle">
            {fmt(t, 2)}
          </text>
        </React.Fragment>
      ))}
      {rows.map((r, i) => {
        const fill = r.difference >= 0 ? COLORS[0] : COLORS[1];
        return (
          <g
            key={r.seed}
            className="seed-target"
            data-seed={r.seed}
            tabIndex={0}
            role="button"
            aria-label={`Inspect seed ${r.seed}, difference ${fmt(
              r.difference,
              3
            )}`}
            onClick={() => openSeed(r.seed)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                openSeed(r.seed);
              }
            }}
          >
            <title>{`Seed ${r.seed} · ${sign(
              r.difference
            )} PPP · click to inspect`}</title>
            <rect
              x="0"
              y={y(i) - 11}
              width="510"
              height="22"
              fill="transparent"
            />
            <text x="45" y={y(i) + 3} textAnchor="end">
              {r.seed}
            </text>
            <rect
              x={Math.min(x(0), x(r.difference))}
              y={y(i) - 5}
              width={Math.max(2, Math.abs(x(r.difference) - x(0)))}
              height="10"
              rx="3"
              fill={fill}
            />
            <circle cx={x(r.difference)} cy={y(i)} r="3.5" fill={fill} />
            <text
              x={
                r.difference < 0
                  ? x(r.difference) - 6
                  : x(r.difference) + 6
              }
              y={y(i) + 3}
              textAnchor={r.difference < 0 ? "end" : "start"}
              style={{ fontSize: "8px" }}
            >
              {sign(r.difference, 2)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function AdaptationCard({
  experiment,
}: {
  experiment: ExperimentOverview;
}) {
  const adaptationMeasureIds = (
    experiment.study?.measures?.adaptation || ["ppp"]
  ).filter((id) =>
    experiment.adaptation.some((r) => r.metric === id && r.rate !== null)
  );
  const [selectedMetric, setSelectedMetric] = useState(
    adaptationMeasureIds[0] || "ppp"
  );

  const rows = experiment.adaptation.filter(
    (r) => r.metric === selectedMetric
  );
  const bins = ["q1", "q2", "q3", "q4", "q5"];
  if (rows.some((r) => r.time_bin === "ot" && r.rate != null)) {
    bins.push("ot");
  }
  const series = experiment.conditions.map((c) => ({
    label: c.label,
    color: conditionColor(experiment.conditions, c.id),
    values: bins.map(
      (b) =>
        rows.find((r) => r.condition === c.id && r.time_bin === b)?.rate ??
        null
    ),
  }));

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h2>Through the game</h2>
          <p>Condition-level rates by regulation-time quintile</p>
        </div>
        <select
          id="adaptation-metric"
          className="metric-select"
          aria-label="Adaptation metric"
          value={selectedMetric}
          onChange={(e) => setSelectedMetric(e.target.value)}
        >
          {adaptationMeasureIds.map((id) => (
            <option key={id} value={id}>
              {metricById(experiment.metrics, id)?.name || id}
            </option>
          ))}
        </select>
      </div>
      <div className="card-body">
        <Legend conditions={experiment.conditions} />
        <div id="adaptation-chart">
          <LineChartSvg
            series={series}
            labels={bins.map((b) => (b === "ot" ? "OT" : `Q${b[1]}`))}
            percent={selectedMetric !== "ppp"}
            height={275}
          />
        </div>
        <p className="chart-note">
          Counts pooled across games. Unobserved bins stay blank; overtime is
          separate when present.
        </p>
      </div>
    </section>
  );
}

