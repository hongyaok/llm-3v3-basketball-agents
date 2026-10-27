import React, { Suspense } from "react";
import { notFound } from "next/navigation";
import { getCatalogData, getExperimentOverview } from "@/lib/data-server";
import { DownloadIcon, PageHeading } from "@/components/SharedUi";
import { GameLibraryClient } from "@/components/GameLibraryClient";

export const dynamic = "error";
export const dynamicParams = false;

export function generateStaticParams() {
  const catalog = getCatalogData();
  return catalog.experiments.map((exp) => ({
    experimentId: exp.id,
  }));
}

export default async function GameLibraryPage({
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

  return (
    <>
      <PageHeading
        eyebrow="RECORDED GAMES"
        name="Every game. Every decision."
        description="Compare matched seeds, inspect a close finish, or follow a game from the opening possession."
        actions={
          <a
            className="button"
            href={`/data/downloads/${encodeURIComponent(
              experiment.experiment_id
            )}/games.csv`}
            download={`${experiment.experiment_id}_games.csv`}
          >
            <DownloadIcon /> Export games
          </a>
        }
      />
      <Suspense
        fallback={
          <div className="loading-state">
            <span className="spinner" />
            <p>Loading game library…</p>
          </div>
        }
      >
        <GameLibraryClient experiment={experiment} />
      </Suspense>
    </>
  );
}

