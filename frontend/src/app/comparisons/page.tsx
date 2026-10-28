import React from "react";
import type { Metadata } from "next";
import { getComparisonsData } from "@/lib/data-server";
import {
  getAllBoxScores,
  getAllExperimentOverviews,
} from "@/lib/data-server";
import { ComparisonsSection } from "@/components/ComparisonsSection";
import { CrossExperimentTables } from "@/components/CrossExperimentTables";

export const dynamic = "error";

export const metadata: Metadata = {
  title: "All Experiments — Side-by-Side Ablation Comparisons",
  description:
    "Compare Teammate Communication, Captain Tactical Calls, and Shared Team Memory Updates across 31 exported games and paired seeds.",
};

export default function DedicatedComparisonsPage() {
  const data = getComparisonsData();
  const overviews = getAllExperimentOverviews();
  const boxScores = getAllBoxScores();
  return (
    <>
      <ComparisonsSection data={data} isEmbedded={false} />
      <CrossExperimentTables overviews={overviews} boxScores={boxScores} />
    </>
  );
}

