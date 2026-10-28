import type {
  FrameState,
  GameReplay,
  GameSummaryRow,
  ReplayCaptainCall,
  ReplayDecision,
  ReplayFrame,
  ReplayMessage,
  ReplayPossessionEnd,
  ReplayPossessionRow,
  ReplayReferee,
  ReplayResolution,
} from "../../src/lib/types";
import { toFiniteNumber } from "./numbers";

export interface BuildReplayOptions {
  gameId: string;
  jsonlText: string;
  fileName?: string;
  exportedGameRow?: Record<string, string> | null;
  exportedPossessions?: Array<Record<string, string>>;
}

/**
 * Faithful port of `DashboardData.replay(game_id)` in `src/bball3x3/display/dashboard.py`.
 * Also supports log-only (unexported) games when `exportedGameRow` is null/omitted.
 */
export function buildGameReplay(options: BuildReplayOptions): GameReplay {
  const {
    gameId,
    jsonlText,
    fileName = `${gameId}.jsonl`,
    exportedGameRow = null,
    exportedPossessions = [],
  } = options;

  const events = new Map<
    number,
    {
      state?: FrameState;
      decisions: ReplayDecision[];
      messages: ReplayMessage[];
      captain_calls: ReplayCaptainCall[];
      possessions_ended: ReplayPossessionEnd[];
      resolution?: ReplayResolution;
      referee?: ReplayReferee;
    }
  >();

  const getEventBucket = (eventIdx: number) => {
    let bucket = events.get(eventIdx);
    if (!bucket) {
      bucket = {
        decisions: [],
        messages: [],
        captain_calls: [],
        possessions_ended: [],
      };
      events.set(eventIdx, bucket);
    }
    return bucket;
  };

  let start: Record<string, unknown> | null = null;
  let end: GameReplay["end"] = null;
  const allPossessionsEnded: ReplayPossessionEnd[] = [];

  const lines = jsonlText.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const lineNumber = i + 1;
    const line = lines[i];
    if (!line.trim()) continue;

    let record: Record<string, unknown>;
    try {
      const parsed = JSON.parse(line);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("record must be an object");
      }
      record = parsed as Record<string, unknown>;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      throw new Error(`${fileName}:${lineNumber}: ${message}`);
    }

    const kind = record.record_type;
    if (kind === "game_start") {
      start = record;
      continue;
    }
    if (kind === "game_end") {
      end = record as GameReplay["end"];
      continue;
    }

    const eventIdx = record.event_idx;
    if (typeof eventIdx !== "number" || !Number.isInteger(eventIdx)) {
      continue;
    }

    const frame = getEventBucket(eventIdx);
    if (kind === "state") {
      frame.state = record.state as FrameState;
    } else if (kind === "decision") {
      const parsedOutput =
        record.parsed_output && typeof record.parsed_output === "object"
          ? (record.parsed_output as Record<string, unknown>)
          : {};
      frame.decisions.push({
        player: (record.player as string) ?? null,
        team: (record.team as "A" | "B") ?? null,
        executed_action: (record.executed_action as string) ?? null,
        executed_target: (record.executed_target as string) ?? null,
        invalid_reason: (record.invalid_reason as string) ?? null,
        parse_ok: (record.parse_ok as boolean) ?? null,
        memory_ref: (record.memory_ref as string) ?? null,
        rationale: (parsedOutput.rationale as string) ?? null,
        proposed_action: (parsedOutput.action as string) ?? null,
      });
    } else if (kind === "message") {
      frame.messages.push(record as unknown as ReplayMessage);
    } else if (kind === "captain_call") {
      frame.captain_calls.push(record as unknown as ReplayCaptainCall);
    } else if (kind === "possession_end") {
      const possRecord = record as unknown as ReplayPossessionEnd;
      frame.possessions_ended.push(possRecord);
      allPossessionsEnded.push(possRecord);
    } else if (kind === "resolution") {
      frame.resolution = record as unknown as ReplayResolution;
    } else if (kind === "referee") {
      frame.referee = record as unknown as ReplayReferee;
    }
  }

  if (
    !start ||
    start.game_id !== gameId ||
    !start.initial_state ||
    typeof start.initial_state !== "object"
  ) {
    throw new Error(`${fileName}: missing or mismatched game_start`);
  }

  const frames: ReplayFrame[] = [
    {
      event_idx: 0,
      state: start.initial_state as FrameState,
      decisions: [],
      messages: [],
      captain_calls: [],
      possessions_ended: [],
    },
  ];

  const sortedEventIndices = [...events.keys()].sort((a, b) => a - b);
  for (const eventIdx of sortedEventIndices) {
    const frame = events.get(eventIdx)!;
    if (!frame.state) {
      throw new Error(`${fileName}: missing state at event ${eventIdx}`);
    }
    const builtFrame: ReplayFrame = {
      event_idx: eventIdx,
      state: frame.state,
      decisions: frame.decisions,
      messages: frame.messages,
      captain_calls: frame.captain_calls,
      possessions_ended: frame.possessions_ended,
    };
    if (frame.resolution !== undefined) {
      builtFrame.resolution = frame.resolution;
    }
    if (frame.referee !== undefined) {
      builtFrame.referee = frame.referee;
    }
    frames.push(builtFrame);
  }

  const warnings: string[] = [];
  if (!end) {
    warnings.push("The local log has no game_end record; replay may be incomplete.");
  } else if (exportedGameRow) {
    const exportedScoreA = toFiniteNumber(exportedGameRow.final_score_A);
    const exportedScoreB = toFiniteNumber(exportedGameRow.final_score_B);
    if (
      end.final_score.A !== exportedScoreA ||
      end.final_score.B !== exportedScoreB
    ) {
      warnings.push("Local final score differs from the results export.");
    }
  } else {
    warnings.push(
      "Log-only game: recorded in the run archives, but not included in the interim_31games export tables."
    );
  }

  const configSnapshot =
    start.config_snapshot && typeof start.config_snapshot === "object"
      ? (start.config_snapshot as Record<string, unknown>)
      : {};
  const simulationCfg =
    configSnapshot.simulation && typeof configSnapshot.simulation === "object"
      ? (configSnapshot.simulation as Record<string, unknown>)
      : configSnapshot;
  const court =
    simulationCfg.court && typeof simulationCfg.court === "object"
      ? (simulationCfg.court as GameReplay["court"])
      : {};

  let possessions: ReplayPossessionRow[];
  if (exportedGameRow) {
    possessions = exportedPossessions.filter((r) => r.game_id === gameId) as unknown as ReplayPossessionRow[];
  } else {
    possessions = allPossessionsEnded.map((p) => ({
      possession_id: p.possession_id,
      physical_team: p.team,
      points: String(p.points),
      start_event_idx: String(p.start_event_idx),
      end_event_idx: String(p.end_event_idx),
    }));
  }

  const rawConditions = start.team_conditions as { A: string; B: string };
  const conditions =
    rawConditions.A === rawConditions.B
      ? { A: rawConditions.A, B: `${rawConditions.B}_B` }
      : rawConditions;

  const replay: GameReplay = {
    id: gameId,
    seed: start.seed as number | string,
    conditions,
    coordination: start.coordination as GameReplay["coordination"],
    first_possession: start.first_possession as string,
    court,
    frames,
    end,
    warnings,
    possessions,
  };

  if (!exportedGameRow) {
    replay.unexported = true;
  }

  return replay;
}

/**
 * Build a `GameSummaryRow` for a log-only (unexported) game from its parsed `GameReplay`.
 */
export function buildUnexportedGameSummary(replay: GameReplay): GameSummaryRow {
  const scoreA = replay.end?.final_score?.A ?? null;
  const scoreB = replay.end?.final_score?.B ?? null;
  const complete = Boolean(replay.end);
  let winner: string | null = null;
  if (complete && scoreA !== null && scoreB !== null && scoreA !== scoreB) {
    winner = scoreA > scoreB ? replay.conditions.A : replay.conditions.B;
  }
  return {
    id: replay.id,
    seed: String(replay.seed),
    first_possession: String(replay.first_possession),
    score: { A: scoreA, B: scoreB },
    conditions: replay.conditions,
    winner,
    complete,
    events: replay.end?.last_event_idx ?? replay.frames.length - 1,
    end_reason: replay.end?.end_reason ?? null,
    validation: "log_only",
    available: true,
    ppp: {},
    unexported: true,
  };
}

