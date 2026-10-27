import React from "react";
import Link from "next/link";
import { ArrowIcon } from "@/components/SharedUi";

export default function NotFound() {
  return (
    <div className="not-found-card card">
      <span className="eyebrow">RULE VIOLATION · 404 OUT OF BOUNDS</span>
      <div className="not-found-code mono">00.0s</div>
      <h1>Shot clock expired. Route out of bounds.</h1>
      <p>
        The requested experiment, seed, or possession coordinate lies outside
        the 15×11m half-court boundaries. Choose a destination below to resume
        observation.
      </p>
      <div className="not-found-actions">
        <Link className="button primary" href="/">
          Return to research hub <ArrowIcon />
        </Link>
        <Link className="button" href="/comparisons">
          Compare all 3 ablations
        </Link>
        <Link className="button" href="/experiments/abl_comms_v1/replay">
          Watch court replay
        </Link>
      </div>
    </div>
  );
}
