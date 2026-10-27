import React from "react";
import type { Metadata, Viewport } from "next";
import "@/styles/globals.css";
import "@/styles/replay.css";
import { switzer, zodiak, jetBrainsMono } from "./fonts";
import { getAllExperimentOverviews, getCatalogData } from "@/lib/data-server";
import { AppShell } from "@/components/AppShell";

export const metadata: Metadata = {
  title: {
    default: "Courtside — Multi-Agent 3v3 Basketball Research Observatory",
    template: "%s · Courtside",
  },
  description:
    "DSA4213 research testbed investigating how teammate communication, captain-led tactical calls, and shared team memory shape LLM agent cooperation and adaptation in competitive FIBA 3x3 basketball.",
  openGraph: {
    title: "Courtside — Multi-Agent 3v3 Basketball Research Observatory",
    description:
      "Controlled ablation experiments, possession-level court replays, and 6-stage simulation architecture for competitive 3v3 basketball LLM agents.",
    type: "website",
  },
};

export const viewport: Viewport = {
  themeColor: "#10211c",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const catalog = getCatalogData();
  const overviews = getAllExperimentOverviews();

  return (
    <html
      lang="en"
      className={`${switzer.variable} ${zodiak.variable} ${jetBrainsMono.variable}`}
    >
      <body>
        <AppShell catalog={catalog} overviews={overviews}>
          {children}
        </AppShell>
      </body>
    </html>
  );
}
