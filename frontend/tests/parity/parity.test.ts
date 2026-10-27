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
      source_zip: "interim_31games.zip",
      exported_games: 31,
      total_logs: 32,
      unexported_logs: ["abl_comms_v1_s106_B"],
    });
  });

  it("matches comparison_summary() across all 3 experiments", () => {
    const comparisons = loadJson(path.join(DATA_DIR, "comparisons.json"));
    assertDeepEqualWithFloatTolerance(comparisons, golden.comparisons);
  });

  for (const expId of ["abl_captain_v1", "abl_comms_v1", "abl_memory_v1"]) {
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
    ["abl_comms_v1", ["abl_comms_v1", "abl_comms_v1_s101_A"]],
    ["abl_comms_v1_s106_A", ["abl_comms_v1", "abl_comms_v1_s106_A"]],
    ["abl_captain_v1", ["abl_captain_v1", "abl_captain_v1_s101_A"]],
    ["abl_memory_v1", ["abl_memory_v1", "abl_memory_v1_s101_A"]],
  ] as const) {
    it(`matches replay() for ${expAndGame[1]}`, () => {
      const [expId, gameId] = expAndGame;
      const actual = loadJson(
        path.join(DATA_DIR, "replays", expId, `${gameId}.json`)
      );
      assertDeepEqualWithFloatTolerance(actual, golden.sample_replays[key]);
    });
  }

  it("generates replay for log-only game abl_comms_v1_s106_B with warning", () => {
    const s106B = loadJson(
      path.join(DATA_DIR, "replays", "abl_comms_v1", "abl_comms_v1_s106_B.json")
    );
    expect(s106B.id).toBe("abl_comms_v1_s106_B");
    expect(s106B.unexported).toBe(true);
    expect(s106B.frames.length).toBeGreaterThan(300);
    expect(s106B.end.final_score).toEqual({ A: 22, B: 9 });
    expect(s106B.warnings[0]).toMatch(/Log-only game/);
  });
});

