"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { CatalogData, ExperimentOverview } from "@/lib/types";

export function AppShell({
  catalog,
  overviews,
  children,
}: {
  catalog: CatalogData;
  overviews: Record<string, ExperimentOverview>;
  children: React.ReactNode;
}) {
  const pathname = usePathname() || "/";
  const router = useRouter();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteQuery, setPaletteQuery] = useState("");

  // Extract experimentId from URL if inside /experiments/[experimentId]
  const match = pathname.match(/^\/experiments\/([^/]+)(?:\/([^/]+))?/);
  const currentExperimentId =
    match && overviews[match[1]] ? match[1] : catalog.default;
  const subSection = match?.[2] || "";
  const currentOverview =
    overviews[currentExperimentId] || overviews[catalog.default];

  // Legacy hash redirect support (e.g. /#replay?experiment=abl_comms_v1&game=...)
  useEffect(() => {
    if (typeof window === "undefined" || !window.location.hash) return;
    const rawHash = window.location.hash.slice(1);
    const [view, query = ""] = rawHash.split("?");
    const params = new URLSearchParams(query);
    const exp = params.get("experiment") || currentExperimentId;
    if (view === "overview") {
      router.replace(`/experiments/${encodeURIComponent(exp)}`);
    } else if (view === "games") {
      const seed = params.get("seed");
      router.replace(
        `/experiments/${encodeURIComponent(exp)}/games${
          seed ? `?seed=${encodeURIComponent(seed)}` : ""
        }`
      );
    } else if (view === "replay") {
      const game = params.get("game");
      const event = params.get("event");
      if (game) {
        router.replace(
          `/experiments/${encodeURIComponent(exp)}/replay/${encodeURIComponent(
            game
          )}${event ? `?event=${encodeURIComponent(event)}` : ""}`
        );
      } else {
        router.replace(`/experiments/${encodeURIComponent(exp)}/replay`);
      }
    } else if (view === "notes") {
      router.replace(`/experiments/${encodeURIComponent(exp)}/methods`);
    } else if (view === "architecture") {
      router.replace("/architecture");
    }
  }, [currentExperimentId, router]);

  // Global keyboard shortcut (Cmd/Ctrl + K or Escape) for Quick Jump modal
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((prev) => !prev);
      } else if (e.key === "Escape" && paletteOpen) {
        setPaletteOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [paletteOpen]);

  const isLanding = pathname === "/";
  const isComparisons = pathname === "/comparisons";
  const isArchitecture = pathname.startsWith("/architecture");
  const isOverview =
    pathname === `/experiments/${currentExperimentId}` &&
    !isLanding &&
    !isComparisons;
  const isGames = subSection === "games";
  const isReplay = subSection === "replay";
  const isMethods = subSection === "methods";

  const totalGamesInExperiment =
    currentOverview.summary.games +
    (currentOverview.unexported_games?.length ?? 0);

  const navigateToExperiment = (nextExp: string) => {
    if (isGames) {
      router.push(`/experiments/${encodeURIComponent(nextExp)}/games`);
    } else if (isMethods) {
      router.push(`/experiments/${encodeURIComponent(nextExp)}/methods`);
    } else if (isReplay) {
      router.push(`/experiments/${encodeURIComponent(nextExp)}/replay`);
    } else {
      router.push(`/experiments/${encodeURIComponent(nextExp)}`);
    }
  };

  const handleExperimentSelect = (e: React.ChangeEvent<HTMLSelectElement>) => {
    navigateToExperiment(e.target.value);
  };

  const quickDestinations = [
    {
      category: "Hub & Comparisons",
      label: "Research Hub & Interactive Path Chooser",
      sub: "Project proposal, 3-layer anatomy, and task router",
      href: "/",
    },
    {
      category: "Hub & Comparisons",
      label: "All Experiments — Side-by-Side Ablations",
      sub: "Compare Team A vs Teams B, C, and D across 31 exported games",
      href: "/comparisons",
    },
    {
      category: "System",
      label: "6-Stage System & Agent Architecture",
      sub: "Interactive pipeline schematic, RAG referee, and 5-module player modal",
      href: "/architecture",
    },
    ...catalog.experiments.flatMap((exp) => [
      {
        category: exp.title,
        label: `${exp.title} — Experiment Overview`,
        sub: `${exp.conditions.join(" vs ")} · Paired seed analysis & PPP scatters`,
        href: `/experiments/${exp.id}`,
      },
      {
        category: exp.title,
        label: `${exp.title} — Interactive 3v3 Court Replay`,
        sub: `Step through 15×11m half-court possessions for ${exp.id}`,
        href: `/experiments/${exp.id}/replay`,
      },
      {
        category: exp.title,
        label: `${exp.title} — Game Library`,
        sub: `Filter and inspect all recorded games for ${exp.id}`,
        href: `/experiments/${exp.id}/games`,
      },
      {
        category: exp.title,
        label: `${exp.title} — Methods, CSVs & Plots`,
        sub: `Download raw CSVs and view saved statistical figures for ${exp.id}`,
        href: `/experiments/${exp.id}/methods`,
      },
    ]),
  ];

  const filteredDestinations = quickDestinations.filter((item) => {
    const q = paletteQuery.trim().toLowerCase();
    if (!q) return true;
    return (
      item.label.toLowerCase().includes(q) ||
      item.sub.toLowerCase().includes(q) ||
      item.category.toLowerCase().includes(q) ||
      item.href.toLowerCase().includes(q)
    );
  });

  return (
    <>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <aside className="sidebar">
        <Link className="brand" href="/" aria-label="Courtside home">
          <span>
            courtside<span className="brand-sub">MULTI-AGENT RESEARCH</span>
          </span>
        </Link>
        <div className="nav-caption">NAVIGATE</div>
        <nav aria-label="Main navigation">
          <Link
            href="/"
            className={isLanding ? "active" : ""}
            aria-current={isLanding ? "page" : undefined}
          >
            <span className="nav-icon">◎</span> Research hub
          </Link>
          <Link
            href="/comparisons"
            className={isComparisons ? "active" : ""}
            aria-current={isComparisons ? "page" : undefined}
          >
            <span className="nav-icon">▤</span> All experiments
          </Link>
          <Link
            href={`/experiments/${currentExperimentId}`}
            className={isOverview ? "active" : ""}
            aria-current={isOverview ? "page" : undefined}
          >
            <span className="nav-icon">▦</span> Experiment overview
          </Link>
          <Link
            href={`/experiments/${currentExperimentId}/games`}
            className={isGames ? "active" : ""}
            aria-current={isGames ? "page" : undefined}
          >
            <span className="nav-icon">◫</span> Game library{" "}
            <span id="nav-count" className="nav-count">
              {totalGamesInExperiment}
            </span>
          </Link>
          <Link
            href={`/experiments/${currentExperimentId}/replay`}
            className={isReplay ? "active" : ""}
            aria-current={isReplay ? "page" : undefined}
          >
            <span className="nav-icon">▷</span> Court replay
          </Link>
          <Link
            href={`/experiments/${currentExperimentId}/methods`}
            className={isMethods ? "active" : ""}
            aria-current={isMethods ? "page" : undefined}
          >
            <span className="nav-icon">≡</span> Methods &amp; data
          </Link>
          <div className="nav-caption secondary">SYSTEM</div>
          <Link
            href="/architecture"
            className={isArchitecture ? "active" : ""}
            aria-current={isArchitecture ? "page" : undefined}
          >
            <span className="nav-icon">◈</span> System architecture
          </Link>
        </nav>
        <div className="sidebar-run">
          <span className="eyebrow">ACTIVE ABLATION</span>
          <strong id="study-title">
            {currentOverview.study?.title || "Team comparison"}
          </strong>
          <p id="study-matchup">
            {currentOverview.conditions.map((c) => c.label).join(" × ")}
          </p>
          <span className="pill sidebar-pill">
            <i /> Recorded results
          </span>
        </div>
        <div className="sidebar-bottom">
          <div>
            DSA4213 · Group 16
            <span>FIBA 3×3 · Six LLM agents · One half-court</span>
          </div>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumbs">
            <Link href="/" className="breadcrumb-home">
              Courtside
            </Link>
            <span>/</span>
            {isLanding ? (
              <strong id="experiment-id">research_hub</strong>
            ) : isComparisons ? (
              <strong id="experiment-id">all_experiments</strong>
            ) : isArchitecture ? (
              <strong id="experiment-id">system_architecture</strong>
            ) : (
              <>
                <Link
                  href={`/experiments/${encodeURIComponent(
                    currentExperimentId
                  )}`}
                  className="breadcrumb-exp"
                >
                  <strong id="experiment-id">{currentExperimentId}</strong>
                </Link>
                {subSection ? (
                  <>
                    <span>/</span>
                    <span className="breadcrumb-sub mono">{subSection}</span>
                  </>
                ) : null}
              </>
            )}
          </div>

          <div className="topbar-right">
            <button
              type="button"
              className="quick-jump-trigger"
              onClick={() => {
                setPaletteQuery("");
                setPaletteOpen(true);
              }}
              aria-label="Open quick navigation menu"
            >
              <span>Quick jump</span>
              <kbd className="mono">⌘K</kbd>
            </button>

            <label className="experiment-picker" htmlFor="experiment-select">
              Study{" "}
              <select
                id="experiment-select"
                aria-label="Select experiment"
                value={currentExperimentId}
                disabled={catalog.experiments.length < 2}
                onChange={handleExperimentSelect}
              >
                {catalog.experiments.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.title} · {option.conditions.join(" vs ")}
                  </option>
                ))}
              </select>
            </label>

            <span className="status-dot" />
            <span className="topbar-status-text">
              Published · {catalog.dataset?.exported_games ?? 31} games
            </span>
          </div>
        </header>

        <main id="main" tabIndex={-1}>
          {children}
        </main>

        <footer className="footer">
          <div className="footer-left">
            <strong>COURTSIDE</strong>
            <span className="footer-dot">·</span>
            <span>
              Multi-Agent Cooperation &amp; Adaptation in Competitive 3v3
              Basketball (DSA4213 Group 16)
            </span>
          </div>
          <div className="footer-links">
            <Link href="/">Research hub</Link>
            <Link href="/comparisons">All ablations</Link>
            <Link href={`/experiments/${currentExperimentId}`}>Overview</Link>
            <Link href={`/experiments/${currentExperimentId}/replay`}>
              Court replay
            </Link>
            <Link href="/architecture">Architecture</Link>
          </div>
          <span id="footer-source" className="mono">
            {currentOverview.summary.games} exported games ·{" "}
            {currentOverview.summary.seeds} paired seeds · {currentExperimentId}
          </span>
        </footer>
      </div>

      {/* QUICK-JUMP COMMAND PALETTE MODAL */}
      {paletteOpen ? (
        <div
          className="palette-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label="Quick navigation router"
          onClick={(e) => {
            if (e.target === e.currentTarget) setPaletteOpen(false);
          }}
        >
          <div className="palette-modal">
            <div className="palette-head">
              <input
                type="search"
                className="palette-input"
                placeholder="Where do you want to go? (e.g. replay, communication, captain, memory, architecture...)"
                value={paletteQuery}
                onChange={(e) => setPaletteQuery(e.target.value)}
                autoFocus
              />
              <button
                type="button"
                className="palette-close"
                onClick={() => setPaletteOpen(false)}
              >
                ESC
              </button>
            </div>
            <div className="palette-list">
              {filteredDestinations.length ? (
                filteredDestinations.map((item) => (
                  <button
                    key={item.href}
                    type="button"
                    className={`palette-item ${
                      pathname === item.href ? "current" : ""
                    }`}
                    onClick={() => {
                      setPaletteOpen(false);
                      router.push(item.href);
                    }}
                  >
                    <div>
                      <span className="palette-cat">{item.category}</span>
                      <strong>{item.label}</strong>
                      <small>{item.sub}</small>
                    </div>
                    <code className="mono">{item.href}</code>
                  </button>
                ))
              ) : (
                <div className="palette-empty">
                  No matching destinations for &ldquo;{paletteQuery}&rdquo;
                </div>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
