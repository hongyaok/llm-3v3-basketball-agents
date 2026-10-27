import type {
  CatalogData,
  ComparisonExperimentRow,
  ComparisonPrimaryMetric,
  ComparisonsSummary,
  ExperimentOverview,
} from "../../src/lib/types";

export interface CatalogEntry {
  overview: ExperimentOverview;
  hasStats: boolean;
  hasAdaptation: boolean;
  logsMatched: number;
}

/**
 * Faithful port of `DashboardCatalog.options()` and `DashboardCatalog.comparison_summary()`.
 */
export function buildCatalogOptions(
  entries: Record<string, CatalogEntry>
): CatalogData {
  const sortedIds = Object.keys(entries).sort();
  if (sortedIds.length === 0) {
    throw new Error("No complete experiment exports found");
  }
  const defaultId = sortedIds.includes("abl_comms_v1")
    ? "abl_comms_v1"
    : sortedIds[0];

  const experiments = sortedIds.map((experimentId) => {
    const { overview } = entries[experimentId];
    return {
      id: experimentId,
      title: overview.study.title,
      conditions: overview.conditions.map((c) => c.label),
      games: overview.summary.games,
      ...(overview.unexported_games?.length
        ? { unexported_games: overview.unexported_games.length }
        : {}),
    };
  });

  return {
    default: defaultId,
    experiments,
  };
}

export function buildComparisonsSummary(
  entries: Record<string, CatalogEntry>
): ComparisonsSummary {
  const sortedIds = Object.keys(entries).sort();
  const rows: ComparisonExperimentRow[] = sortedIds.map((experimentId) => {
    const entry = entries[experimentId];
    const { overview } = entry;
    const metricsById = Object.fromEntries(
      overview.metrics.map((m) => [m.id, m])
    );

    const primary: ComparisonPrimaryMetric[] =
      overview.study.measures.primary.map((metricId) => {
        const metric = metricsById[metricId];
        const paired = metric.paired;
        return {
          id: metricId,
          name: metric.name,
          percent: metric.percent,
          conditions: metric.conditions,
          paired: paired
            ? {
                status: paired.status,
                effect_mean: paired.effect_mean ?? null,
                bootstrap_95_ci: paired.bootstrap_95_ci ?? null,
                p_value: paired.wilcoxon?.p_value ?? null,
                n_seeds: paired.n_seeds,
              }
            : null,
        };
      });

    return {
      experiment_id: experimentId,
      title: overview.study.title,
      conditions: overview.conditions,
      summary: overview.summary,
      primary_metrics: primary,
      logs_matched: entry.logsMatched,
      validity: overview.validity,
      measure_note: overview.study.measures.note,
      has_stats: entry.hasStats,
      has_adaptation: entry.hasAdaptation,
    };
  });

  return { experiments: rows };
}

