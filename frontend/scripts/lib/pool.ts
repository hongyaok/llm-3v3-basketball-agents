import type { PooledMetric } from "../../src/lib/types";
import { toFiniteNumber } from "./numbers";

/**
 * Faithful port of Python `_pool(rows, metric)` in `src/bball3x3/display/dashboard.py`.
 */
export function poolMetric(
  rows: Array<Record<string, unknown>>,
  metric: string
): PooledMetric {
  const statusCounts: Record<string, number> = {};
  const statusOrder: string[] = [];

  for (const row of rows) {
    const rawStatus = row[`${metric}_status`];
    const status =
      typeof rawStatus === "string" && rawStatus.length > 0 ? rawStatus : "missing";
    if (!(status in statusCounts)) {
      statusCounts[status] = 0;
      statusOrder.push(status);
    }
    statusCounts[status] += 1;
  }

  const valid = rows.filter((row) => {
    const status = row[`${metric}_status`];
    if (status === "ok") {
      return toFiniteNumber(row[`${metric}_rate`]) !== null;
    }
    // A condition with the feature switched off still produced a real rate
    // when it had opportunities: CSSR without a captain sees 398 tactic calls.
    // With a zero denominator there is nothing to report.
    return (
      status === "not_applicable" &&
      (toFiniteNumber(row[`${metric}_denominator`]) ?? 0) > 0
    );
  });

  let numerator = 0;
  let denominator = 0;
  for (const row of valid) {
    numerator += toFiniteNumber(row[`${metric}_numerator`]) ?? 0;
    denominator += toFiniteNumber(row[`${metric}_denominator`]) ?? 0;
  }

  let status: string;
  if (denominator) {
    status = valid.length === rows.length ? "ok" : "partial";
  } else if (statusOrder.length === 1) {
    status = statusOrder[0];
  } else {
    status = "unavailable";
  }

  return {
    numerator,
    denominator,
    rate: denominator ? numerator / denominator : null,
    status,
    status_counts: statusCounts,
    games: valid.length,
  };
}

