export type TeamId = "A" | "B";

export interface PooledMetric {
  numerator: number;
  denominator: number;
  rate: number | null;
  status: string;
  status_counts: Record<string, number>;
  games: number;
}

export interface PairedSeedEntry {
  seed: string;
  difference: number;
  [key: string]: unknown;
}

export interface WilcoxonResult {
  p_value?: number | null;
  statistic?: number | null;
  [key: string]: unknown;
}

export interface PairedMetricEstimate {
  status?: string;
  effect_mean?: number | null;
  bootstrap_95_ci?: [number, number] | null;
  wilcoxon?: WilcoxonResult | null;
  n_seeds?: number;
  n_games?: number;
  paired_seeds?: PairedSeedEntry[];
  excluded_seeds?: unknown[];
  [key: string]: unknown;
}

export interface ExperimentMetric {
  id: string;
  name: string;
  description: string;
  percent: boolean;
  conditions: Record<string, PooledMetric>;
  paired?: PairedMetricEstimate | null;
}

export interface ConditionSummary {
  id: string;
  label: string;
  wins: number;
  features: Record<string, boolean | null>;
}

export interface StudyMeasures {
  primary: string[];
  context: string[];
  adaptation: string[];
  note: string;
}

export interface StudyInfo {
  title: string;
  baseline: string;
  comparison: string | null;
  changed_features: string[];
  measures: StudyMeasures;
}

export interface GameSummaryRow {
  id: string;
  seed: string;
  first_possession: string;
  score: { A: number | null; B: number | null };
  conditions: { A: string; B: string };
  winner: string | null;
  complete: boolean;
  events: number | null;
  end_reason: string | null;
  validation: string | null;
  available: boolean;
  ppp: Record<string, number | null>;
  unexported?: boolean;
}

export interface AdaptationRow {
  experiment_id: string;
  comparison: string;
  metric: string;
  condition: string;
  time_bin: string;
  numerator: number | null;
  denominator: number | null;
  rate: number | null;
  status: string;
  [key: string]: unknown;
}

export interface ExperimentOverview {
  experiment_id: string;
  model: string;
  conditions: ConditionSummary[];
  study: StudyInfo;
  validity: {
    sir: PooledMetric;
    iar: ExperimentMetric;
  };
  summary: {
    games: number;
    complete_games: number;
    seeds: number;
    draws: number;
    possessions: number;
    events: number;
    invariant_violations: number;
    logged_cost_usd: number;
  };
  games: GameSummaryRow[];
  unexported_games?: GameSummaryRow[];
  metrics: ExperimentMetric[];
  adaptation: AdaptationRow[];
  statistics: {
    baseline?: string | null;
    bootstrap_replicates?: number | null;
    analysis_seed?: number | string | null;
    model_note?: string | null;
    possession_model: Record<string, { status?: string; [key: string]: unknown }>;
    source_excluded_games: unknown[];
  };
  config: {
    llm_players?: { model?: string; temperature?: number; [key: string]: unknown };
    llm_referee?: { model?: string; temperature?: number; top_k_rules?: number; [key: string]: unknown };
    memory_settings?: { backend?: string; [key: string]: unknown };
    simulation?: { court?: Record<string, unknown>; [key: string]: unknown };
    [key: string]: unknown;
  };
  sources: {
    results: string;
    logs_matched: number;
    export: string;
    stats: string;
    adaptation: string;
  };
  plots?: Array<{
    comparison: string;
    experiment_id: string;
    file: string;
    metric: string;
  }>;
}

export interface CatalogExperimentOption {
  id: string;
  title: string;
  conditions: string[];
  games: number;
  unexported_games?: number;
}

export interface CatalogData {
  default: string;
  experiments: CatalogExperimentOption[];
  dataset?: {
    source_zip: string;
    exported_games: number;
    total_logs: number;
    unexported_logs: string[];
  };
}

export interface ComparisonPrimaryMetric {
  id: string;
  name: string;
  percent: boolean;
  conditions: Record<string, PooledMetric>;
  paired: {
    status?: string;
    effect_mean?: number | null;
    bootstrap_95_ci?: [number, number] | null;
    p_value?: number | null;
    n_seeds?: number;
  } | null;
}

export interface ComparisonExperimentRow {
  experiment_id: string;
  title: string;
  conditions: ConditionSummary[];
  summary: ExperimentOverview["summary"];
  primary_metrics: ComparisonPrimaryMetric[];
  logs_matched: number;
  validity: ExperimentOverview["validity"];
  measure_note: string;
  has_stats: boolean;
  has_adaptation: boolean;
}

export interface ComparisonsSummary {
  experiments: ComparisonExperimentRow[];
}

export interface PlayerState {
  id: string;
  team: TeamId;
  pos: [number, number];
  prev_pos?: [number, number];
  movement?: string;
  speed?: string;
  has_ball?: boolean;
  fatigue?: number;
}

export interface FrameState {
  event_idx: number;
  game_clock_s: number;
  shot_clock_s: number;
  score: { A: number; B: number };
  team_fouls: { A: number; B: number };
  offense: TeamId;
  needs_clear?: boolean;
  phase?: string;
  players: Record<string, PlayerState>;
  ball: {
    status: string;
    pos: [number, number];
    holder?: string | null;
  };
  matchups?: Record<string, string>;
}

export interface ReplayDecision {
  player: string | null;
  team: TeamId | null;
  executed_action: string | null;
  executed_target: string | null;
  invalid_reason: string | null;
  parse_ok: boolean | null;
  memory_ref: string | null;
  rationale: string | null;
  proposed_action: string | null;
}

export interface ReplayMessage {
  record_type: "message";
  event_idx: number;
  team: TeamId;
  sender: string;
  channel?: string;
  kind?: string;
  text: string;
  directive?: { to?: string; [key: string]: unknown } | null;
  cs?: string | null;
  suppressed?: boolean;
  delivered_at?: number | null;
}

export interface ReplayCaptainCall {
  record_type: "captain_call";
  event_idx: number;
  team: TeamId;
  maintain?: boolean;
  tactic?: string | null;
  cs?: string | null;
  directives?: Array<{ to?: string; act?: string; target?: string | null }>;
}

export interface ReplayPossessionEnd {
  record_type: "possession_end";
  possession_id: string;
  team: TeamId;
  points: number;
  points_by_team?: { A: number; B: number };
  end_reason: string;
  start_event_idx: number;
  end_event_idx: number;
}

export interface ReplayShot {
  team: TeamId;
  shooter: string;
  made: boolean;
  assist_by?: string | null;
  screen_id?: string | null;
  [key: string]: unknown;
}

export interface ReplayResolution {
  record_type: "resolution";
  event_idx: number;
  actions?: Record<string, string>;
  action_targets?: Record<string, string | null>;
  outcomes?: Record<string, unknown>;
  involved_opponents?: Record<string, string[]>;
  model_terms?: Record<string, unknown>;
  rng_draws?: Record<string, unknown>;
  possession_before?: { possession_id: string; team: TeamId } | null;
  possession_after?: { possession_id: string; team: TeamId } | null;
  scoring_events?: Array<{ team: TeamId; points: number; source: string; [key: string]: unknown }>;
  possession_changes?: Array<Record<string, unknown>>;
  shots?: ReplayShot[] | null;
  screens?: unknown;
  turnovers?: Array<{ team: TeamId; player?: string; reason: string; [key: string]: unknown }>;
  game_over?: boolean;
  game_end_reason?: string | null;
}

export interface ReplayReferee {
  record_type: "referee";
  event_idx: number;
  retrieved_chunk_ids?: string[];
  decision?: {
    call?: string | null;
    offender?: string | null;
    fouled_player?: string | null;
    foul_type?: string | null;
    violation_type?: string | null;
    rule_ids_cited?: string[];
  } | null;
  rejected_output?: unknown;
  rejection_reason?: string | null;
  raw_output?: string | null;
  failure_code?: string | null;
  parse_error?: string | null;
  [key: string]: unknown;
}

export interface ReplayFrame {
  event_idx: number;
  state: FrameState;
  decisions: ReplayDecision[];
  messages: ReplayMessage[];
  captain_calls: ReplayCaptainCall[];
  possessions_ended: ReplayPossessionEnd[];
  resolution?: ReplayResolution;
  referee?: ReplayReferee;
}

export interface ReplayPossessionRow {
  possession_id: string;
  physical_team: string;
  points: string | number;
  start_event_idx: string | number;
  end_event_idx?: string | number;
  [key: string]: unknown;
}

export interface GameReplay {
  id: string;
  seed: number | string;
  conditions: { A: string; B: string };
  coordination: Record<string, { comms?: boolean; captain?: boolean; memory_write?: boolean }>;
  first_possession: string;
  court: {
    width_m?: number;
    depth_m?: number;
    cell_m?: number;
    basket?: [number, number];
    arc_radius_m?: number;
    [key: string]: unknown;
  };
  frames: ReplayFrame[];
  end: {
    record_type: "game_end";
    last_event_idx: number;
    end_reason: string;
    final_score: { A: number; B: number };
    ot_flag?: boolean;
    totals?: Record<string, unknown>;
    total_cost_usd?: number;
  } | null;
  warnings: string[];
  possessions: ReplayPossessionRow[];
  unexported?: boolean;
}

