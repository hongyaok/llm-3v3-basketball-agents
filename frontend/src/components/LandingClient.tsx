"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type {
  CatalogData,
  ComparisonsSummary,
  ExperimentOverview,
} from "@/lib/types";
import { ArrowIcon } from "@/components/SharedUi";
import { ComparisonsSection } from "@/components/ComparisonsSection";

type TaskId =
  | "overview"
  | "replay"
  | "comparisons"
  | "games"
  | "architecture"
  | "methods";

type LayerId = "llm" | "engine" | "referee";

export function LandingClient({
  catalog,
  comparisons,
  overviews,
}: {
  catalog: CatalogData;
  comparisons: ComparisonsSummary;
  overviews: Record<string, ExperimentOverview>;
}) {
  const router = useRouter();
  const [selectedTask, setSelectedTask] = useState<TaskId>("overview");
  const [selectedExpId, setSelectedExpId] = useState<string>(catalog.default);
  const [activeLayer, setActiveLayer] = useState<LayerId>("llm");

  const activeOverview = overviews[selectedExpId] || overviews[catalog.default];
  const allReplayGames = useMemo(() => {
    const exported = (activeOverview.games || []).filter((g) => g.available);
    const unexported = (activeOverview.unexported_games || []).filter(
      (g) => g.available
    );
    return [...exported, ...unexported];
  }, [activeOverview]);

  const closestGame = useMemo(() => {
    const games = activeOverview.games || [];
    if (!games.length) return null;
    return [...games].sort(
      (a, b) =>
        Math.abs((a.score.A ?? 0) - (a.score.B ?? 0)) -
        Math.abs((b.score.A ?? 0) - (b.score.B ?? 0))
    )[0];
  }, [activeOverview]);

  const [selectedGameId, setSelectedGameId] = useState<string>(
    closestGame?.id || allReplayGames[0]?.id || "abl_comms_v1_s106_A"
  );

  // Keep selectedGameId valid when experiment changes
  const effectiveGameId = useMemo(() => {
    if (allReplayGames.some((g) => g.id === selectedGameId)) {
      return selectedGameId;
    }
    return (
      closestGame?.id ||
      allReplayGames[0]?.id ||
      `${selectedExpId}_s106_A`
    );
  }, [allReplayGames, closestGame, selectedExpId, selectedGameId]);

  const destinationUrl = useMemo(() => {
    switch (selectedTask) {
      case "comparisons":
        return "/comparisons";
      case "overview":
        return `/experiments/${encodeURIComponent(selectedExpId)}`;
      case "replay":
        return `/experiments/${encodeURIComponent(
          selectedExpId
        )}/replay/${encodeURIComponent(effectiveGameId)}`;
      case "games":
        return `/experiments/${encodeURIComponent(selectedExpId)}/games`;
      case "architecture":
        return "/architecture";
      case "methods":
        return `/experiments/${encodeURIComponent(selectedExpId)}/methods`;
    }
  }, [selectedTask, selectedExpId, effectiveGameId]);

  const handleLaunch = (e: React.FormEvent) => {
    e.preventDefault();
    router.push(destinationUrl);
  };

  const totalExportedGames = catalog.dataset?.exported_games ?? 30;
  const totalReplayLogs =
    totalExportedGames +
    Object.values(overviews).reduce(
      (acc, ov) => acc + (ov.unexported_games?.length ?? 0),
      0
    );

  return (
    <div className="landing-page">
      {/* HERO + TACTICAL COMMAND DECK */}
      <section className="landing-hero">
        <div className="landing-hero-grid">
          <div className="landing-hero-copy">
            <div className="landing-meta-strip">
              <span className="meta-chip">DSA4213 · GROUP 16</span>
              <span className="meta-chip">FIBA 3×3 HALF-COURT SIMULATOR</span>
              <span className="meta-chip mono">
                mistral-small-3.2-24b-instruct
              </span>
            </div>

            <h1 className="landing-display-title">
              Multi-agent cooperation &amp; adaptation under a{" "}
              <span className="serif-italic">12-second</span> shot clock.
            </h1>

            <blockquote className="proposal-question">
              <span className="eyebrow">RESEARCH QUESTION · PROPOSAL §1</span>
              <p>
                &ldquo;How do structured teammate communication, captain-led
                tactical calls, and shared team memory affect cooperation and
                adaptation among LLM agents in a competitive 3v3 basketball
                environment?&rdquo;
              </p>
            </blockquote>

            <p className="landing-lead">
              We built a virtual FIBA 3×3 half-court testbed where six
              autonomous LLM player agents compete under partial observability,
              strictly separating high-level natural-language tactical intent
              from a deterministic physical resolution engine and a
              rulebook-grounded RAG referee.
            </p>

            <div className="landing-stats-row">
              <div className="landing-stat">
                <span className="landing-stat-num mono">
                  {catalog.experiments.length}
                </span>
                <span className="landing-stat-label">
                  3 ablation studies + 1 control experiment (Full vs Full)
                </span>
              </div>
              <div className="landing-stat">
                <span className="landing-stat-num mono">
                  {totalExportedGames}
                  {totalReplayLogs > totalExportedGames ? (
                    <small>+{totalReplayLogs - totalExportedGames}</small>
                  ) : null}
                </span>
                <span className="landing-stat-label">
                  {totalReplayLogs > totalExportedGames
                    ? `Exported games + ${totalReplayLogs - totalExportedGames} log-only possession replay`
                    : "Exported games (30 ablation + 6 control)"}
                </span>
              </div>
              <div className="landing-stat">
                <span className="landing-stat-num mono">0.00%</span>
                <span className="landing-stat-label">
                  State Inconsistency Rate (SIR) across 1,683 transitions
                </span>
              </div>
            </div>
          </div>

          {/* RIGHT COLUMN: INTERACTIVE PATH CHOOSER / ROUTER */}
          <div className="command-deck-card">
            <div className="command-deck-head">
              <div>
                <span className="eyebrow">INTERACTIVE NAVIGATION ROUTER</span>
                <h2>What would you like to do?</h2>
                <p>
                  Configure your destination below or select any workflow card
                  to jump straight to the right view.
                </p>
              </div>
              <span className="deck-live-badge mono">READY</span>
            </div>

            <form className="command-launcher" onSubmit={handleLaunch}>
              <div className="launcher-field">
                <label htmlFor="launcher-task">1. Choose your objective</label>
                <select
                  id="launcher-task"
                  value={selectedTask}
                  onChange={(e) => setSelectedTask(e.target.value as TaskId)}
                >
                  <option value="overview">
                    Inspect an experiment overview &amp; paired statistics
                  </option>
                  <option value="replay">
                    Watch an interactive 3v3 half-court game replay
                  </option>
                  <option value="comparisons">
                    Compare all 3 ablation experiments side by side
                  </option>
                  <option value="games">
                    Search &amp; filter the {totalReplayLogs}-game match library
                  </option>
                  <option value="architecture">
                    Explore the 6-stage system &amp; agent architecture
                  </option>
                  <option value="methods">
                    Audit methods, raw CSVs &amp; statistical plots
                  </option>
                </select>
              </div>

              {selectedTask !== "comparisons" &&
              selectedTask !== "architecture" ? (
                <div className="launcher-field">
                  <label htmlFor="launcher-exp">
                    2. Select ablation study
                  </label>
                  <select
                    id="launcher-exp"
                    value={selectedExpId}
                    onChange={(e) => setSelectedExpId(e.target.value)}
                  >
                    {catalog.experiments.map((exp) => (
                      <option key={exp.id} value={exp.id}>
                        {exp.title} ({exp.conditions.join(" vs ")})
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}

              {selectedTask === "replay" ? (
                <div className="launcher-field">
                  <label htmlFor="launcher-game">
                    3. Select match recording
                  </label>
                  <select
                    id="launcher-game"
                    value={effectiveGameId}
                    onChange={(e) => setSelectedGameId(e.target.value)}
                  >
                    {allReplayGames.map((g) => (
                      <option key={g.id} value={g.id}>
                        Seed {g.seed} · {g.id} ({g.score.A ?? 0}–
                        {g.score.B ?? 0}){" "}
                        {g.unexported ? "[Log only]" : ""}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}

              <div className="launcher-footer">
                <div className="launcher-route-preview">
                  <span>Target route</span>
                  <code className="mono">{destinationUrl}</code>
                </div>
                <button type="submit" className="button lime launcher-submit">
                  Go to destination <ArrowIcon />
                </button>
              </div>
            </form>

            <div className="deck-quick-study-bar">
              <span>Active context for cards below:</span>
              <div className="study-pill-group" role="group" aria-label="Active ablation study">
                {catalog.experiments.map((exp) => (
                  <button
                    key={exp.id}
                    type="button"
                    className={`study-pill-btn ${
                      selectedExpId === exp.id ? "active" : ""
                    }`}
                    onClick={() => setSelectedExpId(exp.id)}
                  >
                    {exp.title.replace(" ablation", "")}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* 6 DESTINATION INTENT CARDS */}
        <div className="intent-grid-header">
          <span className="eyebrow">01 · CHOOSE YOUR WORKFLOW</span>
          <p>Direct pathways into every layer of the research observatory</p>
        </div>

        <div className="intent-grid">
          {/* Card 1: Compare All Ablations */}
          <div className="intent-card">
            <div className="intent-card-top">
              <span className="intent-index mono">01 / COMPARE</span>
              <span className="intent-tag">
                {catalog.experiments.length} STUDIES · {totalExportedGames} GAMES
              </span>
            </div>
            <h3>Compare all 3 ablations side by side</h3>
            <p>
              Evaluate pooled Points-Per-Possession (PPP), paired seed bootstrap
              95% confidence intervals, MAAR, CCAR, MAUR, CSSR, and system
              validity across Teams A, B, C, and D.
            </p>
            <div className="intent-quick-links">
              <Link className="intent-primary-cta" href="/comparisons">
                Open side-by-side matrix <ArrowIcon />
              </Link>
              <a className="intent-sub-link" href="#comparisons">
                Jump to summary below ↓
              </a>
            </div>
          </div>

          {/* Card 2: Experiment Overview */}
          <div className="intent-card">
            <div className="intent-card-top">
              <span className="intent-index mono">02 / OVERVIEW</span>
              <span className="intent-tag mono">{selectedExpId}</span>
            </div>
            <h3>Inspect {activeOverview.study.title.toLowerCase()}</h3>
            <p>
              Examine paired seed PPP differentials, game-by-game scoring
              efficiency scatters, win-loss splits, and complete statistical
              tables for{" "}
              <strong>
                {activeOverview.conditions.map((c) => c.label).join(" vs ")}
              </strong>
              .
            </p>
            <div className="intent-chip-row">
              {catalog.experiments.map((exp) => (
                <Link
                  key={exp.id}
                  href={`/experiments/${encodeURIComponent(exp.id)}`}
                  className={`intent-mini-chip ${
                    exp.id === selectedExpId ? "active" : ""
                  }`}
                >
                  {exp.title.replace(" ablation", "")} →
                </Link>
              ))}
            </div>
            <div className="intent-quick-links">
              <Link
                className="intent-primary-cta"
                href={`/experiments/${encodeURIComponent(selectedExpId)}`}
              >
                Open {activeOverview.study.title} <ArrowIcon />
              </Link>
            </div>
          </div>

          {/* Card 3: Court Replay */}
          <div className="intent-card featured-intent">
            <div className="intent-card-top">
              <span className="intent-index mono">03 / COURT REPLAY</span>
              <span className="intent-tag">15×11M HALF-COURT SVG</span>
            </div>
            <h3>Watch possession-by-possession 3v3 replays</h3>
            <p>
              Scrub through every decision tick, inspect each player&apos;s
              structured observation, read live <code>&lt;c&gt;[tactic]</code>{" "}
              captain calls and teammate messages, and audit RAG referee foul
              rulings.
            </p>
            <div className="intent-chip-row">
              {closestGame ? (
                <Link
                  href={`/experiments/${encodeURIComponent(
                    selectedExpId
                  )}/replay/${encodeURIComponent(closestGame.id)}`}
                  className="intent-mini-chip"
                >
                  Closest game (Seed {closestGame.seed}) →
                </Link>
              ) : null}
              <Link
                href="/experiments/abl_comms_v1/replay/abl_comms_v1_s106_B"
                className="intent-mini-chip"
              >
                Seed 106_B →
              </Link>
            </div>
            <div className="intent-quick-links">
              <Link
                className="intent-primary-cta"
                href={`/experiments/${encodeURIComponent(
                  selectedExpId
                )}/replay/${encodeURIComponent(effectiveGameId)}`}
              >
                Launch court replay <ArrowIcon />
              </Link>
            </div>
          </div>

          {/* Card 4: Game Library */}
          <div className="intent-card">
            <div className="intent-card-top">
              <span className="intent-index mono">04 / GAME LIBRARY</span>
              <span className="intent-tag">
                {activeOverview.summary.games +
                  (activeOverview.unexported_games?.length ?? 0)}{" "}
                MATCHES IN STUDY
              </span>
            </div>
            <h3>Browse &amp; filter the match library</h3>
            <p>
              Search all recorded games by seed number, condition assignment, or
              winning team. Compare home/away swaps on matched seeds and jump to
              any game&apos;s replay.
            </p>
            <div className="intent-quick-links">
              <Link
                className="intent-primary-cta"
                href={`/experiments/${encodeURIComponent(selectedExpId)}/games`}
              >
                Browse {activeOverview.study.title} games <ArrowIcon />
              </Link>
            </div>
          </div>

          {/* Card 5: System Architecture */}
          <div className="intent-card">
            <div className="intent-card-top">
              <span className="intent-index mono">05 / ARCHITECTURE</span>
              <span className="intent-tag">6-STAGE TICK PIPELINE</span>
            </div>
            <h3>Explore the interactive system architecture</h3>
            <p>
              Inspect the 6-stage simulation pipeline, click any player node to
              view its 5-module agent internals, and trace how RAG rulebook
              embeddings ground referee foul calls.
            </p>
            <div className="intent-quick-links">
              <Link className="intent-primary-cta" href="/architecture">
                Open system architecture <ArrowIcon />
              </Link>
            </div>
          </div>

          {/* Card 6: Methods & Raw Data */}
          <div className="intent-card">
            <div className="intent-card-top">
              <span className="intent-index mono">06 / METHODS &amp; DATA</span>
              <span className="intent-tag">CSV · JSON · PLOTS</span>
            </div>
            <h3>Audit methodology, raw CSVs &amp; saved figures</h3>
            <p>
              Review formal metric definitions, model &amp; prompt
              configurations, responsible-practice safeguards, and download raw{" "}
              <code>games.csv</code> and <code>possessions.csv</code> tables.
            </p>
            <div className="intent-quick-links">
              <Link
                className="intent-primary-cta"
                href={`/experiments/${encodeURIComponent(
                  selectedExpId
                )}/methods`}
              >
                Open methods &amp; downloads <ArrowIcon />
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* SECTION 02: WHY THIS PROJECT WAS CREATED (PROPOSAL NARRATIVE) */}
      <section className="proposal-section">
        <div className="section-editorial-head">
          <div>
            <span className="eyebrow">
              02 · WHY THIS PROJECT WAS CREATED (DSA4213 PROPOSAL)
            </span>
            <h2>
              Why FIBA 3×3 basketball is a crucible for multi-agent LLM
              coordination.
            </h2>
          </div>
          <p className="editorial-sub">
            From our group proposal: designing an interpretable, rule-enforced
            scenario-analysis testbed for coaches, sports analysts, and
            multi-agent researchers.
          </p>
        </div>

        <div className="proposal-pillars-grid">
          <article className="proposal-pillar">
            <span className="pillar-num mono">MOTIVATION 01</span>
            <h3>Sequential, adversarial &amp; partially observable</h3>
            <p>
              In basketball, a player&apos;s optimal decision depends not only
              on individual attributes (shooting, passing, defense, stamina),
              but on teammate positioning, off-ball cuts, defensive rotations,
              fatigue, and opponent tendencies—without ever seeing the opposing
              team&apos;s private tactical calls or messages.
            </p>
          </article>

          <article className="proposal-pillar">
            <span className="pillar-num mono">MOTIVATION 02</span>
            <h3>FIBA 3×3&apos;s relentless 12-second shot clock</h3>
            <p>
              Played on a single 15×11m half-court with three active players per
              team and no substitutes, FIBA 3×3 forces continuous transitions
              and rapid coordination under a 12-second shot clock. Agents must
              align intentions within a few discrete decision events or risk a
              shot-clock violation.
            </p>
          </article>

          <article className="proposal-pillar">
            <span className="pillar-num mono">MOTIVATION 03</span>
            <h3>Unifying communication, leadership &amp; memory</h3>
            <p>
              Prior multi-agent research studied embodied communication (
              <em>CoELA</em>, Zhang et al., 2024), topology protocols (
              <em>MultiAgentBench</em>, Zhu et al., 2025), opponent modeling (
              <em>EMO</em>, Yu et al., 2025; <em>A-ToM</em>, Mu et al., 2026),
              or football sims without messaging (<em>sfas</em>, Xu, 2026) in
              isolation. We isolate communication, captain hierarchy, and shared
              memory together in one competitive setting.
            </p>
          </article>

          <article className="proposal-pillar">
            <span className="pillar-num mono">MOTIVATION 04</span>
            <h3>Explainable scenario testbed for coaches</h3>
            <p>
              Rather than presenting an unvalidated black-box predictor of
              real-world match scores, this simulator gives coaches and sports
              analysts a controlled, auditable environment to test natural
              language player profiles, pre-game strategies, and counter-tactics
              at the possession level.
            </p>
          </article>
        </div>

        {/* INTERACTIVE 3-LAYER SYSTEM SEPARATION EXPLORER */}
        <div className="anatomy-card">
          <div className="anatomy-head">
            <div>
              <span className="eyebrow">
                PROPOSAL §3 &amp; §4 · ARCHITECTURAL SEPARATION OF CONCERNS
              </span>
              <h3>
                Studying LLM coordination without letting the LLM hallucinate
                outcomes.
              </h3>
              <p>
                A core design principle of our proposal is separating high-level
                tactical reasoning from physical action resolution and rule
                enforcement. Select a layer to inspect its exact contract:
              </p>
            </div>
            <div className="anatomy-tabs" role="tablist" aria-label="System layers">
              <button
                type="button"
                role="tab"
                aria-selected={activeLayer === "llm"}
                className={`anatomy-tab ${activeLayer === "llm" ? "active" : ""}`}
                onClick={() => setActiveLayer("llm")}
              >
                01 · LLM Player Agents
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeLayer === "engine"}
                className={`anatomy-tab ${
                  activeLayer === "engine" ? "active" : ""
                }`}
                onClick={() => setActiveLayer("engine")}
              >
                02 · Non-LLM Resolution Engine
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeLayer === "referee"}
                className={`anatomy-tab ${
                  activeLayer === "referee" ? "active" : ""
                }`}
                onClick={() => setActiveLayer("referee")}
              >
                03 · FIBA 3×3 RAG Referee
              </button>
            </div>
          </div>

          <div className="anatomy-body">
            {activeLayer === "llm" ? (
              <div className="anatomy-panel">
                <div className="anatomy-copy">
                  <span className="eyebrow">
                    LAYER 01 · HIGH-LEVEL TACTICAL INTENT &amp; MESSAGING
                  </span>
                  <h4>
                    Six persistent player agents operating under partial
                    observability
                  </h4>
                  <p>
                    At each meaningful game event (pass reception, screen
                    engagement, drive, shot, rebound, defensive rotation, or
                    shot-clock threshold), each player receives a 9-part
                    structured observation: own grid position &amp; fatigue,
                    teammate &amp; opponent vectors, defensive matchups, ball
                    state, clock/fouls, captain call, recent teammate messages,
                    and shared team memory.
                  </p>
                  <ul className="anatomy-list">
                    <li>
                      <strong>Simultaneous Action &amp; Message Emission:</strong>{" "}
                      Messages and captain calls generated at event <code>t</code>{" "}
                      are stored and delivered in teammates&apos; observations at
                      event <code>t + 1</code>, avoiding multi-round latency.
                    </li>
                    <li>
                      <strong>Explicit Memory Attribution:</strong> When shared
                      memory is enabled, actions include{" "}
                      <code>memory_ref=&quot;M03&quot;</code> and captain calls
                      include <code>[tactic cs=01]</code> to audit adaptation.
                    </li>
                  </ul>
                </div>
                <div className="anatomy-code-box">
                  <div className="code-box-title mono">
                    PROPOSAL §4.2–4.4 · STRUCTURED AGENT OUTPUTS
                  </div>
                  <pre className="mono">{`<ACTIONS>
  <A1 action="PASS" target="A2" memory_ref="M03"/>
  <A2 action="CUT_BASELINE" target="RIGHT_CORNER" memory_ref="None"/>
  <A3 action="SCREEN" target="B2" memory_ref="M07"/>
</ACTIONS>

<!-- Captain Tactical Call & Teammate Action Messages -->
<A1><c>[tactic cs=01] run pick and roll on the left wing,
A2 will be handler [/tactic]</c></A1>
<A2>[action] A3 set a screen for A2 [/action]</A2>

<!-- Proposed Shared Opponent Memory Write -->
<MEMORY_UPDATE opponent="B1" category="defensive_tendency"
  tendency="leaves passing lanes open on contested drives" />`}</pre>
                </div>
              </div>
            ) : null}

            {activeLayer === "engine" ? (
              <div className="anatomy-panel">
                <div className="anatomy-copy">
                  <span className="eyebrow">
                    LAYER 02 · DETERMINISTIC RULES &amp; STOCHASTIC PHYSICS
                  </span>
                  <h4>
                    Explicit logistic resolvers &amp; 20 game-state constraints
                  </h4>
                  <p>
                    Selecting <code>SHOOT</code> or <code>PASS</code> never
                    guarantees success. The non-LLM simulation engine validates
                    every proposed action against 20 physical and rule
                    constraints (unique ball possession, movement speed limits,
                    12s shot clock, out-of-bounds) and safely remaps any
                    infeasible LLM proposal so the game never halts.
                  </p>
                  <div className="formula-callout">
                    <span className="eyebrow">
                      EXPLICIT SHOT RESOLUTION MODEL (PROPOSAL §4.2)
                    </span>
                    <div className="formula-math serif-italic">
                      P(make) = σ(β₀ + β₁ · shooting + β₂ · shotquality − β₃ ·
                      contest − β₄ · fatigue)
                    </div>
                    <small>
                      Analogous explicit resolvers govern passes, drives,
                      turnovers, rebounds, screens, and steals—keeping
                      coefficients transparent for sensitivity analysis.
                    </small>
                  </div>
                </div>
                <div className="anatomy-code-box">
                  <div className="code-box-title mono">
                    PROPOSAL APPENDIX TABLE 3 · 20 GAME-STATE INVARIANTS
                  </div>
                  <pre className="mono">{`01. Unique Ball Possession    At most one player has_ball = true
02. Ball–Possessor Match      Ball coordinates match handler state
03. Valid Player Positions    All 6 players within 15×11m half-court
07. Possession-Dependent      Only ball handler can PASS or SHOOT
08. Action Feasibility        Screen/cut target within reach radius
09. Movement Limit            Max displacement bounded per tick
11. 12s Shot-Clock Validity   Monotonic decay unless valid reset
13. Possession Transition     Changes only on make/rebound/steal/TO
17. Defensive Matchup         Defenders guard active opponents only
20. Dead-Ball Consistency     No live-ball DRIVE during dead ball`}</pre>
                </div>
              </div>
            ) : null}

            {activeLayer === "referee" ? (
              <div className="anatomy-panel">
                <div className="anatomy-copy">
                  <span className="eyebrow">
                    LAYER 03 · OFFICIAL FIBA 3×3 RULEBOOK RAG OFFICIATING
                  </span>
                  <h4>
                    Deterministic query templating + top-3 clause retrieval
                  </h4>
                  <p>
                    Objective violations (out-of-bounds, 12-second shot-clock
                    expiration) are handled directly by the engine. When physical
                    contact occurs (e.g. <code>BODY_CONTACT</code> on a drive),
                    a separate LLM referee agent evaluates whether a foul
                    occurred—grounded in the official FIBA 3×3 rulebook via
                    Retrieval-Augmented Generation (RAG).
                  </p>
                  <ul className="anatomy-list">
                    <li>
                      <strong>Reproducible Query Templating:</strong> Structured
                      contact fields (player states before/after contact, ball
                      possession, location) generate a deterministic query.
                    </li>
                    <li>
                      <strong>Category-Filtered Vector Retrieval:</strong> Top-3
                      matching rulebook chunks are appended to the referee state
                      before the referee emits its structured ruling.
                    </li>
                  </ul>
                </div>
                <div className="anatomy-code-box">
                  <div className="code-box-title mono">
                    PROPOSAL §4.5 &amp; CODE 3 · RAG REFEREE DECISION
                  </div>
                  <pre className="mono">{`[CONTACT EVENT]
Contact Detected: true
Players Involved: A1 (DRIVE_RIGHT), B1 (CONTEST_DRIVE)
Contact Location: (5, 7) · Contact Type: BODY_CONTACT
Retrieved Rules: FIBA 3x3 Art. 33 (Cylinder & Legal Guarding)

<REFEREE_DECISION
  foul="TRUE"
  offender="B1"
  fouled_player="A1"
  foul_type="DEFENSIVE_FOUL"
/>`}</pre>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </section>

      {/* SECTION 03: EXPERIMENTAL TEAM CONFIGURATIONS & METRICS (PROPOSAL TABLES 1 & 2) */}
      <section className="proposal-matrix-section">
        <div className="section-editorial-head">
          <div>
            <span className="eyebrow">
              03 · CONTROLLED ABLATION DESIGN (PROPOSAL §4.6 &amp; §5)
            </span>
            <h2>Four team configurations. Seven formal evaluation metrics.</h2>
          </div>
          <p className="editorial-sub">
            Player profiles, underlying LLM (<code>mistral-small-3.2-24b-instruct</code>),
            simulation physics, and RAG referee settings are held constant across
            Teams A–D so behavioural differences isolate the ablated mechanism.
          </p>
        </div>

        <div className="matrix-two-col">
          {/* Table 1: Team Configurations */}
          <div className="card matrix-card">
            <div className="card-head">
              <div>
                <div className="eyebrow">PROPOSAL TABLE 1</div>
                <h3>Experimental Team Configurations</h3>
                <p>
                  Team A (Full System) serves as the reference condition in head-to-head play
                </p>
              </div>
            </div>
            <div className="table-wrap">
              <table className="proposal-config-table">
                <thead>
                  <tr>
                    <th>Configuration</th>
                    <th>Teammate Comms</th>
                    <th>Captain Calls</th>
                    <th>Memory Writes</th>
                    <th>Study Link</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>
                      <strong>Team A · Full System</strong>
                      <small>Reference baseline across all 3 studies</small>
                    </td>
                    <td>
                      <span className="cap-badge yes">✔ Enabled</span>
                    </td>
                    <td>
                      <span className="cap-badge yes">✔ Enabled</span>
                    </td>
                    <td>
                      <span className="cap-badge yes">✔ Read + Write</span>
                    </td>
                    <td>
                      <Link className="text-link" href="/comparisons">
                        All 3 studies →
                      </Link>
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <strong>Team B · No Communication</strong>
                      <small>Tests if peer messaging improves cooperation</small>
                    </td>
                    <td>
                      <span className="cap-badge no">✖ Disabled</span>
                    </td>
                    <td>
                      <span className="cap-badge yes">✔ Enabled</span>
                    </td>
                    <td>
                      <span className="cap-badge yes">✔ Read + Write</span>
                    </td>
                    <td>
                      <Link
                        className="text-link"
                        href="/experiments/abl_comms_v1"
                      >
                        abl_comms_v1 →
                      </Link>
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <strong>Team C · No Captain</strong>
                      <small>Tests if centralized calls improve coherence</small>
                    </td>
                    <td>
                      <span className="cap-badge yes">✔ Enabled</span>
                    </td>
                    <td>
                      <span className="cap-badge no">✖ Disabled</span>
                    </td>
                    <td>
                      <span className="cap-badge yes">✔ Read + Write</span>
                    </td>
                    <td>
                      <Link
                        className="text-link"
                        href="/experiments/abl_captain_v1"
                      >
                        abl_captain_v1 →
                      </Link>
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <strong>Team D · Read-Only Memory</strong>
                      <small>Tests within-game opponent adaptation</small>
                    </td>
                    <td>
                      <span className="cap-badge yes">✔ Enabled</span>
                    </td>
                    <td>
                      <span className="cap-badge yes">✔ Enabled</span>
                    </td>
                    <td>
                      <span className="cap-badge amber">✖ Read-Only</span>
                    </td>
                    <td>
                      <Link
                        className="text-link"
                        href="/experiments/abl_memory_v1"
                      >
                        abl_memory_v1 →
                      </Link>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* Table 2: Formal Metrics */}
          <div className="card matrix-card">
            <div className="card-head">
              <div>
                <div className="eyebrow">PROPOSAL TABLE 2 &amp; §5.2</div>
                <h3>Possession &amp; Validity Metric Definitions</h3>
                <p>
                  Derived automatically from structured simulation event logs
                </p>
              </div>
            </div>
            <div className="metrics-glossary-list">
              <div className="glossary-item">
                <div className="glossary-term">
                  <strong className="mono">PPP</strong>
                  <span>Points-Per-Possession</span>
                </div>
                <p>
                  <code>Total points scored / Total possessions</code>. Primary
                  measure of offensive scoring efficiency across all comparisons.
                </p>
              </div>
              <div className="glossary-item">
                <div className="glossary-term">
                  <strong className="mono">MAAR</strong>
                  <span>Message–Action Alignment Rate</span>
                </div>
                <p>
                  Proportion of actions consistent with a preceding teammate{" "}
                  <code>[action]</code> message intent (<code>1/N Σ I(Aᵢ ~ Mᵢ)</code>).
                </p>
              </div>
              <div className="glossary-item">
                <div className="glossary-term">
                  <strong className="mono">CCAR</strong>
                  <span>Captain-Call Adherence Rate</span>
                </div>
                <p>
                  Proportion of teammate actions adhering to the captain&apos;s{" "}
                  <code>&lt;c&gt;[action]</code> or tactical instruction.
                </p>
              </div>
              <div className="glossary-item">
                <div className="glossary-term">
                  <strong className="mono">MAUR &amp; CSSR</strong>
                  <span>Memory Utilisation &amp; Counter-Strategy Rate</span>
                </div>
                <p>
                  Share of actions citing a non-null <code>memory_ref</code>{" "}
                  (MAUR) and tactic calls selecting a learned lookup key{" "}
                  <code>cs=key_id</code> (CSSR).
                </p>
              </div>
              <div className="glossary-item">
                <div className="glossary-term">
                  <strong className="mono">IAR &amp; SIR</strong>
                  <span>Invalid Action &amp; State Inconsistency Rate</span>
                </div>
                <p>
                  Frequency of infeasible agent proposals remapped by the engine
                  (IAR) and impossible post-resolution game states (SIR = 0.00%).
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* SECTION 04: THE ABLATIONS, SIDE BY SIDE */}
      <ComparisonsSection data={comparisons} isEmbedded={true} />
    </div>
  );
}
