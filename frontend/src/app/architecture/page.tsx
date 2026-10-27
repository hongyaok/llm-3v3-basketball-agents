import React from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { ArrowIcon, PageHeading } from "@/components/SharedUi";

export const dynamic = "error";

export const metadata: Metadata = {
  title: "System Architecture — 6-Stage Decision & Simulation Loop",
  description:
    "Interactive diagram of the 6-stage LLM 3x3 basketball simulation loop: Observation Builder, LLM Decision Layer, Comms/Captain Store, Resolution Engine, RAG Referee, and State/Memory Update.",
};

export default function ArchitecturePage() {
  return (
    <>
      <PageHeading
        eyebrow="SYSTEM ARCHITECTURE · PROPOSAL §4"
        name="Six agents propose. One engine decides."
        description="Interactive diagram of the LLM 3×3 basketball simulation loop. Click a player to inspect its decision path and attributes, or step through the 6 stages."
        actions={
          <>
            <Link className="button" href="/experiments/abl_comms_v1/replay">
              See architecture in court replay <ArrowIcon />
            </Link>
            <a
              className="button primary"
              href="/static/system_architecture.html"
              target="_blank"
              rel="noopener"
            >
              Open full screen ↗
            </a>
          </>
        }
      />

      <div className="arch-stage-strip">
        <div className="arch-stage-pill">
          <span className="mono">STAGE 01</span>
          <strong>Game State &amp; Observation Builder</strong>
        </div>
        <div className="arch-stage-pill">
          <span className="mono">STAGE 02</span>
          <strong>LLM Actions, Comms &amp; Memory Proposals</strong>
        </div>
        <div className="arch-stage-pill">
          <span className="mono">STAGE 03</span>
          <strong>Store Teammate Messages &amp; Captain Call</strong>
        </div>
        <div className="arch-stage-pill">
          <span className="mono">STAGE 04</span>
          <strong>Non-LLM Physical &amp; Logistic Resolution</strong>
        </div>
        <div className="arch-stage-pill">
          <span className="mono">STAGE 05</span>
          <strong>FIBA 3×3 Rulebook RAG Referee</strong>
        </div>
        <div className="arch-stage-pill">
          <span className="mono">STAGE 06</span>
          <strong>State &amp; Validated Memory Update</strong>
        </div>
      </div>

      <section className="arch-frame-card">
        <iframe
          className="arch-iframe"
          src="/static/system_architecture.html"
          title="LLM 3v3 basketball system architecture"
        />
      </section>
      <p className="chart-note" style={{ marginTop: "12px" }}>
        Tip: Click inside the diagram and press <strong>→</strong> (Right Arrow)
        to step through the 6 stages, or click any player node (
        <strong>A1–A3</strong>, <strong>B1–B3</strong>) to inspect its private
        observation, memory, and profile.
      </p>
    </>
  );
}
