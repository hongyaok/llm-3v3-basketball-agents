import React from "react";
import Link from "next/link";
import type {
  BoxScoreCondition,
  ExperimentBoxScore,
  ExperimentMetric,
  ExperimentOverview,
  PooledMetric,
} from "@/lib/types";
import { fmt, metricById, sign, title } from "@/lib/format";

/** Short labels, matching the acronyms the deck uses. */
const COORDINATION_METRICS = [
  ["maar", "MAAR", "message alignment"],
  ["ccar", "CCAR", "captain alignment"],
  [
    "coordination_conflict_rate",
    "CCR",
    "coordination conflicts, lower is better",
  ],
  ["maur", "MAUR", "memory usage"],
  ["cssr", "CSSR", "strategy selection"],
] as const;

const BOX_COLUMNS = [
  ["passes_per_game", "Passes"],
  ["assists_per_game", "Assists"],
  ["rebounds_per_game", "Rebounds"],
  ["turnovers_per_game", "Turnovers"],
] as const;

/** Control first, then the three feature ablations — the order the deck uses. */
const STUDY_ORDER = [
  "pilot_v1",
  "abl_comms_v1",
  "abl_captain_v1",
  "abl_memory_v1",
];

function orderedIds(ids: string[]): string[] {
  const ranked = STUDY_ORDER.filter((id) => ids.includes(id));
  return [...ranked, ...ids.filter((id) => !ranked.includes(id)).sort()];
}

function pct(value: number | null | undefined): string {
  return value == null ? "N/A" : `${(value * 100).toFixed(2)}%`;
}

function oneDecimal(value: number | null | undefined): string {
  return value == null ? "N/A" : value.toFixed(1);
}

function ciText(ci: [number, number] | null | undefined, digits = 3): string {
  if (!ci) return "—";
  return `[${sign(ci[0], digits)}, ${sign(ci[1], digits)}]`;
}

/** Two values stacked, so five metric columns fit without horizontal scroll. */
function PairCell({ first, second }: { first: string; second: string }) {
  return (
    <td className="mono">
      <span className="pair-line">{first}</span>
      <span className="pair-line">{second}</span>
    </td>
  );
}

function pairValues(
  metric: ExperimentMetric,
  ids: [string, string],
  format: (value: number | null | undefined) => string
): [string, string] {
  return [
    format(metric.conditions[ids[0]]?.rate),
    format(metric.conditions[ids[1]]?.rate),
  ];
}

function ComparisonCell({
  id,
  title: studyTitle,
  overview,
}: {
  id: string;
  title: string;
  overview: ExperimentOverview;
}) {
  return (
    <td>
      <Link
        className="text-link"
        href={`/experiments/${encodeURIComponent(id)}`}
      >
        {studyTitle}
      </Link>
      <small>
        {overview.conditions[0]?.label} vs {overview.conditions[1]?.label}
      </small>
    </td>
  );
}

export function CrossExperimentTables({
  overviews,
  boxScores,
}: {
  overviews: Record<string, ExperimentOverview>;
  boxScores: Record<string, ExperimentBoxScore>;
}) {
  const ids = orderedIds(Object.keys(overviews));
  if (ids.length === 0) return null;

  const rows = ids.map((id) => {
    const overview = overviews[id];
    return {
      id,
      title: overview.study?.title || id,
      overview,
      pairIds: [overview.conditions[0]?.id, overview.conditions[1]?.id] as [
        string,
        string,
      ],
      ppp: metricById(overview.metrics, "ppp"),
      box: boxScores[id]?.conditions ?? {},
    };
  });

  const baselineLabel =
    rows[0]?.overview.conditions[0]?.label ?? "Full system";
  const variantLabels = [
    ...new Set(rows.map((row) => row.overview.conditions[1]?.label ?? "")),
  ].filter(Boolean);
  const pairLegend = `Top value ${baselineLabel}, bottom value the comparison condition.`;

  return (
    <>
      <section className="section-heading">
        <h2>All four studies, side by side</h2>
        <Link className="text-link" href="/experiments/pilot_v1">
          Open the control experiment →
        </Link>
      </section>

      <section className="card table-card">
        <div className="card-head">
          <div>
            <h2>Performance · points per possession</h2>
            <p>
              Pooled {baselineLabel} versus the comparison condition, with the
              paired seed effect.
            </p>
          </div>
        </div>
        <div className="table-wrap">
          <table className="metric-table cross-study-table">
            <thead>
              <tr>
                <th>Comparison</th>
                <th>Seeds</th>
                <th>Pooled PPP (A / B)</th>
                <th>Paired ΔPPP</th>
                <th>95% CI</th>
                <th>p-value</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const paired = row.ppp?.paired;
                return (
                  <tr key={row.id}>
                    <ComparisonCell
                      id={row.id}
                      title={row.title}
                      overview={row.overview}
                    />
                    <td className="mono">{fmt(paired?.n_seeds, 0)}</td>
                    <td className="mono">
                      {row.ppp
                        ? `${fmt(
                            row.ppp.conditions[row.pairIds[0]]?.rate,
                            3
                          )} / ${fmt(row.ppp.conditions[row.pairIds[1]]?.rate, 3)}`
                        : "—"}
                    </td>
                    <td className="mono">
                      {paired?.effect_mean == null
                        ? "—"
                        : sign(paired.effect_mean, 3)}
                    </td>
                    <td className="mono">
                      {ciText(paired?.bootstrap_95_ci ?? null)}
                    </td>
                    <td className="mono">
                      {fmt(paired?.wilcoxon?.p_value, 3)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="table-foot">
          Effect = {baselineLabel} − comparison condition, averaged across
          paired seeds. A paired effect can differ from subtracting the pooled
          values. Seeds are the matched pairs behind the interval and the test.
        </div>
      </section>

      <section className="card table-card">
        <div className="card-head">
          <div>
            <h2>Other common game statistics</h2>
            <p>
              Per-game counts, counted straight off the saved game logs.{" "}
              {pairLegend}
            </p>
          </div>
        </div>
        <div className="table-wrap">
          <table className="metric-table cross-study-table">
            <thead>
              <tr>
                <th>Comparison</th>
                {BOX_COLUMNS.map(([key, label]) => (
                  <th key={key}>{label} / game</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <ComparisonCell
                    id={row.id}
                    title={row.title}
                    overview={row.overview}
                  />
                  {BOX_COLUMNS.map(([key]) => (
                    <PairCell
                      key={key}
                      first={oneDecimal(
                        row.box[row.pairIds[0]]?.[
                          key as keyof BoxScoreCondition
                        ] as number | null | undefined
                      )}
                      second={oneDecimal(
                        row.box[row.pairIds[1]]?.[
                          key as keyof BoxScoreCondition
                        ] as number | null | undefined
                      )}
                    />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="table-foot">
          Passes are executed PASS actions. An assist is a made shot in the
          event right after a teammate pass. A rebound is a loose ball gathered
          off the boards. Turnovers are logged possession losses.
        </div>
      </section>

      <section className="card table-card">
        <div className="card-head">
          <div>
            <h2>Coordination and adaptation</h2>
            <p>
              Message alignment, captain alignment, coordination conflicts,
              memory use and strategy selection. {pairLegend}
            </p>
          </div>
        </div>
        <div className="table-wrap">
          <table className="metric-table cross-study-table">
            <thead>
              <tr>
                <th>Comparison</th>
                {COORDINATION_METRICS.map(([id, short]) => (
                  <th key={id}>{short}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <ComparisonCell
                    id={row.id}
                    title={row.title}
                    overview={row.overview}
                  />
                  {COORDINATION_METRICS.map(([id]) => {
                    const metric = metricById(row.overview.metrics, id);
                    if (!metric) {
                      return (
                        <td key={id} className="mono">
                          —
                        </td>
                      );
                    }
                    const [first, second] = pairValues(metric, row.pairIds, pct);
                    return <PairCell key={id} first={first} second={second} />;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="table-foot">
          {COORDINATION_METRICS.map(([, short, description]) => (
            <span key={short}>
              <strong>{short}</strong> {description}.{" "}
            </span>
          ))}
          Rates pool every game of a condition with a non-zero denominator, so a
          switched-off mechanism is still reported when the calls happened.
          <strong> N/A</strong> means the condition had no opportunities to
          evaluate at all.
        </div>
      </section>

      <section className="card table-card">
        <div className="card-head">
          <div>
            <h2>System validity</h2>
            <p>
              Invalid actions are assigned to a condition; state consistency
              covers the whole game. {pairLegend}
            </p>
          </div>
        </div>
        <div className="table-wrap">
          <table className="metric-table cross-study-table">
            <thead>
              <tr>
                <th>Comparison</th>
                <th>IAR</th>
                <th>SIR</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const iar = row.overview.validity.iar;
                const sir: PooledMetric = row.overview.validity.sir;
                const [first, second] = pairValues(iar, row.pairIds, pct);
                return (
                  <tr key={row.id}>
                    <ComparisonCell
                      id={row.id}
                      title={row.title}
                      overview={row.overview}
                    />
                    <PairCell first={first} second={second} />
                    <td className="mono">
                      {sir.rate == null
                        ? title(sir.status || "Unavailable")
                        : `${fmt(sir.rate * 100, 2)}%`}
                      <small className="pair-line">
                        {fmt(sir.numerator, 0)}/{fmt(sir.denominator, 0)}{" "}
                        transitions
                      </small>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="table-foot">
          Both rates are lower-is-better. Zero state inconsistency means every
          logged invariant check passed.
          {variantLabels.length
            ? ` Comparison conditions: ${variantLabels.join(", ")}.`
            : ""}
        </div>
      </section>
    </>
  );
}
