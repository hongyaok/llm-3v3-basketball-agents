import React, { Suspense } from "react";
import { notFound } from "next/navigation";
import { getCatalogData, getExperimentOverview } from "@/lib/data-server";
import { ReplayView } from "@/components/ReplayView";

export const dynamic = "error";
export const dynamicParams = false;

export function generateStaticParams() {
  const catalog = getCatalogData();
  return catalog.experiments.map((exp) => ({
    experimentId: exp.id,
  }));
}

export default async function DefaultReplayPage({
  params,
}: {
  params: Promise<{ experimentId: string }>;
}) {
  const { experimentId } = await params;
  let experiment;
  try {
    experiment = getExperimentOverview(experimentId);
  } catch {
    notFound();
  }

  const firstGame =
    experiment.games.find((g) => g.available) ||
    experiment.unexported_games?.find((g) => g.available);

  if (!firstGame) {
    return (
      <div className="loading-state">
        <h1>No local game logs are available for replay.</h1>
      </div>
    );
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
      <ReplayView experiment={experiment} gameId={firstGame.id} />
    </Suspense>
  );
}

