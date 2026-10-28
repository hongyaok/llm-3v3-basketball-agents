import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { parseCsvText } from "./lib/csv";
import { INCLUDED_SEEDS } from "./lib/constants";
import { assertNoNonFiniteNumbers } from "./lib/numbers";
import { buildExperimentOverview } from "./lib/overview";
import {
  buildCatalogOptions,
  buildComparisonsSummary,
  type CatalogEntry,
} from "./lib/comparisons";
import { buildGameReplay, buildUnexportedGameSummary } from "./lib/replay";
import { decodeUtf8, readZipEntries, type ZipEntryMap } from "./lib/zip";
import type { GameSummaryRow } from "../src/lib/types";

const PIPELINE_VERSION = "1.1.0";
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_RESULTS_DIR = path.join(FRONTEND_ROOT, "results");
const OUTPUT_DATA_DIR = path.join(FRONTEND_ROOT, "public", "data");

function sha256File(filePath: string): string {
  const hash = crypto.createHash("sha256");
  hash.update(fs.readFileSync(filePath));
  return hash.digest("hex");
}

function writeJsonSafe(filePath: string, value: unknown): void {
  assertNoNonFiniteNumbers(value);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(value), "utf-8");
}

function resolveResultsDir(): string {
  if (process.env.RESULTS_DIR) {
    return path.resolve(process.env.RESULTS_DIR);
  }
  if (
    fs.existsSync(DEFAULT_RESULTS_DIR) &&
    fs.readdirSync(DEFAULT_RESULTS_DIR).some((f) => f.endsWith(".zip"))
  ) {
    return DEFAULT_RESULTS_DIR;
  }
  throw new Error(
    `No results .zip archives found in ${DEFAULT_RESULTS_DIR}. Run 'npm run sync-results' first.`
  );
}

function ensureStaticArchHtml(): void {
  const dstDir = path.join(FRONTEND_ROOT, "public", "static");
  const dstFile = path.join(dstDir, "system_architecture.html");
  const srcFile = path.resolve(FRONTEND_ROOT, "..", "system_architecture.html");
  if (fs.existsSync(srcFile)) {
    fs.mkdirSync(dstDir, { recursive: true });
    fs.copyFileSync(srcFile, dstFile);
  } else if (!fs.existsSync(dstFile)) {
    throw new Error(
      `Missing architecture HTML at ${dstFile} and ${srcFile}`
    );
  }
}

export function buildDataFromDirectory(
  resultsDir: string,
  outputDir: string,
  options: { force?: boolean } = {}
): void {
  const zipNames = fs
    .readdirSync(resultsDir)
    .filter((f) => f.endsWith(".zip"))
    .sort();
  if (zipNames.length === 0) {
    throw new Error(`No .zip archives found in ${resultsDir}`);
  }

  const checksumsPath = path.join(resultsDir, "CHECKSUMS.sha256");
  const currentChecksums = zipNames
    .map((name) => `${sha256File(path.join(resultsDir, name))}  ${name}`)
    .join("\n");

  if (fs.existsSync(checksumsPath)) {
    const expected = fs.readFileSync(checksumsPath, "utf-8").replace(/\r\n/g, "\n").trim();
    if (expected !== currentChecksums.trim()) {
      const msg = `CHECKSUMS.sha256 mismatch in ${resultsDir}`;
      if (process.env.CI || process.env.VERCEL) {
        throw new Error(msg);
      } else {
        console.warn(`Warning: ${msg}`);
      }
    }
  }

  const stampPath = path.join(outputDir, ".stamp");
  const stampValue = `${PIPELINE_VERSION}\n${currentChecksums}\n`;
  if (
    !options.force &&
    fs.existsSync(stampPath) &&
    fs.existsSync(path.join(outputDir, "catalog.json")) &&
    fs.readFileSync(stampPath, "utf-8") === stampValue
  ) {
    console.log("public/data is up-to-date (stamp matched).");
    return;
  }

  // Locate summary zip vs log zips
  let summaryZipName: string | null = null;
  let summaryEntries: ZipEntryMap | null = null;

  const logEntriesByGameId = new Map<
    string,
    { zipName: string; entryName: string; bytes: Uint8Array }
  >();

  for (const zipName of zipNames) {
    const zipPath = path.join(resultsDir, zipName);
    const entries = readZipEntries(zipPath);
    const hasExportGamesCsv = Object.keys(entries).some((k) =>
      k.endsWith("/export/games.csv") || k === "export/games.csv"
    );

    if (hasExportGamesCsv) {
      if (summaryZipName !== null) {
        throw new Error(
          `Multiple summary archives found: ${summaryZipName} and ${zipName}`
        );
      }
      summaryZipName = zipName;
      summaryEntries = entries;
      continue;
    }

    for (const [entryName, bytes] of Object.entries(entries)) {
      if (!entryName.endsWith(".jsonl")) continue;
      const base = path.posix.basename(entryName);
      const gameId = base.slice(0, -".jsonl".length);
      if (logEntriesByGameId.has(gameId)) {
        const prev = logEntriesByGameId.get(gameId)!;
        throw new Error(
          `Multiple logs found for ${gameId}: ${prev.zipName}:${prev.entryName} and ${zipName}:${entryName}`
        );
      }
      logEntriesByGameId.set(gameId, { zipName, entryName, bytes });
    }
  }

  if (!summaryZipName || !summaryEntries) {
    throw new Error(
      `No summary archive containing export/games.csv found in ${resultsDir}`
    );
  }

  // Discover experiment prefixes inside summaryEntries
  const gamesCsvKeys = Object.keys(summaryEntries)
    .filter((k) => k.endsWith("/export/games.csv") || k === "export/games.csv")
    .sort();

  const availableLogGameIds = new Set(logEntriesByGameId.keys());
  const exportedGameIdsAll = new Set<string>();
  const catalogEntries: Record<string, CatalogEntry> = {};

  fs.rmSync(outputDir, { recursive: true, force: true });
  fs.mkdirSync(outputDir, { recursive: true });

  for (const gamesKey of gamesCsvKeys) {
    const prefix = gamesKey.slice(0, -"export/games.csv".length); // e.g. "interim_31games/abl_comms_v1/"
    const teamsKey = `${prefix}export/teams.csv`;
    const possessionsKey = `${prefix}export/possessions.csv`;
    const statsKey = `${prefix}stats.json`;
    const adaptationKey = `${prefix}plots/adaptation.csv`;
    const plotsManifestKey = `${prefix}plots/manifest.json`;

    if (!summaryEntries[teamsKey] || !summaryEntries[possessionsKey]) {
      continue;
    }

    const gamesCsvText = decodeUtf8(summaryEntries[gamesKey]);
    const teamsCsvText = decodeUtf8(summaryEntries[teamsKey]);
    const possessionsCsvText = decodeUtf8(summaryEntries[possessionsKey]);

    const gamesRows = parseCsvText(gamesCsvText);
    const teamsRows = parseCsvText(teamsCsvText);
    const possessionsRows = parseCsvText(possessionsCsvText);

    const statsObj = summaryEntries[statsKey]
      ? (JSON.parse(decodeUtf8(summaryEntries[statsKey])) as Record<
          string,
          unknown
        >)
      : {};
    const adaptationRows = summaryEntries[adaptationKey]
      ? parseCsvText(decodeUtf8(summaryEntries[adaptationKey]))
      : [];
    const plotsManifest = summaryEntries[plotsManifestKey]
      ? (JSON.parse(decodeUtf8(summaryEntries[plotsManifestKey])) as {
          plots?: Array<{
            comparison: string;
            experiment_id: string;
            file: string;
            metric: string;
          }>;
        })
      : undefined;

    const experimentId = gamesRows[0]?.experiment_id;
    if (!experimentId) {
      throw new Error(`Missing experiment_id in ${gamesKey}`);
    }

    const resultsDirName =
      prefix.replace(/\/$/, "").split("/").pop() || experimentId;

    const exportedByGameId = new Map<string, Record<string, string>>();
    for (const row of gamesRows) {
      if (!INCLUDED_SEEDS.has(String(row.seed))) {
        throw new Error(
          `Unexpected seed ${row.seed} for ${row.game_id} in ${gamesKey}; allowed seeds: ${[...INCLUDED_SEEDS].join(", ")}`
        );
      }
      exportedByGameId.set(row.game_id, row);
      exportedGameIdsAll.add(row.game_id);
    }

    // Find any log-only games that belong to this experiment (by prefix `${experimentId}_`)
    const unexportedGameSummaries: GameSummaryRow[] = [];
    for (const [gameId, logEntry] of logEntriesByGameId.entries()) {
      if (exportedByGameId.has(gameId)) continue;
      if (gameId.startsWith(`${experimentId}_`)) {
        const jsonlText = decodeUtf8(logEntry.bytes);
        const replay = buildGameReplay({
          gameId,
          jsonlText,
          fileName: path.posix.basename(logEntry.entryName),
          exportedGameRow: null,
          exportedPossessions: [],
        });
        writeJsonSafe(
          path.join(outputDir, "replays", experimentId, `${gameId}.json`),
          replay
        );
        unexportedGameSummaries.push(buildUnexportedGameSummary(replay));
      }
    }

    unexportedGameSummaries.sort((a, b) => {
      const seedDiff = Number.parseInt(a.seed, 10) - Number.parseInt(b.seed, 10);
      if (seedDiff !== 0) return seedDiff;
      return a.first_possession.localeCompare(b.first_possession);
    });

    const overview = buildExperimentOverview({
      resultsDirName,
      games: gamesRows,
      teams: teamsRows,
      possessions: possessionsRows,
      stats: statsObj,
      adaptation: adaptationRows,
      availableLogGameIds,
      plotsManifest,
      unexportedGames: unexportedGameSummaries,
    });

    if (catalogEntries[experimentId]) {
      throw new Error(`Duplicate experiment ID: ${experimentId}`);
    }

    catalogEntries[experimentId] = {
      overview,
      hasStats: Object.keys(statsObj).length > 0,
      hasAdaptation: adaptationRows.length > 0,
      logsMatched: overview.sources.logs_matched,
    };

    // Write overview JSON
    writeJsonSafe(
      path.join(outputDir, "experiments", `${experimentId}.json`),
      overview
    );

    // Write replays for exported games
    for (const row of gamesRows) {
      const gameId = row.game_id;
      const logEntry = logEntriesByGameId.get(gameId);
      if (!logEntry) continue;
      const jsonlText = decodeUtf8(logEntry.bytes);
      const replay = buildGameReplay({
        gameId,
        jsonlText,
        fileName: path.posix.basename(logEntry.entryName),
        exportedGameRow: row,
        exportedPossessions: possessionsRows,
      });
      writeJsonSafe(
        path.join(outputDir, "replays", experimentId, `${gameId}.json`),
        replay
      );
    }

    // Write downloads
    const dlDir = path.join(outputDir, "downloads", experimentId);
    fs.mkdirSync(dlDir, { recursive: true });
    fs.writeFileSync(path.join(dlDir, "games.csv"), summaryEntries[gamesKey]);
    fs.writeFileSync(path.join(dlDir, "teams.csv"), summaryEntries[teamsKey]);
    fs.writeFileSync(
      path.join(dlDir, "possessions.csv"),
      summaryEntries[possessionsKey]
    );
    writeJsonSafe(path.join(dlDir, "stats.json"), statsObj);

    // Copy plots (*.png and manifest.json)
    const plotsPrefix = `${prefix}plots/`;
    const plotsOutDir = path.join(outputDir, "plots", experimentId);
    fs.mkdirSync(plotsOutDir, { recursive: true });
    for (const [entryKey, bytes] of Object.entries(summaryEntries)) {
      if (entryKey.startsWith(plotsPrefix)) {
        const relName = entryKey.slice(plotsPrefix.length);
        if (relName && !relName.includes("/")) {
          fs.writeFileSync(path.join(plotsOutDir, relName), bytes);
        }
      }
    }
  }

  const catalog = buildCatalogOptions(catalogEntries);
  const unexportedLogs = [...logEntriesByGameId.keys()]
    .filter((id) => !exportedGameIdsAll.has(id))
    .sort();

  catalog.dataset = {
    source_zip: summaryZipName,
    exported_games: exportedGameIdsAll.size,
    total_logs: logEntriesByGameId.size,
    unexported_logs: unexportedLogs,
  };

  const comparisons = buildComparisonsSummary(catalogEntries);

  writeJsonSafe(path.join(outputDir, "catalog.json"), catalog);
  writeJsonSafe(path.join(outputDir, "comparisons.json"), comparisons);
  fs.writeFileSync(stampPath, stampValue, "utf-8");

  console.log(
    `Built data for ${catalog.experiments.length} experiment(s): ${exportedGameIdsAll.size} exported games + ${unexportedLogs.length} log-only game(s) (${unexportedLogs.join(", ") || "none"}).`
  );
}

if (require.main === module) {
  const force = process.argv.includes("--force");
  ensureStaticArchHtml();
  const resultsDir = resolveResultsDir();
  buildDataFromDirectory(resultsDir, OUTPUT_DATA_DIR, { force });
}

