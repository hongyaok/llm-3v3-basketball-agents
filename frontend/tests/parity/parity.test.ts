import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const FRONTEND_ROOT = path.resolve(__dirname, "../..");
const GOLDEN_PATH = path.join(__dirname, "golden.json");
const DATA_DIR = path.join(FRONTEND_ROOT, "public", "data");

function loadJson(filePath: string) {
  return JSON.parse(fs.readFileSync(filePath, "utf-8"));
}

function stripFrontendExtensions(overview: Record<string, unknown>) {
  const clone = { ...overview };
  delete clone.unexported_games;
  delete clone.plots;
  return clone;
}

function assertDeepEqualWithFloatTolerance(
  actual: unknown,
  expected: unknown,
  tolerance = 1e-12,
  currentPath = "$"
): void {
  if (typeof actual === "number" && typeof expected === "number") {
    if (Math.abs(actual - expected) > tolerance) {
      throw new Error(
        `Float mismatch at ${currentPath}: actual=${actual}, expected=${expected}`
      );
    }
    return;
  }
  if (Array.isArray(actual) && Array.isArray(expected)) {
    if (actual.length !== expected.length) {
      throw new Error(
        `Array length mismatch at ${currentPath}: actual=${actual.length}, expected=${expected.length}`
      );
    }
    for (let i = 0; i < actual.length; i++) {
      assertDeepEqualWithFloatTolerance(
        actual[i],
        expected[i],
        tolerance,
        `${currentPath}[${i}]`
      );
    }
    return;
  }
  if (
    actual &&
    expected &&
    typeof actual === "object" &&
    typeof expected === "object" &&
    !Array.isArray(actual) &&
    !Array.isArray(expected)
  ) {
    const aKeys = Object.keys(actual as Record<string, unknown>).sort();
    const eKeys = Object.keys(expected as Record<string, unknown>).sort();
    expect(aKeys, `Object keys at ${currentPath}`).toEqual(eKeys);
    for (const k of aKeys) {
      assertDeepEqualWithFloatTolerance(
        (actual as Record<string, unknown>)[k],
        (expected as Record<string, unknown>)[k],
        tolerance,
        `${currentPath}.${k}`
      );
    }
    return;
  }
  expect(actual, `Value at ${currentPath}`).toEqual(expected);
}

describe("Python DashboardData / DashboardCatalog parity gate", () => {
  const golden = loadJson(GOLDEN_PATH);

  it("matches catalog options()", () => {
    const catalog = loadJson(path.join(DATA_DIR, "catalog.json"));
    const strippedCatalog = {
      default: catalog.default,
      experiments: catalog.experiments.map(
        ({ id, title, conditions, games }: Record<string, unknown>) => ({
          id,
          title,
          conditions,
          games,
        })
      ),
    };
    assertDeepEqualWithFloatTolerance(strippedCatalog, golden.options);
    expect(catalog.dataset).toEqual({
      source_zip: "seeds_106_110.zip",
      exported_games: 36,
      total_logs: 36,
      unexported_logs: [],
    });
  });

  it("matches comparison_summary() across all experiments", () => {
    const comparisons = loadJson(path.join(DATA_DIR, "comparisons.json"));
    assertDeepEqualWithFloatTolerance(comparisons, golden.comparisons);
  });

  for (const expId of ["abl_captain_v1", "abl_comms_v1", "abl_memory_v1", "pilot_v1"]) {
    it(`matches overview() for ${expId}`, () => {
      const actual = loadJson(
        path.join(DATA_DIR, "experiments", `${expId}.json`)
      );
      assertDeepEqualWithFloatTolerance(
        stripFrontendExtensions(actual),
        golden.overviews[expId]
      );
    });
  }

  for (const [key, expAndGame] of [
    ["abl_comms_v1", ["abl_comms_v1", "abl_comms_v1_s106_A"]],
    ["abl_comms_v1_s106_B", ["abl_comms_v1", "abl_comms_v1_s106_B"]],
    ["abl_captain_v1", ["abl_captain_v1", "abl_captain_v1_s106_A"]],
    ["abl_memory_v1", ["abl_memory_v1", "abl_memory_v1_s106_A"]],
    ["pilot_v1", ["pilot_v1", "pilot_v1_s101_A"]],
  ] as const) {
    it(`matches replay() for ${expAndGame[1]}`, () => {
      const [expId, gameId] = expAndGame;
      const actual = loadJson(
        path.join(DATA_DIR, "replays", expId, `${gameId}.json`)
      );
      assertDeepEqualWithFloatTolerance(actual, golden.sample_replays[key]);
    });
  }

  it("includes seeds 106-110 for ablations and seeds 101-103 for pilot_v1", () => {
    const s106B = loadJson(
      path.join(DATA_DIR, "replays", "abl_comms_v1", "abl_comms_v1_s106_B.json")
    );
    expect(s106B.id).toBe("abl_comms_v1_s106_B");
    expect(s106B.unexported).toBeUndefined();
    expect(s106B.frames.length).toBeGreaterThan(300);
    expect(s106B.end.final_score).toEqual({ A: 22, B: 9 });

    for (const expId of ["abl_captain_v1", "abl_comms_v1", "abl_memory_v1"]) {
      const ov = loadJson(path.join(DATA_DIR, "experiments", `${expId}.json`));
      const seeds = new Set(ov.games.map((g: { seed: string }) => String(g.seed)));
      expect([...seeds].sort()).toEqual(["106", "107", "108", "109", "110"]);
      expect(ov.games.length).toBe(10);
    }

    const pilotOv = loadJson(path.join(DATA_DIR, "experiments", "pilot_v1.json"));
    const pilotSeeds = new Set(
      pilotOv.games.map((g: { seed: string }) => String(g.seed))
    );
    expect([...pilotSeeds].sort()).toEqual(["101", "102", "103"]);
    expect(pilotOv.games.length).toBe(6);
    expect(pilotOv.study.title).toBe("Control experiment");
  });
});

