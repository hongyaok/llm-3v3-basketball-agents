import React, { Suspense } from "react";
import { notFound } from "next/navigation";
import { getCatalogData, getExperimentOverview } from "@/lib/data-server";
import { ReplayView } from "@/components/ReplayView";

export const dynamic = "error";
export const dynamicParams = false;

export function generateStaticParams() {
  const catalog = getCatalogData();
  const params: Array<{ experimentId: string; gameId: string }> = [];
  for (const exp of catalog.experiments) {
    const overview = getExperimentOverview(exp.id);
    for (const g of overview.games) {
      if (g.available) {
        params.push({ experimentId: exp.id, gameId: g.id });
      }
    }
    for (const g of overview.unexported_games ?? []) {
      if (g.available) {
        params.push({ experimentId: exp.id, gameId: g.id });
      }
    }
  }
  return params;
}

export default async function GameReplayPage({
  params,
}: {
  params: Promise<{ experimentId: string; gameId: string }>;
}) {
  const { experimentId, gameId } = await params;
  let experiment;
  try {
    experiment = getExperimentOverview(experimentId);
  } catch {
    notFound();
  }

  const allGames = [
    ...experiment.games,
    ...(experiment.unexported_games ?? []),
  ];
  const exists = allGames.some((g) => g.id === gameId && g.available);
  if (!exists) {
    notFound();
  }

  return (
    <Suspense
      fallback={
        <div className="loading-state">
          <span className="spinner" />
          <h1>Loading the court</h1>
          <p>Reading the recorded states and event evidence.</p>
        </div>
      }
    >
      <ReplayView experiment={experiment} gameId={gameId} />
    </Suspense>
  );
}

