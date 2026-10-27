import { describe, expect, it } from "vitest";
import { zipSync, strToU8 } from "fflate";
import { poolMetric } from "../../scripts/lib/pool";
import { buildExperimentOverview } from "../../scripts/lib/overview";
import { buildGameReplay } from "../../scripts/lib/replay";
import {
  buildCatalogOptions,
  buildComparisonsSummary,
  type CatalogEntry,
} from "../../scripts/lib/comparisons";
import { parseCsvText } from "../../scripts/lib/csv";
import {
  readZipEntries,
  shouldSkipZipEntry,
  validateSafeEntryPath,
} from "../../scripts/lib/zip";
import { fmt, sign, clock, title } from "../../src/lib/format";
import {
  describeShotEvent,
  eventActor,
  eventCues,
  eventTitle,
} from "../../src/lib/replay-logic";
import type { GameReplay } from "../../src/lib/types";

function makeFixtureExperiment() {
  const games = [
    {
      experiment_id: "study",
      game_id: "game-1",
      seed: "101",
      first_possession: "B",
      team_A_condition: "A_full",
      team_B_condition: "B_no_comm",
      game_complete: "True",
      final_score_A: "2",
      final_score_B: "1",
      transitions: "1",
      sir_numerator: "0",
      sir_denominator: "1",
      sir_rate: "0",
      sir_status: "ok",
      total_cost_usd: "0",
      model_slug: "test-model",
      source: "/unavailable/remote/game-1.jsonl",
      config_snapshot_json: "{}",
    },
  ];
  const teams = [
    {
      game_id: "game-1",
      condition: "A_full",
      ppp_numerator: "2",
      ppp_denominator: "2",
      ppp_rate: "1",
      ppp_status: "ok",
      maar_status: "ok",
      comms_enabled: "True",
      captain_enabled: "True",
      memory_write_enabled: "True",
    },
    {
      game_id: "game-1",
      condition: "B_no_comm",
      ppp_numerator: "1",
      ppp_denominator: "2",
      ppp_rate: "0.5",
      ppp_status: "ok",
      maar_status: "not_applicable",
      comms_enabled: "False",
      captain_enabled: "True",
      memory_write_enabled: "True",
    },
  ];
  const possessions = [
    {
      game_id: "game-1",
      possession_id: "p0001",
      start_event_idx: "1",
    },
  ];
  const records = [
    {
      record_type: "game_start",
      game_id: "game-1",
      seed: 101,
      team_conditions: { A: "A_full", B: "B_no_comm" },
      coordination: { A: { comms: true }, B: { comms: false } },
      first_possession: "B",
      initial_state: { score: { A: 0, B: 0 } },
    },
    {
      record_type: "decision",
      event_idx: 1,
      player: "B1",
      team: "B",
      parsed_output: { action: "SHOOT", rationale: "A recorded rationale" },
      executed_action: "HOLD",
      invalid_reason: "ILLEGAL_POSSESSION",
    },
    {
      record_type: "message",
      event_idx: 1,
      sender: "A1",
      team: "A",
      text: "<script>not executable</script>",
      delivered_at: 2,
      suppressed: false,
    },
    {
      record_type: "resolution",
      event_idx: 1,
      shots: null,
      scoring_events: [{ team: "A", points: 2 }],
    },
    {
      record_type: "state",
      event_idx: 1,
      state: { score: { A: 2, B: 1 } },
    },
    {
      record_type: "game_end",
      final_score: { A: 2, B: 1 },
    },
  ];
  const jsonlText = records.map((r) => JSON.stringify(r)).join("\n");
  return { games, teams, possessions, records, jsonlText };
}

describe("pipeline unit tests (ported from test_dashboard.py)", () => {
  it("pool uses counts and preserves unavailable status", () => {
    const rows = [
      {
        ppp_numerator: "1",
        ppp_denominator: "2",
        ppp_rate: ".5",
        ppp_status: "ok",
      },
      {
        ppp_numerator: "9",
        ppp_denominator: "10",
        ppp_rate: ".9",
        ppp_status: "ok",
      },
      {
        ppp_numerator: "100",
        ppp_denominator: "100",
        ppp_rate: "",
        ppp_status: "insufficient_evidence",
      },
    ];
    const metric = poolMetric(rows, "ppp");
    expect(metric.rate).toBeCloseTo(10 / 12, 10);
    expect(metric.rate).not.toBeCloseTo(0.7, 5);
    expect(metric.status).toBe("partial");
    expect(metric.games).toBe(2);

    const unavailable = poolMetric([{ maar_status: "not_applicable" }], "maar");
    expect(unavailable.rate).toBeNull();
    expect(unavailable.status).toBe("not_applicable");
  });

  it("overview matches local logs and condition identity", () => {
    const { games, teams, possessions } = makeFixtureExperiment();
    const overview = buildExperimentOverview({
      resultsDirName: "study",
      games,
      teams,
      possessions,
      stats: {},
      adaptation: [],
      availableLogGameIds: new Set(["game-1"]),
    });
    expect(overview.summary.games).toBe(1);
    expect(overview.games[0].available).toBe(true);
    expect(overview.games[0].winner).toBe("A_full");
    expect(overview.conditions[0].wins).toBe(1);
    expect(overview.conditions[1].features.comms).toBe(false);
    expect(overview.validity.sir.rate).toBe(0);
    expect(overview.validity.sir.denominator).toBe(1);
    expect(overview.study.measures.primary).toEqual(["ppp", "maar"]);
    expect(overview.study.measures.context).toEqual(["ccar"]);
    expect(JSON.stringify(overview)).not.toContain("/unavailable/remote");
    expect(overview.metrics[1].conditions.B_no_comm.rate).toBeNull();
  });

  it("replay keeps initial and post event states and message timing", () => {
    const { games, possessions, jsonlText } = makeFixtureExperiment();
    const replay = buildGameReplay({
      gameId: "game-1",
      jsonlText,
      exportedGameRow: games[0],
      exportedPossessions: possessions,
    });
    expect(replay.frames.map((f) => f.event_idx)).toEqual([0, 1]);
    expect(replay.frames[0].state.score).toEqual({ A: 0, B: 0 });
    const event = replay.frames[1];
    expect(event.state.score).toEqual({ A: 2, B: 1 });
    expect(event.messages[0].delivered_at).toBe(2);
    expect(event.decisions[0].proposed_action).toBe("SHOOT");
    expect(event.decisions[0].executed_action).toBe("HOLD");
    expect(event.decisions[0].rationale).toBe("A recorded rationale");
    expect(event.resolution?.shots).toBeNull();
    expect(replay.warnings).toEqual([]);
  });

  it("replay reports bad records and does not invent missing states", () => {
    const { games, possessions, records } = makeFixtureExperiment();
    const withoutState = records
      .filter((r) => r.record_type !== "state")
      .map((r) => JSON.stringify(r))
      .join("\n");
    expect(() =>
      buildGameReplay({
        gameId: "game-1",
        jsonlText: withoutState,
        exportedGameRow: games[0],
        exportedPossessions: possessions,
      })
    ).toThrow(/missing state at event 1/);

    expect(() =>
      buildGameReplay({
        gameId: "game-1",
        jsonlText: '{"invalid":',
        fileName: "game-1.jsonl",
        exportedGameRow: games[0],
        exportedPossessions: possessions,
      })
    ).toThrow(/game-1\.jsonl:1/);
  });

  it("catalog discovers and routes captain and memory ablations", () => {
    function makeAblationEntry(
      experimentId: string,
      comparison: string,
      disabledFeature: "captain" | "memory_write"
    ): CatalogEntry {
      const games = [
        {
          experiment_id: experimentId,
          game_id: `${experimentId}_game`,
          seed: "101",
          first_possession: "A",
          team_A_condition: "A_full",
          team_B_condition: comparison,
          game_complete: "True",
          final_score_A: "2",
          final_score_B: "1",
          transitions: "1",
          sir_numerator: "0",
          sir_denominator: "1",
          sir_rate: "0",
          sir_status: "ok",
          total_cost_usd: "0",
          model_slug: "test-model",
          config_snapshot_json: "{}",
        },
      ];
      const teams = ["A_full", comparison].map((condition) => ({
        game_id: `${experimentId}_game`,
        condition,
        ppp_numerator: "2",
        ppp_denominator: "2",
        ppp_rate: "1",
        ppp_status: "ok",
        comms_enabled: "True",
        captain_enabled: String(
          condition === "A_full" || disabledFeature !== "captain"
        ),
        memory_write_enabled: String(
          condition === "A_full" || disabledFeature !== "memory_write"
        ),
      }));
      const possessions = [
        { game_id: `${experimentId}_game`, possession_id: "p0001" },
      ];
      const stats = {
        baseline: "A_full",
        results: [
          {
            experiment_id: experimentId,
            comparison,
            metrics: {
              ppp: {
                status: "ok",
                effect_mean: disabledFeature === "captain" ? 0.1 : 0.2,
                bootstrap_95_ci: [-0.1, 0.3],
                n_seeds: 1,
                wilcoxon: { p_value: 0.5 },
              },
            },
          },
        ],
      };
      const overview = buildExperimentOverview({
        resultsDirName: experimentId,
        games,
        teams,
        possessions,
        stats,
        adaptation: [],
        availableLogGameIds: new Set(),
      });
      return {
        overview,
        hasStats: true,
        hasAdaptation: false,
        logsMatched: 0,
      };
    }

    const entries: Record<string, CatalogEntry> = {
      abl_captain_v1: makeAblationEntry(
        "abl_captain_v1",
        "C_no_captain",
        "captain"
      ),
    };
    const opts1 = buildCatalogOptions(entries);
    expect(opts1.experiments[0].title).toBe("Captain ablation");
    const captain = entries.abl_captain_v1.overview;
    expect(captain.conditions[1].label).toBe("No captain");
    expect(captain.conditions[1].features.captain).toBe(false);
    expect(captain.study.comparison).toBe("C_no_captain");
    expect(captain.study.measures.primary).toEqual(["ppp", "ccar"]);
    expect(captain.study.measures.adaptation).toEqual(["ppp"]);

    entries.abl_memory_v1 = makeAblationEntry(
      "abl_memory_v1",
      "D_read_only",
      "memory_write"
    );
    const opts2 = buildCatalogOptions(entries);
    expect(opts2.experiments).toHaveLength(2);
    const memory = entries.abl_memory_v1.overview;
    expect(memory.study.title).toBe("Memory updates ablation");
    expect(memory.conditions[1].features.memory_write).toBe(false);
    expect(memory.study.measures.primary).toEqual(["ppp", "maur", "cssr"]);
    expect(memory.study.measures.adaptation).toEqual(["maur", "cssr", "ppp"]);

    const summaries = Object.fromEntries(
      buildComparisonsSummary(entries).experiments.map((r) => [
        r.experiment_id,
        r,
      ])
    );
    expect(Object.keys(summaries).sort()).toEqual([
      "abl_captain_v1",
      "abl_memory_v1",
    ]);
    expect(summaries.abl_captain_v1.primary_metrics[0].paired?.effect_mean).toBe(
      0.1
    );
    expect(summaries.abl_memory_v1.primary_metrics[0].paired?.effect_mean).toBe(
      0.2
    );
    expect(summaries.abl_captain_v1.validity.sir.rate).toBe(0);
    expect(summaries.abl_captain_v1.primary_metrics.map((m) => m.id)).toEqual([
      "ppp",
      "ccar",
    ]);
    expect(summaries.abl_memory_v1.primary_metrics.map((m) => m.id)).toEqual([
      "ppp",
      "maur",
      "cssr",
    ]);
  });

  it("handles zip entries with directory data, __MACOSX, .DS_Store, BOM CSVs, and rejects path traversal", () => {
    const zipped = zipSync({
      "dir_with_data/": strToU8("non-empty directory payload"),
      "__MACOSX/._file.txt": strToU8("junk"),
      "dir_with_data/.DS_Store": strToU8("junk"),
      "dir_with_data/data.csv": strToU8("\uFEFFcol1,col2\nval1,val2\n"),
    });
    const entries = readZipEntries(zipped);
    expect(Object.keys(entries)).toEqual(["dir_with_data/data.csv"]);
    const csvRows = parseCsvText(
      Buffer.from(entries["dir_with_data/data.csv"]).toString("utf-8")
    );
    expect(csvRows).toEqual([{ col1: "val1", col2: "val2" }]);

    expect(() => validateSafeEntryPath("../evil.txt")).toThrow(/traversal/);
    expect(() => validateSafeEntryPath("/etc/passwd")).toThrow(/absolute/);
    expect(shouldSkipZipEntry("some/folder/")).toBe(true);
  });

  it("formatters match app.js behavior", () => {
    expect(fmt(1.2345, 2)).toBe("1.23");
    expect(fmt(null)).toBe("—");
    expect(sign(0.1234, 3)).toBe("+0.123");
    expect(sign(-0.1234, 3)).toBe("−0.123");
    expect(sign(0, 3)).toBe("0.000");
    expect(clock(600)).toBe("10:00");
    expect(clock(65)).toBe("1:05");
    expect(title("WIN_SCORE")).toBe("Win score");
  });

  it("describes made shots, missed shots, and rebounds for replay animation", () => {
    const mockReplay: GameReplay = {
      id: "test-game",
      seed: 101,
      conditions: { A: "A_full", B: "C_no_captain" },
      coordination: {},
      first_possession: "A",
      court: { width_m: 15, depth_m: 11, cell_m: 1, basket: [7, 1] },
      end: null,
      warnings: [],
      possessions: [],
      frames: [
        {
          event_idx: 0,
          state: {
            event_idx: 0,
            game_clock_s: 600,
            shot_clock_s: 12,
            score: { A: 0, B: 0 },
            team_fouls: { A: 0, B: 0 },
            offense: "A",
            players: {
              A1: { id: "A1", team: "A", pos: [7, 8], has_ball: true },
              B1: { id: "B1", team: "B", pos: [7, 6] },
            },
            ball: { status: "HELD", pos: [7, 8], holder: "A1" },
          },
          decisions: [],
          messages: [],
          captain_calls: [],
          possessions_ended: [],
        },
        {
          event_idx: 1,
          state: {
            event_idx: 1,
            game_clock_s: 598,
            shot_clock_s: 12,
            score: { A: 1, B: 0 },
            team_fouls: { A: 0, B: 0 },
            offense: "B",
            players: {
              A1: { id: "A1", team: "A", pos: [7, 5] },
              B1: { id: "B1", team: "B", pos: [7, 9], has_ball: true },
            },
            ball: { status: "HELD", pos: [7, 9], holder: "B1" },
          },
          decisions: [],
          messages: [],
          captain_calls: [],
          possessions_ended: [],
          resolution: {
            record_type: "resolution",
            event_idx: 1,
            actions: { A1: "SHOOT", B1: "CONTEST" },
            shots: [{ team: "A", shooter: "A1", made: true }],
            scoring_events: [{ team: "A", points: 1, source: "FIELD_GOAL" }],
          },
        },
        {
          event_idx: 2,
          state: {
            event_idx: 2,
            game_clock_s: 595,
            shot_clock_s: 9,
            score: { A: 1, B: 0 },
            team_fouls: { A: 0, B: 0 },
            offense: "B",
            players: {
              A1: { id: "A1", team: "A", pos: [7, 4] },
              B1: { id: "B1", team: "B", pos: [11, 7] },
            },
            ball: { status: "LOOSE", pos: [11, 7], holder: null },
          },
          decisions: [],
          messages: [],
          captain_calls: [],
          possessions_ended: [],
          resolution: {
            record_type: "resolution",
            event_idx: 2,
            actions: { A1: "CONTEST", B1: "SHOOT" },
            shots: [{ team: "B", shooter: "B1", made: false }],
            scoring_events: [],
          },
        },
        {
          event_idx: 3,
          state: {
            event_idx: 3,
            game_clock_s: 594,
            shot_clock_s: 12,
            score: { A: 1, B: 0 },
            team_fouls: { A: 0, B: 0 },
            offense: "A",
            players: {
              A1: { id: "A1", team: "A", pos: [6, 3], has_ball: true },
              B1: { id: "B1", team: "B", pos: [9, 5] },
            },
            ball: { status: "HELD", pos: [6, 3], holder: "A1" },
          },
          decisions: [],
          messages: [],
          captain_calls: [],
          possessions_ended: [],
          resolution: {
            record_type: "resolution",
            event_idx: 3,
            actions: { A1: "BOX_OUT", B1: "BOX_OUT" },
            scoring_events: [],
          },
        },
      ],
    };

    const scoreDesc = describeShotEvent(mockReplay, 1);
    expect(scoreDesc?.kind).toBe("score");
    expect(scoreDesc?.message).toBe("A1 scored 1 point");
    expect(eventActor(mockReplay, mockReplay.frames[1], 1)).toBe("A1");
    expect(eventCues(mockReplay, mockReplay.frames[1], 1)[0]).toEqual({
      kind: "score",
      text: "A1 scored 1 point",
    });
    expect(eventTitle(mockReplay.frames[1], mockReplay.frames, 1)).toBe(
      "A1 scored 1 point"
    );

    const missDesc = describeShotEvent(mockReplay, 2);
    expect(missDesc?.kind).toBe("miss");
    expect(missDesc?.message).toBe("B1 Missed");
    expect(missDesc?.nextRebounder).toBe("A1");
    expect(eventActor(mockReplay, mockReplay.frames[2], 2)).toBe("B1");
    expect(eventCues(mockReplay, mockReplay.frames[2], 2)[0]).toEqual({
      kind: "miss",
      text: "B1 Missed",
    });
    expect(eventTitle(mockReplay.frames[2], mockReplay.frames, 2)).toBe(
      "B1 Missed"
    );

    const rebDesc = describeShotEvent(mockReplay, 3);
    expect(rebDesc?.kind).toBe("rebound");
    expect(rebDesc?.message).toBe("A1 Rebound");
    expect(rebDesc?.isOffensiveRebound).toBe(false);
    expect(eventActor(mockReplay, mockReplay.frames[3], 3)).toBe("A1");
    expect(eventCues(mockReplay, mockReplay.frames[3], 3)[0]).toEqual({
      kind: "rebound",
      text: "A1 Rebound",
    });
    expect(eventTitle(mockReplay.frames[3], mockReplay.frames, 3)).toBe(
      "A1 Rebound"
    );

    mockReplay.frames.push({
      event_idx: 4,
      state: {
        event_idx: 4,
        game_clock_s: 590,
        shot_clock_s: 12,
        score: { A: 1, B: 0 },
        team_fouls: { A: 0, B: 0 },
        offense: "A",
        players: {
          A1: { id: "A1", team: "A", pos: [6, 5], has_ball: true },
          B1: { id: "B1", team: "B", pos: [6, 5] },
        },
        ball: { status: "HELD", pos: [6, 5], holder: "A1" },
      },
      decisions: [],
      messages: [],
      captain_calls: [],
      possessions_ended: [],
      resolution: {
        record_type: "resolution",
        event_idx: 4,
        actions: { A1: "DEFEND", B1: "PASS" },
        turnovers: [{ team: "B", player: "B1", reason: "STEAL" }],
      },
    });

    const tovDesc = describeShotEvent(mockReplay, 4);
    expect(tovDesc?.kind).toBe("turnover");
    expect(tovDesc?.message).toBe("Turnover: A1 stole ball from B1");
    expect(eventCues(mockReplay, mockReplay.frames[4], 4)[0]).toEqual({
      kind: "turnover",
      text: "Turnover: A1 stole ball from B1",
    });
    expect(eventTitle(mockReplay.frames[4], mockReplay.frames, 4)).toBe(
      "Turnover: A1 stole ball from B1"
    );
  });
});

