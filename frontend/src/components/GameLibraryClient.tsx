"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import type { ExperimentOverview, GameSummaryRow } from "@/lib/types";
import {
  conditionColor,
  conditionLabel,
  fmt,
  title,
} from "@/lib/format";

export function GameLibraryClient({
  experiment,
}: {
  experiment: ExperimentOverview;
}) {
  const searchParams = useSearchParams();
  const initialSeed = searchParams.get("seed") || "";

  const [query, setQuery] = useState(initialSeed);
  const [firstFilter, setFirstFilter] = useState("");
  const [winnerFilter, setWinnerFilter] = useState("");

  const allGames: GameSummaryRow[] = [
    ...experiment.games,
    ...(experiment.unexported_games ?? []),
  ];

  const qLower = query.toLowerCase().trim();
  const filteredRows = allGames.filter(
    (g) =>
      (!qLower ||
        g.id.toLowerCase().includes(qLower) ||
        String(g.seed).toLowerCase().includes(qLower)) &&
      (!firstFilter || g.first_possession === firstFilter) &&
      (!winnerFilter || g.winner === winnerFilter)
  );

  const comparisonText = experiment.conditions.map((c) => c.label).join(" / ");

  return (
    <>
      <div className="toolbar">
        <div className="filters">
          <input
            className="search"
            id="game-search"
            type="search"
            placeholder="Search by seed or game ID…"
            aria-label="Search games"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select
            id="first-filter"
            aria-label="Filter by first possession"
            value={firstFilter}
            onChange={(e) => setFirstFilter(e.target.value)}
          >
            <option value="">Either team starts</option>
            <option value="A">Team A starts</option>
            <option value="B">Team B starts</option>
          </select>
          <select
            id="winner-filter"
            aria-label="Filter by winner"
            value={winnerFilter}
            onChange={(e) => setWinnerFilter(e.target.value)}
          >
            <option value="">All results</option>
            {experiment.conditions.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label} wins
              </option>
            ))}
          </select>
        </div>
        <span className="muted" id="game-count">
          {filteredRows.length} of {allGames.length} games
          {experiment.unexported_games?.length
            ? ` (${experiment.games.length} exported + ${experiment.unexported_games.length} log-only)`
            : ""}
        </span>
      </div>
      <section className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Game / seed</th>
                <th>Starts</th>
                <th>{comparisonText}</th>
                <th>Winner</th>
                <th>Events</th>
                <th>End condition</th>
                <th></th>
              </tr>
            </thead>
            <tbody id="games-body">
              {filteredRows.length ? (
                filteredRows.map((g) => (
                  <tr key={g.id} className="game-row">
                    <td>
                      <strong>Seed {g.seed}</strong>{" "}
                      {g.unexported ? (
                        <span
                          className="status-label amber"
                          title="Present in raw run logs, not included in exported summary tables"
                        >
                          Log only
                        </span>
                      ) : null}
                      <small className="game-id">{g.id}</small>
                    </td>
                    <td>
                      <span className="status-label">
                        Team {g.first_possession}
                      </span>
                    </td>
                    <td>
                      <div className="mini-score">
                        <b className="green-text">{fmt(g.score.A, 0)}</b>
                        <span>:</span>
                        <b className="orange-text">{fmt(g.score.B, 0)}</b>
                      </div>
                    </td>
                    <td
                      style={{
                        color: conditionColor(experiment.conditions, g.winner),
                      }}
                    >
                      {g.winner
                        ? conditionLabel(experiment.conditions, g.winner)
                        : "No winner"}
                    </td>
                    <td className="mono">{fmt(g.events, 0)}</td>
                    <td>
                      {title(g.end_reason)}
                      <small>
                        {g.unexported
                          ? "Complete · Log only"
                          : g.complete
                            ? "Complete"
                            : "Incomplete"}
                      </small>
                    </td>
                    <td>
                      {g.available ? (
                        <Link
                          className="button small"
                          href={`/experiments/${encodeURIComponent(
                            experiment.experiment_id
                          )}/replay/${encodeURIComponent(g.id)}`}
                        >
                          Replay ↗
                        </Link>
                      ) : (
                        <button className="button small" disabled>
                          Log missing
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={7}>
                    <div className="empty-state">
                      No games match these filters.
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
      <p className="chart-note" style={{ marginTop: "14px" }}>
        A/B in the game ID identifies the first-possession variant. Conditions
        stay attached to the physical teams recorded in each log.
      </p>
    </>
  );
}

