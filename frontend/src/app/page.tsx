import React from "react";
import {
  getAllExperimentOverviews,
  getCatalogData,
  getComparisonsData,
} from "@/lib/data-server";
import { LandingClient } from "@/components/LandingClient";

export const dynamic = "error";

export default function LandingPage() {
  const catalog = getCatalogData();
  const comparisons = getComparisonsData();
  const overviews = getAllExperimentOverviews();

  return (
    <LandingClient
      catalog={catalog}
      comparisons={comparisons}
      overviews={overviews}
    />
  );
}
