export interface TeamBoxScore {
  passes: number;
  assists: number;
  rebounds: number;
  turnovers: number;
}

export interface GameBoxScore {
  A: TeamBoxScore;
  B: TeamBoxScore;
}

export interface ConditionBoxScore extends TeamBoxScore {
  games: number;
  passes_per_game: number | null;
  assists_per_game: number | null;
  rebounds_per_game: number | null;
  turnovers_per_game: number | null;
}

const TEAM_IDS = new Set(["A", "B"]);

function emptyTeamBox(): TeamBoxScore {
  return { passes: 0, assists: 0, rebounds: 0, turnovers: 0 };
}

function teamOf(playerId: unknown): "A" | "B" | null {
  if (typeof playerId !== "string" || playerId.length === 0) return null;
  const team = playerId[0];
  return TEAM_IDS.has(team) ? (team as "A" | "B") : null;
}

/**
 * Per-game counting stats that the export CSVs do not carry.
 *
 * Definitions, all validated against the graded result archives:
 * - pass: an executed `PASS` action, credited to the acting player's team.
 * - assist: a made field goal in the resolution immediately following a
 *   teammate's `PASS` (the engine never writes `assist_by`).
 * - rebound: a `LOOSE -> HELD` ball transition, credited to the player who
 *   gathers it. Consecutive loose states count once.
 * - turnover: one `turnovers` entry, credited to the team that lost the ball.
 */
export function computeGameBoxScore(jsonlText: string): GameBoxScore {
  const box: GameBoxScore = { A: emptyTeamBox(), B: emptyTeamBox() };
  let previousPassed: Record<"A" | "B", boolean> = { A: false, B: false };
  let previousBallStatus: string | null = null;

  for (const line of jsonlText.split("\n")) {
    if (!line.trim()) continue;
    let record: Record<string, unknown>;
    try {
      record = JSON.parse(line) as Record<string, unknown>;
    } catch {
      continue;
    }

    const recordType = record.record_type;

    if (recordType === "resolution") {
      const passed: Record<"A" | "B", boolean> = { A: false, B: false };
      const actions = record.actions as Record<string, string> | undefined;
      for (const [playerId, action] of Object.entries(actions ?? {})) {
        const team = teamOf(playerId);
        if (!team || action !== "PASS") continue;
        box[team].passes += 1;
        passed[team] = true;
      }

      const shots = record.shots as
        | Array<{ team?: string; made?: boolean }>
        | null
        | undefined;
      for (const shot of shots ?? []) {
        const team = teamOf(shot?.team);
        if (!team || !shot?.made) continue;
        if (previousPassed[team]) box[team].assists += 1;
      }

      const turnovers = record.turnovers as
        | Array<{ team?: string }>
        | null
        | undefined;
      for (const turnover of turnovers ?? []) {
        const team = teamOf(turnover?.team);
        if (team) box[team].turnovers += 1;
      }

      previousPassed = passed;
      continue;
    }

    if (recordType === "state") {
      const state = record.state as
        | { ball?: { status?: string; holder?: string | null } }
        | undefined;
      const ball = state?.ball;
      if (!ball) continue;
      if (previousBallStatus === "LOOSE" && ball.status === "HELD") {
        const team = teamOf(ball.holder);
        if (team) box[team].rebounds += 1;
      }
      previousBallStatus = ball.status ?? null;
    }
  }

  return box;
}

/** Mean per-game counts for one condition. */
export function averageTeamBox(rows: TeamBoxScore[]): ConditionBoxScore {
  const games = rows.length;
  const total = rows.reduce<TeamBoxScore>(
    (acc, row) => ({
      passes: acc.passes + row.passes,
      assists: acc.assists + row.assists,
      rebounds: acc.rebounds + row.rebounds,
      turnovers: acc.turnovers + row.turnovers,
    }),
    emptyTeamBox()
  );
  const per = (value: number) => (games ? value / games : null);
  return {
    games,
    ...total,
    passes_per_game: per(total.passes),
    assists_per_game: per(total.assists),
    rebounds_per_game: per(total.rebounds),
    turnovers_per_game: per(total.turnovers),
  };
}
