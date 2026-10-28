import path from "node:path";
import type {
  AdaptationRow,
  ConditionSummary,
  ExperimentMetric,
  ExperimentOverview,
  GameSummaryRow,
} from "../../src/lib/types";
import {
  FEATURES,
  FEATURE_ORDER,
  LABELS,
  MATCHUP_MEASURES,
  METRIC_ENTRIES,
} from "./constants";
import { toFiniteNumber } from "./numbers";
import { poolMetric } from "./pool";

export interface ExperimentInput {
  resultsDirName: string;
  games: Array<Record<string, string>>;
  teams: Array<Record<string, string>>;
  possessions: Array<Record<string, string>>;
  stats: Record<string, unknown>;
  adaptation: Array<Record<string, string>>;
  availableLogGameIds: Set<string>;
  plotsManifest?: {
    plots?: Array<{
      comparison: string;
      experiment_id: string;
      file: string;
      metric: string;
    }>;
  };
  unexportedGames?: GameSummaryRow[];
}

export function validateExperimentInput(input: ExperimentInput): string {
  if (!input.games.length) {
    throw new Error("The results export contains no games");
  }
  const ids = input.games.map((row) => row.game_id);
  if (ids.length !== new Set(ids).size) {
    throw new Error("Game IDs must be unique in the results export");
  }
  const experiments = new Set(input.games.map((row) => row.experiment_id));
  if (experiments.size !== 1) {
    throw new Error("Select an export containing a single experiment");
  }
  const experimentId = [...experiments][0];
  for (const gameId of ids) {
    if (
      !gameId ||
      path.posix.basename(gameId) !== gameId ||
      path.win32.basename(gameId) !== gameId ||
      gameId === "." ||
      gameId === ".."
    ) {
      throw new Error(`Invalid game ID: ${gameId}`);
    }
  }
  return experimentId;
}

/**
 * Faithful port of `DashboardData.overview()` in `src/bball3x3/display/dashboard.py`.
 */
export function buildExperimentOverview(input: ExperimentInput): ExperimentOverview {
  const experimentId = validateExperimentInput(input);

  const uniqueConditions = [...new Set(input.teams.map((row) => row.condition))].sort();
  if (uniqueConditions.length !== 2) {
    throw new Error("A dashboard experiment must contain exactly two conditions");
  }

  const rawBaseline = input.stats.baseline;
  let baseline =
    typeof rawBaseline === "string" && uniqueConditions.includes(rawBaseline)
      ? rawBaseline
      : uniqueConditions.includes("A_full")
        ? "A_full"
        : uniqueConditions[0];

  const conditions = [
    baseline,
    ...uniqueConditions.filter((c) => c !== baseline),
  ];

  const conditionRows: Record<string, Array<Record<string, string>>> = {};
  for (const c of conditions) {
    conditionRows[c] = input.teams.filter((r) => r.condition === c);
  }

  const statsResults = Array.isArray(input.stats.results)
    ? (input.stats.results as Array<Record<string, unknown>>)
    : [];
  const comparison =
    statsResults.find((r) => r.experiment_id === experimentId) ?? {};

  const wins: Record<string, number> = {};
  const games: GameSummaryRow[] = [];
  let draws = 0;

  for (const row of input.games) {
    const scoreA = toFiniteNumber(row.final_score_A);
    const scoreB = toFiniteNumber(row.final_score_B);
    const scores = { A: scoreA, B: scoreB };
    const complete = (row.game_complete ?? "").toLowerCase() === "true";
    let winner: string | null = null;
    if (complete && scoreA !== null && scoreB !== null) {
      if (scoreA === scoreB) {
        draws += 1;
      } else {
        const winningTeam = scoreA > scoreB ? "A" : "B";
        winner = row[`team_${winningTeam}_condition`];
        wins[winner] = (wins[winner] ?? 0) + 1;
      }
    }

    const ppp: Record<string, number | null> = {};
    for (const r of input.teams) {
      if (r.game_id === row.game_id && r.ppp_status === "ok") {
        ppp[r.condition] = toFiniteNumber(r.ppp_rate);
      }
    }

    games.push({
      id: row.game_id,
      seed: row.seed,
      first_possession: row.first_possession,
      score: scores,
      conditions: {
        A: row.team_A_condition,
        B: row.team_B_condition,
      },
      winner,
      complete,
      events: toFiniteNumber(row.transitions),
      end_reason: row.end_reason ?? null,
      validation: row.possession_validation ?? null,
      available: input.availableLogGameIds.has(row.game_id),
      ppp,
    });
  }

  games.sort((a, b) => {
    const seedDiff = Number.parseInt(a.seed, 10) - Number.parseInt(b.seed, 10);
    if (seedDiff !== 0) return seedDiff;
    return a.first_possession < b.first_possession
      ? -1
      : a.first_possession > b.first_possession
        ? 1
        : 0;
  });

  const config = JSON.parse(input.games[0].config_snapshot_json || "{}");
  const comparisonMetrics =
    comparison.metrics && typeof comparison.metrics === "object"
      ? (comparison.metrics as Record<string, unknown>)
      : {};

  const metrics: ExperimentMetric[] = METRIC_ENTRIES.map(
    ([key, [label, description, percent]]) => ({
      id: key,
      name: label,
      description,
      percent,
      conditions: Object.fromEntries(
        conditions.map((c) => [c, poolMetric(conditionRows[c], key)])
      ),
      paired: (comparisonMetrics[key] as ExperimentMetric["paired"]) ?? null,
    })
  );

  const conditionSummaries: ConditionSummary[] = conditions.map((c) => {
    const firstRow = conditionRows[c][0] ?? {};
    const features: Record<string, boolean | null> = {};
    for (const name of FEATURE_ORDER) {
      const rawVal = firstRow[`${name}_enabled`];
      features[name] = rawVal ? rawVal.toLowerCase() === "true" : null;
    }
    return {
      id: c,
      label: LABELS[c] ?? c.replaceAll("_", " "),
      wins: wins[c] ?? 0,
      features,
    };
  });

  const changed: string[] =
    conditions.length === 2
      ? FEATURE_ORDER.filter(
          (name) =>
            conditionSummaries[0].features[name] !== null &&
            conditionSummaries[1].features[name] !== null &&
            conditionSummaries[0].features[name] !==
              conditionSummaries[1].features[name]
        )
      : [];

  const title =
    changed.length === 1
      ? `${FEATURES[changed[0]]} ablation`
      : conditions.includes("A_full_B")
        ? "Control experiment"
        : "Team comparison";

  const comparisonId =
    (typeof comparison.comparison === "string" && comparison.comparison) ||
    (conditions.length > 1 ? conditions[1] : null);

  const focus = (comparisonId && MATCHUP_MEASURES[comparisonId]) || {
    primary: ["ppp"],
    context: [],
    adaptation: ["ppp"],
    note: "",
  };

  const iarMetric = metrics.find((m) => m.id === "iar")!;

  let totalEvents = 0;
  let totalInvariantViolations = 0;
  let totalCostUsd = 0;
  for (const r of input.games) {
    totalEvents += toFiniteNumber(r.transitions) ?? 0;
    totalInvariantViolations += toFiniteNumber(r.sir_numerator) ?? 0;
    totalCostUsd += toFiniteNumber(r.total_cost_usd) ?? 0;
  }

  let matchedLogsCount = 0;
  for (const g of games) {
    if (g.available) matchedLogsCount += 1;
  }

  const adaptation: AdaptationRow[] = input.adaptation.map((r) => ({
    ...r,
    experiment_id: r.experiment_id,
    comparison: r.comparison,
    metric: r.metric,
    condition: r.condition,
    time_bin: r.time_bin,
    status: r.status,
    rate: toFiniteNumber(r.rate),
    numerator: toFiniteNumber(r.numerator),
    denominator: toFiniteNumber(r.denominator),
  }));

  const overview: ExperimentOverview = {
    experiment_id: experimentId,
    model: input.games[0].model_slug,
    conditions: conditionSummaries,
    study: {
      title,
      baseline,
      comparison: comparisonId,
      changed_features: changed,
      measures: focus,
    },
    validity: {
      sir: poolMetric(input.games, "sir"),
      iar: iarMetric,
    },
    summary: {
      games: games.length,
      complete_games: games.filter((g) => g.complete).length,
      seeds: new Set(games.map((g) => g.seed)).size,
      draws,
      possessions: input.possessions.length,
      events: totalEvents,
      invariant_violations: totalInvariantViolations,
      logged_cost_usd: totalCostUsd,
    },
    games,
    metrics,
    adaptation,
    statistics: {
      baseline: (input.stats.baseline as string | undefined) ?? null,
      bootstrap_replicates:
        (input.stats.bootstrap_replicates as number | undefined) ?? null,
      analysis_seed:
        (input.stats.analysis_seed as number | string | undefined) ?? null,
      model_note: (input.stats.model_note as string | undefined) ?? null,
      possession_model:
        (comparison.possession_model as ExperimentOverview["statistics"]["possession_model"]) ??
        {},
      source_excluded_games: Array.isArray(input.stats.source_excluded_games)
        ? input.stats.source_excluded_games
        : [],
    },
    config,
    sources: {
      results: input.resultsDirName,
      logs_matched: matchedLogsCount,
      export: "export/*.csv",
      stats: "stats.json",
      adaptation: "plots/adaptation.csv",
    },
  };

  if (input.unexportedGames && input.unexportedGames.length > 0) {
    overview.unexported_games = input.unexportedGames;
  }
  if (input.plotsManifest?.plots) {
    overview.plots = input.plotsManifest.plots;
  }

  return overview;
}

