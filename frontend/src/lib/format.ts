import type { ConditionSummary, ExperimentMetric } from "./types";

export const COLORS = ["#24795a", "#d97745"] as const;

export const FEATURE_NAMES: Record<string, string> = {
  comms: "Communication",
  captain: "Captain calls",
  memory_write: "Memory updates",
};

export function fmt(value: unknown, digits = 2): string {
  if (value === null || value === undefined || typeof value === "boolean") {
    return "—";
  }
  const num = Number(value);
  if (!Number.isFinite(num)) {
    return "—";
  }
  return num.toLocaleString("en", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function sign(value: unknown, digits = 3): string {
  if (value === null || value === undefined || typeof value === "boolean") {
    return "—";
  }
  const num = Number(value);
  if (!Number.isFinite(num)) {
    return "—";
  }
  const prefix = num > 0 ? "+" : num < 0 ? "−" : "";
  return `${prefix}${fmt(Math.abs(num), digits)}`;
}

export function title(value: unknown): string {
  const s = String(value ?? "")
    .replaceAll("_", " ")
    .toLowerCase();
  return s.replace(/^./, (c) => c.toUpperCase());
}

export function clock(value: unknown): string {
  if (value === null || value === undefined || typeof value === "boolean") {
    return "—";
  }
  const num = Number(value);
  if (!Number.isFinite(num)) {
    return "—";
  }
  const clamped = Math.max(0, num);
  const mins = Math.floor(clamped / 60);
  const secs = String(Math.floor(clamped % 60)).padStart(2, "0");
  return `${mins}:${secs}`;
}

export function conditionIndex(
  conditions: ConditionSummary[],
  id: string | null | undefined
): number {
  if (!id) return 0;
  return Math.max(
    0,
    conditions.findIndex((c) => c.id === id)
  );
}

export function conditionColor(
  conditions: ConditionSummary[],
  id: string | null | undefined
): string {
  return COLORS[conditionIndex(conditions, id) % COLORS.length];
}

export function conditionLabel(
  conditions: ConditionSummary[],
  id: string | null | undefined
): string {
  if (!id) return "";
  return conditions.find((c) => c.id === id)?.label || id;
}

export function conditionSymbol(
  condition: ConditionSummary,
  fallback: string
): string {
  return condition.id.match(/^([A-Z])_/)?.[1] || fallback;
}

export function featureSummary(condition: ConditionSummary): string {
  return Object.entries(FEATURE_NAMES)
    .map(([key, label]) => {
      const val = condition.features[key];
      const state = val === null || val === undefined ? "unknown" : val ? "on" : "off";
      return `${label} ${state}`;
    })
    .join(" · ");
}

export function metricById(
  metrics: ExperimentMetric[],
  id: string
): ExperimentMetric | undefined {
  return metrics.find((m) => m.id === id);
}

