import { describe, expect, it } from "vitest";
import {
  averageTeamBox,
  computeGameBoxScore,
} from "../../scripts/lib/boxscore";

function jsonl(records: unknown[]): string {
  return records.map((r) => JSON.stringify(r)).join("\n");
}

function state(status: string, holder: string | null): unknown {
  return {
    record_type: "state",
    state: { ball: { status, holder } },
  };
}

function resolution(partial: Record<string, unknown>): unknown {
  return {
    record_type: "resolution",
    actions: {},
    action_targets: {},
    shots: null,
    turnovers: null,
    ...partial,
  };
}

describe("computeGameBoxScore", () => {
  it("counts passes, assists, rebounds and turnovers per team", () => {
    const box = computeGameBoxScore(
      jsonl([
        state("HELD", "A1"),
        resolution({
          actions: { A1: "PASS", A2: "CUT", B1: "DEFEND" },
          action_targets: { A1: "A2" },
        }),
        resolution({
          actions: { A2: "SHOOT", B1: "CONTEST" },
          shots: [{ team: "A", shooter: "A2", made: true }],
        }),
        state("LOOSE", null),
        state("LOOSE", null),
        state("HELD", "B3"),
        resolution({
          actions: { B3: "PASS" },
          turnovers: [
            { team: "B", reason: "STEAL", player: "B3" },
          ],
        }),
      ])
    );

    expect(box.A).toEqual({
      passes: 1,
      assists: 1,
      rebounds: 0,
      turnovers: 0,
    });
    expect(box.B).toEqual({
      passes: 1,
      assists: 0,
      // consecutive loose states count once, credited to the gatherer
      rebounds: 1,
      turnovers: 1,
    });
  });

  it("only credits an assist when the pass is in the preceding event", () => {
    const box = computeGameBoxScore(
      jsonl([
        resolution({ actions: { A1: "PASS" } }),
        resolution({ actions: { A2: "MOVE" } }),
        resolution({
          actions: { A3: "SHOOT" },
          shots: [{ team: "A", shooter: "A3", made: true }],
        }),
        resolution({
          actions: { B1: "SHOOT" },
          shots: [{ team: "B", shooter: "B1", made: false }],
        }),
      ])
    );

    expect(box.A.assists).toBe(0);
    expect(box.A.passes).toBe(1);
    // a missed shot is not an assist
    expect(box.B.assists).toBe(0);
  });

  it("ignores malformed lines instead of throwing", () => {
    const box = computeGameBoxScore(
      [
        '{"record_type":"resolution","actions":{"A1":"PASS"}}',
        "not json",
        "",
        '{"record_type":"state","state":{"ball":{"status":"LOOSE"}}}',
      ].join("\n")
    );
    expect(box.A.passes).toBe(1);
    expect(box.A.turnovers).toBe(0);
  });
});

describe("averageTeamBox", () => {
  it("averages per game and reports null with no games", () => {
    const averaged = averageTeamBox([
      { passes: 10, assists: 2, rebounds: 4, turnovers: 6 },
      { passes: 20, assists: 4, rebounds: 8, turnovers: 2 },
    ]);
    expect(averaged.games).toBe(2);
    expect(averaged.passes_per_game).toBe(15);
    expect(averaged.assists_per_game).toBe(3);
    expect(averaged.rebounds_per_game).toBe(6);
    expect(averaged.turnovers_per_game).toBe(4);

    const empty = averageTeamBox([]);
    expect(empty.games).toBe(0);
    expect(empty.passes_per_game).toBeNull();
  });
});
