import fs from "node:fs";
import path from "node:path";
import type {
  CatalogData,
  ComparisonsSummary,
  ExperimentOverview,
} from "./types";

const DATA_ROOT = path.join(process.cwd(), "public", "data");

function readJsonFile<T>(relPath: string): T {
  const fullPath = path.join(DATA_ROOT, relPath);
  const raw = fs.readFileSync(fullPath, "utf-8");
  return JSON.parse(raw) as T;
}

export function getCatalogData(): CatalogData {
  return readJsonFile<CatalogData>("catalog.json");
}

export function getComparisonsData(): ComparisonsSummary {
  return readJsonFile<ComparisonsSummary>("comparisons.json");
}

export function getExperimentOverview(experimentId: string): ExperimentOverview {
  return readJsonFile<ExperimentOverview>(`experiments/${experimentId}.json`);
}

export function getAllExperimentOverviews(): Record<string, ExperimentOverview> {
  const catalog = getCatalogData();
  const out: Record<string, ExperimentOverview> = {};
  for (const exp of catalog.experiments) {
    out[exp.id] = getExperimentOverview(exp.id);
  }
  return out;
}

