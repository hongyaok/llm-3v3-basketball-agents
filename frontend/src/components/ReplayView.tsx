"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import type {
  ExperimentOverview,
  FrameState,
  GameReplay,
  GameSummaryRow,
  PlayerState,
} from "@/lib/types";
import { fetchGameReplay } from "@/lib/data-client";
import {
  clock,
  conditionColor,
  conditionIndex,
  conditionLabel,
  fmt,
  title,
} from "@/lib/format";
import {
  activePossessionId,
  eventActor,
  eventCues,
  eventTitle,
  momentKinds,
  possessionFrameIndex,
} from "@/lib/replay-logic";
import { Legend, LineChartSvg, PageHeading } from "./SharedUi";

type InspectorTab = "decisions" | "team talk" | "outcome";

function computeCourtGeometry(court: GameReplay["court"]) {
  const cell = Number(court.cell_m) || 1;
  const width = (Number(court.width_m) || 15) / cell;
  const depth = (Number(court.depth_m) || 11) / cell;
  const scale = Math.min(710 / width, 520 / depth);
  const ox = (800 - width * scale) / 2;
  const oy = 34;
  const xy = (pos: [number, number]): [number, number] => [
    ox + (pos[0] + 0.5) * scale,
    oy + (pos[1] + 0.5) * scale,
  ];
  const basket = xy((court.basket as [number, number]) || [7, 1]);
  const radius = ((Number(court.arc_radius_m) || 6.75) / cell) * scale;
  const arc = Array.from({ length: 61 }, (_, i) => {
    const a = (i * Math.PI) / 60;
    return `${i ? "L" : "M"}${basket[0] + radius * Math.cos(a)},${
      basket[1] + radius * Math.sin(a)
    }`;
  }).join(" ");
  return { cell, width, depth, scale, ox, oy, xy, basket, radius, arc };
}

function getCourtPlayerPositions(
  state: FrameState | undefined,
  xy: (pos: [number, number]) => [number, number]
): Map<string, [number, number]> | null {
  if (!state) return null;
  const groups = new Map<string, string[]>();
  const positions = new Map<string, [number, number]>();
  const sortedPlayers = Object.values(state.players).sort((a, b) =>
    a.id.localeCompare(b.id)
  );
  for (const player of sortedPlayers) {
    const key = JSON.stringify(player.pos);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(player.id);
  }
  for (const player of sortedPlayers) {
    const members = groups.get(JSON.stringify(player.pos))!;
    const angle = (members.indexOf(player.id) * Math.PI * 2) / members.length;
    const [x, y] = xy(player.pos);
    positions.set(player.id, [
      x + (members.length > 1 ? Math.cos(angle) * 13 : 0),
      y + (members.length > 1 ? Math.sin(angle) * 13 : 0),
    ]);
  }
  return positions;
}

function getBallTargetPosition(
  state: FrameState,
  xy: (pos: [number, number]) => [number, number]
): [number, number] {
  const players = Object.values(state.players).sort((a, b) =>
    a.id.localeCompare(b.id)
  );
  const holder = players.find((p) => p.has_ball || p.id === state.ball.holder);
  const [x, y] = xy(holder ? holder.pos : state.ball.pos);
  return [x + (holder ? 23 : 0), y + (holder ? 15 : 0)];
}

export function ReplayView({
  experiment,
  gameId,
}: {
  experiment: ExperimentOverview;
  gameId: string;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialEventParam = Number(searchParams.get("event")) || 0;

  const [game, setGame] = useState<GameReplay | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(600);
  const [timelineSpan, setTimelineSpan] = useState<number>(40);
  const [timelineStart, setTimelineStart] = useState(0);
  const [showTrails, setShowTrails] = useState(true);
  const [focusedPlayer, setFocusedPlayer] = useState<string | null>(null);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("decisions");
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  const svgRef = useRef<SVGSVGElement | null>(null);
  const clockNodeRef = useRef<HTMLDivElement | null>(null);
  const shotClockNodeRef = useRef<HTMLElement | null>(null);
  const displayedPositionsRef = useRef<Map<string, [number, number]>>(
    new Map()
  );
  const stepAnimRef = useRef<number | null>(null);
  const playbackRafRef = useRef<number | null>(null);
  const playbackFractionRef = useRef<number>(0);
  const shouldAnimateStepRef = useRef<boolean>(false);
  const frameIndexRef = useRef<number>(0);
  frameIndexRef.current = frameIndex;

  const showToast = useCallback((msg: string) => {
    setToastMsg(msg);
  }, []);

  useEffect(() => {
    if (!toastMsg) return;
    const t = setTimeout(() => setToastMsg(null), 3500);
    return () => clearTimeout(t);
  }, [toastMsg]);

  // Load game replay JSON
  useEffect(() => {
    const controller = new AbortController();
    setGame(null);
    setError(null);
    setPlaying(false);
    displayedPositionsRef.current.clear();
    playbackFractionRef.current = 0;

    fetchGameReplay(experiment.experiment_id, gameId, controller.signal)
      .then((loaded) => {
        setGame(loaded);
        const idx = Math.max(
          0,
          loaded.frames.findIndex((f) => f.event_idx === initialEventParam)
        );
        setFrameIndex(idx);
        setFocusedPlayer(null);
        setTimelineStart(0);
        setTimelineSpan(40);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : String(err));
      });

    return () => {
      controller.abort();
    };
  }, [experiment.experiment_id, gameId, initialEventParam]);

  const isOrangeTeam = useCallback(
    (team: string | null | undefined) => {
      if (!game || !team) return false;
      const cond = game.conditions[team as "A" | "B"];
      return conditionIndex(experiment.conditions, cond) === 1;
    },
    [experiment.conditions, game]
  );

  const teamColor = useCallback(
    (team: "A" | "B") => {
      const cond = game?.conditions[team];
      return conditionColor(experiment.conditions, cond);
    },
    [experiment.conditions, game]
  );

  const goFrame = useCallback(
    (targetIdx: number, animate = false) => {
      if (!game) return;
      playbackFractionRef.current = 0;
      shouldAnimateStepRef.current = animate;
      const clamped = Math.max(0, Math.min(game.frames.length - 1, targetIdx));
      setFrameIndex(clamped);
    },
    [game]
  );

  const pausePlayback = useCallback(() => {
    if (playbackRafRef.current !== null) {
      cancelAnimationFrame(playbackRafRef.current);
      playbackRafRef.current = null;
    }
    setPlaying(false);
  }, []);

  // Keep timeline window synced with frameIndex
  useEffect(() => {
    if (!game) return;
    const span = Math.min(timelineSpan, game.frames.length);
    if (!Number.isFinite(timelineSpan)) {
      setTimelineStart(0);
    } else if (
      frameIndex < timelineStart ||
      frameIndex >= timelineStart + span
    ) {
      setTimelineStart(Math.floor(frameIndex / span) * span);
    }
  }, [frameIndex, game, timelineSpan, timelineStart]);

  // Step / position update on court SVG
  useEffect(() => {
    if (!game || !svgRef.current) return;
    const svg = svgRef.current;
    const f = game.frames[frameIndex];
    const s = f.state;
    const { xy } = computeCourtGeometry(game.court);
    const playerPositions = getCourtPlayerPositions(s, xy);
    if (!playerPositions) return;

    const targets = new Map<string, [number, number]>();
    const from = new Map<string, [number, number]>();
    const nodes = new Map<string, SVGGElement>();

    svg.querySelectorAll<SVGGElement>(".court-player").forEach((node) => {
      const pid = node.dataset.player;
      if (!pid) return;
      const target = playerPositions.get(pid);
      if (!target) return;
      targets.set(pid, target);
      from.set(pid, displayedPositionsRef.current.get(pid) || target);
      nodes.set(pid, node);
    });

    const ballGroup = svg.querySelector<SVGGElement>(
      'g[aria-label="Basketball"]'
    );
    if (ballGroup) {
      const ballTarget = getBallTargetPosition(s, xy);
      targets.set("__ball__", ballTarget);
      from.set(
        "__ball__",
        displayedPositionsRef.current.get("__ball__") || ballTarget
      );
      nodes.set("__ball__", ballGroup);
    }

    if (stepAnimRef.current !== null) {
      cancelAnimationFrame(stepAnimRef.current);
      stepAnimRef.current = null;
    }

    const animate = shouldAnimateStepRef.current;
    shouldAnimateStepRef.current = false;
    const reducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const duration = animate && !reducedMotion ? Math.min(320, speed) : 0;
    const previous = game.frames[frameIndex - 1]?.state;

    const draw = (progress: number) => {
      for (const [id, target] of targets) {
        const start = from.get(id)!;
        const x = start[0] + (target[0] - start[0]) * progress;
        const y = start[1] + (target[1] - start[1]) * progress;
        nodes.get(id)?.setAttribute("transform", `translate(${x} ${y})`);
        displayedPositionsRef.current.set(id, [x, y]);
      }
      if (
        duration &&
        previous?.phase === s.phase &&
        typeof previous.game_clock_s === "number" &&
        typeof s.game_clock_s === "number" &&
        clockNodeRef.current?.firstChild
      ) {
        clockNodeRef.current.firstChild.nodeValue = clock(
          previous.game_clock_s +
            (s.game_clock_s - previous.game_clock_s) * progress
        );
      }
      if (
        duration &&
        typeof previous?.shot_clock_s === "number" &&
        previous.shot_clock_s >= s.shot_clock_s &&
        shotClockNodeRef.current
      ) {
        shotClockNodeRef.current.textContent = `${fmt(
          previous.shot_clock_s +
            (s.shot_clock_s - previous.shot_clock_s) * progress,
          1
        )}s`;
      }
    };

    if (!duration) {
      draw(1);
      return;
    }

    draw(0);
    const started = performance.now();
    const step = (now: number) => {
      const progress = Math.min(1, (now - started) / duration);
      draw(progress);
      stepAnimRef.current = progress < 1 ? requestAnimationFrame(step) : null;
    };
    stepAnimRef.current = requestAnimationFrame(step);

    return () => {
      if (stepAnimRef.current !== null) {
        cancelAnimationFrame(stepAnimRef.current);
        stepAnimRef.current = null;
      }
    };
  }, [frameIndex, game, speed]);

  // Continuous playback loop
  useEffect(() => {
    if (!playing || !game) return;
    if (stepAnimRef.current !== null) {
      cancelAnimationFrame(stepAnimRef.current);
      stepAnimRef.current = null;
    }

    const pace = speed;
    const reducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const anchorFrame = frameIndexRef.current;
    const anchorTime = performance.now() - playbackFractionRef.current * pace;
    const { xy } = computeCourtGeometry(game.court);

    const paintPlaybackCourt = (idx: number, progress: number) => {
      const svg = svgRef.current;
      if (!svg) return;
      const current = game.frames[idx]?.state;
      const next = game.frames[idx + 1]?.state;
      if (!current || !next) return;
      const fromPos = getCourtPlayerPositions(current, xy);
      const toPos = getCourtPlayerPositions(next, xy);
      if (!fromPos || !toPos) return;

      svg.querySelectorAll<SVGGElement>(".court-player").forEach((node) => {
        const id = node.dataset.player;
        if (!id) return;
        const start = fromPos.get(id);
        const end = toPos.get(id);
        if (!start || !end) return;
        const position: [number, number] = [
          start[0] + (end[0] - start[0]) * progress,
          start[1] + (end[1] - start[1]) * progress,
        ];
        node.setAttribute(
          "transform",
          `translate(${position[0]} ${position[1]})`
        );
        displayedPositionsRef.current.set(id, position);
      });

      const ballStart = getBallTargetPosition(current, xy);
      const ballEnd = getBallTargetPosition(next, xy);
      const ball: [number, number] = [
        ballStart[0] + (ballEnd[0] - ballStart[0]) * progress,
        ballStart[1] + (ballEnd[1] - ballStart[1]) * progress,
      ];
      const ballGroup = svg.querySelector<SVGGElement>(
        'g[aria-label="Basketball"]'
      );
      ballGroup?.setAttribute("transform", `translate(${ball[0]} ${ball[1]})`);
      displayedPositionsRef.current.set("__ball__", ball);

      if (
        current.phase === next.phase &&
        typeof current.game_clock_s === "number" &&
        typeof next.game_clock_s === "number" &&
        clockNodeRef.current?.firstChild
      ) {
        clockNodeRef.current.firstChild.nodeValue = clock(
          current.game_clock_s +
            (next.game_clock_s - current.game_clock_s) * progress
        );
      }
      if (
        typeof current.shot_clock_s === "number" &&
        current.shot_clock_s >= next.shot_clock_s &&
        shotClockNodeRef.current
      ) {
        shotClockNodeRef.current.textContent = `${fmt(
          current.shot_clock_s +
            (next.shot_clock_s - current.shot_clock_s) * progress,
          1
        )}s`;
      }
    };

    const tick = (now: number) => {
      const elapsed = Math.max(0, now - anchorTime);
      const nextIndex = Math.min(
        game.frames.length - 1,
        anchorFrame + Math.floor(elapsed / pace)
      );
      if (nextIndex === game.frames.length - 1) {
        playbackFractionRef.current = 0;
        setFrameIndex(nextIndex);
        setPlaying(false);
        playbackRafRef.current = null;
        return;
      }
      if (nextIndex !== frameIndexRef.current) {
        frameIndexRef.current = nextIndex;
        setFrameIndex(nextIndex);
      }
      const frac = (elapsed / pace) % 1;
      playbackFractionRef.current = frac;
      if (!reducedMotion) {
        paintPlaybackCourt(nextIndex, frac);
      }
      playbackRafRef.current = requestAnimationFrame(tick);
    };

    playbackRafRef.current = requestAnimationFrame(tick);
    return () => {
      if (playbackRafRef.current !== null) {
        cancelAnimationFrame(playbackRafRef.current);
        playbackRafRef.current = null;
      }
    };
  }, [game, playing, speed]);

  // Pause on visibilitychange
  useEffect(() => {
    const onVis = () => {
      if (document.hidden) pausePlayback();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [pausePlayback]);

  // Keyboard shortcuts: Space, ArrowRight, ArrowLeft
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!game) return;
      const target = event.target as HTMLElement | null;
      if (
        target?.closest(
          "input,select,textarea,button,[role=button],summary,a"
        )
      ) {
        return;
      }
      if (event.code === "Space") {
        event.preventDefault();
        if (playing) {
          pausePlayback();
        } else {
          if (frameIndexRef.current === game.frames.length - 1) {
            goFrame(0, false);
          }
          setPlaying(true);
        }
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        pausePlayback();
        goFrame(frameIndexRef.current + 1, true);
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        pausePlayback();
        goFrame(frameIndexRef.current - 1, true);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [game, goFrame, pausePlayback, playing]);

  const availableGames: GameSummaryRow[] = useMemo(() => {
    return [
      ...experiment.games.filter((g) => g.available),
      ...(experiment.unexported_games ?? []).filter((g) => g.available),
    ];
  }, [experiment.games, experiment.unexported_games]);

  const moments = useMemo(() => {
    if (!game) return [];
    return game.frames
      .map((f, i) => ({ f, i }))
      .filter(
        ({ f }) =>
          f.resolution?.scoring_events?.length ||
          f.resolution?.turnovers?.length ||
          (f.referee?.decision?.call && f.referee.decision.call !== "NONE")
      );
  }, [game]);

  const scoreSeries = useMemo(() => {
    if (!game) return null;
    return {
      series: (["A", "B"] as const).map((t) => ({
        label: conditionLabel(experiment.conditions, game.conditions[t]),
        color: teamColor(t),
        values: game.frames.map((row) => row.state.score[t]),
      })),
      labels: game.frames.map((row) => String(row.event_idx)),
    };
  }, [experiment.conditions, game, teamColor]);

  if (error) {
    return (
      <div className="loading-state">
        <h1>This view couldn’t load.</h1>
        <p>{error}</p>
        <Link
          className="button"
          href={`/experiments/${encodeURIComponent(experiment.experiment_id)}`}
          style={{ marginTop: "20px" }}
        >
          Return to overview
        </Link>
      </div>
    );
  }

  if (!game) {
    return (
      <div className="loading-state">
        <span className="spinner" />
        <h1>Loading the court</h1>
        <p>Reading the recorded states and event evidence.</p>
      </div>
    );
  }

  const f = game.frames[frameIndex];
  const s = f.state;
  const geom = computeCourtGeometry(game.court);
  const playersSorted: PlayerState[] = Object.values(s.players).sort((a, b) =>
    a.id.localeCompare(b.id)
  );
  const actor = eventActor(game, f, frameIndex);
  const cues = eventCues(game, f, frameIndex);

  const lastIdx = game.frames.length - 1;
  const span = Math.min(timelineSpan, game.frames.length);
  const windowEnd = Math.min(lastIdx, timelineStart + span - 1);

  const handleTogglePlay = () => {
    if (playing) {
      pausePlayback();
      return;
    }
    if (frameIndex === game.frames.length - 1) {
      goFrame(0, false);
    }
    setPlaying(true);
  };

  const handleNextScore = () => {
    pausePlayback();
    const index = game.frames.findIndex(
      (fr, i) => i > frameIndex && fr.resolution?.scoring_events?.length
    );
    if (index >= 0) {
      goFrame(index);
    } else {
      showToast("No further scoring events in this game.");
    }
  };

  const handleShareEvent = async () => {
    const url = new URL(window.location.href);
    url.searchParams.set("event", String(f.event_idx));
    window.history.replaceState(null, "", url.toString());
    try {
      await navigator.clipboard.writeText(url.toString());
      showToast("Link copied to this recorded event.");
    } catch {
      showToast("The address bar now links to this event.");
    }
  };

  const disabledCommsTeams = Object.entries(game.coordination || {})
    .filter(([, v]) => !v.comms)
    .map(([team]) => team);

  return (
    <>
      <PageHeading
        eyebrow="THE GAME, UNDER A MICROSCOPE"
        name="Back on the court."
        description="Scrub through recorded events. Select a player to follow their decision."
        actions={
          <Link
            className="button"
            href={`/experiments/${encodeURIComponent(
              experiment.experiment_id
            )}/games`}
          >
            ← Game library
          </Link>
        }
      />

      {game.warnings.map((w, idx) => (
        <div key={idx} className="callout warning">
          {w}
        </div>
      ))}

      <div className="replay-toolbar">
        <div className="filters">
          <select
            id="replay-game"
            className="replay-select"
            aria-label="Select game"
            value={game.id}
            onChange={(e) => {
              pausePlayback();
              router.push(
                `/experiments/${encodeURIComponent(
                  experiment.experiment_id
                )}/replay/${encodeURIComponent(e.target.value)}`
              );
            }}
          >
            {availableGames.map((g) => (
              <option key={g.id} value={g.id}>
                Seed {g.seed} · {g.first_possession} starts · {fmt(g.score.A, 0)}{" "}
                : {fmt(g.score.B, 0)}
                {g.unexported ? " (log only)" : ""}
              </option>
            ))}
          </select>
          <select
            id="possession-select"
            className="replay-select"
            aria-label="Jump to possession"
            value={activePossessionId(game, f, frameIndex)}
            onChange={(e) => {
              if (e.target.value) {
                pausePlayback();
                const index = possessionFrameIndex(game, e.target.value);
                if (index >= 0) goFrame(index);
              }
            }}
          >
            <option value="">Jump to possession…</option>
            {game.possessions.map((p) => (
              <option key={p.possession_id} value={p.possession_id}>
                {p.possession_id} · {p.physical_team} · {p.points} pts
              </option>
            ))}
          </select>
        </div>
        <div className="filters">
          <button
            id="trails-toggle"
            className="button small"
            aria-pressed={showTrails}
            onClick={() => setShowTrails((v) => !v)}
          >
            Movement trails {showTrails ? "on" : "off"}
          </button>
          <button
            id="share-event"
            className="button small"
            onClick={handleShareEvent}
          >
            Link to event ↗
          </button>
        </div>
      </div>

      <div className="replay-layout">
        <div>
          <section className="card court-card">
            <div id="scoreboard" className="scoreboard">
              <div className="score-team">
                <span>
                  <i className="dot" />{" "}
                  {conditionLabel(experiment.conditions, game.conditions.A)}
                </span>
                <strong className="score-digits">{s.score.A}</strong>
              </div>
              <div className="clock" ref={clockNodeRef}>
                {clock(s.game_clock_s)}
                <small>{s.phase === "OT" ? "OVERTIME" : "GAME CLOCK"}</small>
              </div>
              <div className="score-team">
                <strong className="score-digits">{s.score.B}</strong>
                <span>
                  {conditionLabel(experiment.conditions, game.conditions.B)}{" "}
                  <i className="dot orange" />
                </span>
              </div>
            </div>

            <div id="court" className="court-wrap">
              <div id="event-cue" className="event-cue" aria-live="off">
                {cues.map((cue, idx) => (
                  <span
                    key={idx}
                    className={`event-cue-badge ${cue.kind}`}
                  >
                    {cue.text}
                  </span>
                ))}
              </div>
              <svg
                ref={svgRef}
                className="court-svg"
                viewBox="0 0 800 600"
                role="img"
                aria-label={`Half-court positions after event ${f.event_idx}`}
              >
                <defs>
                  <pattern
                    id="court-grid"
                    width={geom.scale}
                    height={geom.scale}
                    patternUnits="userSpaceOnUse"
                    x={geom.ox}
                    y={geom.oy}
                  >
                    <path
                      d={`M ${geom.scale} 0 L 0 0 0 ${geom.scale}`}
                      fill="none"
                      stroke="#d4dfb7"
                      strokeOpacity=".045"
                    />
                  </pattern>
                  <clipPath id="court-clip">
                    <rect
                      x={geom.ox}
                      y={geom.oy}
                      width={geom.width * geom.scale}
                      height={geom.depth * geom.scale}
                    />
                  </clipPath>
                </defs>
                <rect
                  x={geom.ox}
                  y={geom.oy}
                  width={geom.width * geom.scale}
                  height={geom.depth * geom.scale}
                  fill="#264633"
                />
                <rect
                  x={geom.ox}
                  y={geom.oy}
                  width={geom.width * geom.scale}
                  height={geom.depth * geom.scale}
                  fill="url(#court-grid)"
                  stroke="#829c70"
                  strokeOpacity=".6"
                  strokeWidth="2"
                />
                <g
                  clipPath="url(#court-clip)"
                  fill="none"
                  stroke="#9db584"
                  strokeWidth="2"
                  strokeOpacity=".45"
                >
                  <path d={geom.arc} />
                  <rect
                    x={geom.basket[0] - (2.45 * geom.scale) / geom.cell}
                    y={geom.oy}
                    width={(4.9 * geom.scale) / geom.cell}
                    height={(5.8 * geom.scale) / geom.cell}
                    fill="#a6be84"
                    fillOpacity=".025"
                  />
                  <circle
                    cx={geom.basket[0]}
                    cy={geom.oy + (5.8 * geom.scale) / geom.cell}
                    r={(1.8 * geom.scale) / geom.cell}
                  />
                  <path
                    d={`M${geom.basket[0] - 32} ${geom.basket[1] - 12}h64`}
                    strokeWidth="4"
                  />
                  <circle
                    cx={geom.basket[0]}
                    cy={geom.basket[1]}
                    r="11"
                    stroke="#ead8a0"
                    strokeWidth="2.5"
                  />
                  <path
                    d={`M${geom.basket[0] - (1.25 * geom.scale) / geom.cell} ${
                      geom.basket[1]
                    } A${(1.25 * geom.scale) / geom.cell} ${
                      (1.25 * geom.scale) / geom.cell
                    } 0 0 0 ${
                      geom.basket[0] + (1.25 * geom.scale) / geom.cell
                    } ${geom.basket[1]}`}
                  />
                </g>
                <text
                  x="400"
                  y={geom.oy + geom.depth * geom.scale - 19}
                  textAnchor="middle"
                  fontSize="14"
                  fontWeight="600"
                  letterSpacing="6"
                  fill="#86a573"
                  opacity=".35"
                >
                  COURTSIDE
                </text>

                <g id="court-trails">
                  {showTrails
                    ? playersSorted.map((p) => {
                        const [baseX, baseY] = geom.xy(p.pos);
                        const [prevX, prevY] = geom.xy(p.prev_pos || p.pos);
                        if (prevX === baseX && prevY === baseY) return null;
                        const color = isOrangeTeam(p.team)
                          ? "#efb087"
                          : "#d1eea5";
                        return (
                          <React.Fragment key={p.id}>
                            <path
                              d={`M${prevX} ${prevY} L${baseX} ${baseY}`}
                              stroke={color}
                              strokeWidth="2"
                              strokeOpacity=".5"
                              strokeDasharray="5 5"
                            />
                            <circle
                              cx={prevX}
                              cy={prevY}
                              r="4"
                              fill={color}
                              opacity=".5"
                            />
                          </React.Fragment>
                        );
                      })
                    : null}
                </g>

                {playersSorted.map((p) => {
                  const color = isOrangeTeam(p.team) ? "#efb087" : "#d1eea5";
                  const holder = p.has_ball || s.ball.holder === p.id;
                  const action =
                    f.resolution?.actions?.[p.id] ||
                    p.movement ||
                    "No action recorded";
                  const toggleFocus = () => {
                    setFocusedPlayer((cur) => (cur === p.id ? null : p.id));
                    setInspectorTab("decisions");
                  };
                  return (
                    <g
                      key={p.id}
                      className="court-player"
                      data-player={p.id}
                      tabIndex={0}
                      role="button"
                      aria-label={`Inspect ${p.id}: ${title(action)}${
                        holder ? ", ball holder" : ""
                      }`}
                      aria-pressed={focusedPlayer === p.id}
                      onClick={toggleFocus}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          toggleFocus();
                        }
                      }}
                    >
                      <title>{`${p.id} · (${p.pos.join(", ")}) · ${title(
                        action
                      )}${holder ? " · ball holder" : ""}`}</title>
                      <circle
                        className="actor-ring"
                        r="28"
                        fill="none"
                        stroke="#ffd785"
                        strokeWidth="3"
                        display={actor === p.id ? "inline" : "none"}
                      />
                      <circle
                        className="holder-ring"
                        r="24"
                        fill="none"
                        stroke="#efc66e"
                        strokeWidth="2"
                        strokeDasharray="4 3"
                        display={holder ? "inline" : "none"}
                      />
                      <circle
                        className="player-disc"
                        r="18"
                        fill={color}
                        stroke={focusedPlayer === p.id ? "white" : "#23402f"}
                        strokeWidth={focusedPlayer === p.id ? 4 : 2}
                      />
                      <text
                        y="4"
                        textAnchor="middle"
                        fontSize="12"
                        fontWeight="700"
                        fill="#243c2a"
                      >
                        {p.id}
                      </text>
                    </g>
                  );
                })}

                <g aria-label="Basketball">
                  <circle
                    r="7"
                    fill="#e8aa56"
                    stroke="#5c472d"
                    strokeWidth="1.5"
                  />
                  <path d="M-6 0h12" stroke="#72502b" />
                </g>
                <text
                  x="400"
                  y="588"
                  textAnchor="middle"
                  fontSize="9"
                  letterSpacing="2"
                  fill="#91aa85"
                >
                  {`${geom.width} × ${geom.depth} GRID · RECORDED POSITIONS · ${s.ball.status}`}
                </text>
              </svg>
            </div>

            <div id="court-meta" className="court-meta">
              <span>
                SHOT CLOCK{" "}
                <strong ref={shotClockNodeRef}>
                  {fmt(s.shot_clock_s, 1)}s
                </strong>
              </span>
              <span>
                POSSESSION <strong>{s.offense}</strong>
                {s.needs_clear ? " · CLEAR REQUIRED" : ""}
              </span>
              <span>
                FOULS{" "}
                <strong>
                  A {s.team_fouls.A} / B {s.team_fouls.B}
                </strong>
              </span>
            </div>

            <div className="playback">
              <div className="timeline-label">
                <span id="timeline-current">
                  EVENT {f.event_idx} · {eventTitle(f, game.frames, frameIndex)}
                </span>
                <span id="timeline-total">
                  {game.frames.length - 1} recorded events
                </span>
              </div>

              <div className="timeline-tools">
                <button
                  id="timeline-prev"
                  className="button small"
                  type="button"
                  disabled={
                    timelineStart === 0 || !Number.isFinite(timelineSpan)
                  }
                  onClick={() => {
                    pausePlayback();
                    goFrame(Math.max(0, timelineStart - timelineSpan));
                  }}
                >
                  ← Earlier
                </button>
                <label htmlFor="timeline-zoom">Timeline</label>
                <select
                  id="timeline-zoom"
                  className="speed"
                  value={
                    Number.isFinite(timelineSpan) ? String(timelineSpan) : "all"
                  }
                  onChange={(e) => {
                    const v =
                      e.target.value === "all"
                        ? Infinity
                        : Number(e.target.value);
                    setTimelineSpan(v);
                    setTimelineStart(0);
                  }}
                >
                  <option value="40">40 events</option>
                  <option value="80">80 events</option>
                  <option value="all">Full game</option>
                </select>
                <button
                  id="timeline-next"
                  className="button small"
                  type="button"
                  disabled={
                    windowEnd === lastIdx || !Number.isFinite(timelineSpan)
                  }
                  onClick={() => {
                    pausePlayback();
                    goFrame(Math.min(lastIdx, timelineStart + timelineSpan));
                  }}
                >
                  Later →
                </button>
                <span id="timeline-window-label" className="mono">
                  Events {game.frames[timelineStart].event_idx}–
                  {game.frames[windowEnd].event_idx} of{" "}
                  {game.frames[lastIdx].event_idx}
                </span>
              </div>

              <input
                id="event-slider"
                className="range"
                type="range"
                min={timelineStart}
                max={windowEnd}
                value={frameIndex}
                step={1}
                aria-label="Recorded event in visible timeline window"
                aria-valuetext={`Event ${f.event_idx}: ${eventTitle(
                  f,
                  game.frames,
                  frameIndex
                )}`}
                onChange={(e) => {
                  pausePlayback();
                  goFrame(Number(e.target.value));
                }}
              />

              <div id="timeline-markers" className="timeline-markers">
                {game.frames
                  .slice(timelineStart, windowEnd + 1)
                  .map((fr, offset) => {
                    const kinds = momentKinds(fr);
                    if (!kinds.length) return null;
                    const i = timelineStart + offset;
                    const pct =
                      ((i - timelineStart) /
                        Math.max(windowEnd - timelineStart, 1)) *
                      100;
                    const label = `Event ${fr.event_idx}: ${kinds.join(
                      ", "
                    )} — ${eventTitle(fr, game.frames, i)}`;
                    return (
                      <button
                        key={fr.event_idx}
                        type="button"
                        className={`timeline-marker ${kinds[0]}`}
                        style={{ left: `${pct}%` }}
                        data-frame={i}
                        aria-label={label}
                        title={label}
                        onClick={() => {
                          pausePlayback();
                          goFrame(i);
                        }}
                      />
                    );
                  })}
              </div>

              <div className="timeline-legend">
                <span className="score">Score</span>
                <span className="turnover">Turnover</span>
                <span className="call">Referee call</span>
              </div>

              <div className="play-controls">
                <div className="play-buttons">
                  <button
                    id="previous-event"
                    className="button icon"
                    aria-label="Previous event"
                    disabled={frameIndex === 0}
                    onClick={() => {
                      pausePlayback();
                      goFrame(frameIndex - 1, true);
                    }}
                  >
                    ‹
                  </button>
                  <button
                    id="play-button"
                    className="button lime"
                    aria-label={playing ? "Pause replay" : "Play replay"}
                    onClick={handleTogglePlay}
                  >
                    {playing ? "Ⅱ Pause" : "▶ Play"}
                  </button>
                  <button
                    id="next-event"
                    className="button icon"
                    aria-label="Next event"
                    disabled={frameIndex === lastIdx}
                    onClick={() => {
                      pausePlayback();
                      goFrame(frameIndex + 1, true);
                    }}
                  >
                    ›
                  </button>
                  <button
                    id="next-score"
                    className="button small"
                    onClick={handleNextScore}
                  >
                    Next score ↗
                  </button>
                </div>
                <div className="filters">
                  <span className="key-hint">SPACE TO PLAY · ← → TO STEP</span>
                  <select
                    id="speed"
                    className="speed"
                    aria-label="Seconds per recorded event"
                    value={speed}
                    onChange={(e) => setSpeed(Number(e.target.value))}
                  >
                    <option value={1200}>1.2 s / event</option>
                    <option value={600}>0.6 s / event</option>
                    <option value={300}>0.3 s / event</option>
                    <option value={150}>0.15 s / event</option>
                  </select>
                </div>
              </div>
            </div>
          </section>

          <section className="card score-history">
            <div className="card-head">
              <div>
                <h3>The score over time</h3>
              </div>
              <Legend conditions={experiment.conditions} />
            </div>
            <div className="card-body" id="score-history">
              {scoreSeries ? (
                <LineChartSvg
                  series={scoreSeries.series}
                  labels={scoreSeries.labels}
                  percent={false}
                  height={135}
                  active={frameIndex}
                />
              ) : null}
            </div>
          </section>
        </div>

        <aside className="card inspector">
          <div className="inspector-header">
            <div className="eyebrow" id="inspector-event">
              EVENT {String(f.event_idx).padStart(3, "0")} /{" "}
              {clock(s.game_clock_s)}
            </div>
            <h2 id="inspector-title">
              {eventTitle(f, game.frames, frameIndex)}
            </h2>
            <p id="inspector-description">
              {f.event_idx === 0
                ? "The initial state, before any decisions."
                : `${
                    f.resolution?.possession_before?.possession_id ||
                    "Recorded event"
                  } · Court shows the state after resolution.`}
            </p>
          </div>
          <div
            className="inspector-tabs"
            role="tablist"
            aria-label="Event details"
          >
            {(["decisions", "team talk", "outcome"] as const).map((tab) => (
              <button
                key={tab}
                role="tab"
                data-tab={tab}
                aria-selected={tab === inspectorTab}
                className={tab === inspectorTab ? "active" : ""}
                onClick={() => setInspectorTab(tab)}
              >
                {title(tab)}
              </button>
            ))}
          </div>
          <div id="inspector-body" className="inspector-body" role="tabpanel">
            {inspectorTab === "decisions" ? (
              f.decisions.length ? (
                f.decisions.map((d, idx) => (
                  <div
                    key={idx}
                    className={`decision ${
                      focusedPlayer === d.player ? "active-player" : ""
                    }`}
                  >
                    <div className="decision-top">
                      <span
                        className={`player-badge ${
                          isOrangeTeam(d.team) ? "orange" : ""
                        }`}
                      >
                        {d.player}
                      </span>
                      <span className="decision-action">
                        {title(d.executed_action || "No action")}
                      </span>
                      <span className="muted">{d.executed_target || ""}</span>
                    </div>
                    <p>{d.rationale || "No rationale recorded."}</p>
                    {d.invalid_reason ? (
                      <small>
                        Remapped from {d.proposed_action} ·{" "}
                        {title(d.invalid_reason)}
                      </small>
                    ) : null}
                    {d.memory_ref ? <small>Memory: {d.memory_ref}</small> : null}
                  </div>
                ))
              ) : (
                <div className="empty-state">
                  No player decisions recorded for this event.
                </div>
              )
            ) : inspectorTab === "team talk" ? (
              <>
                <div className="channel-heading">Captain calls</div>
                {f.captain_calls.map((c, idx) => (
                  <div key={idx} className="message-card">
                    <div className="message-meta">
                      <span
                        className={`player-badge ${
                          isOrangeTeam(c.team) ? "orange" : ""
                        }`}
                      >
                        {c.team}
                      </span>
                      <strong>
                        {c.maintain ? "Maintain previous call" : "Captain"}
                      </strong>
                      {c.cs ? ` · ${c.cs}` : ""}
                    </div>
                    <p>{c.tactic || "No tactic recorded."}</p>
                    {(c.directives || []).map((d, dIdx) => (
                      <small key={dIdx}>
                        {d.to} → {d.act} {d.target || ""}
                      </small>
                    ))}
                  </div>
                ))}
                <div className="channel-heading">Teammate messages</div>
                {f.messages.map((m, idx) => (
                  <div
                    key={idx}
                    className={`message-card ${
                      m.suppressed ? "suppressed" : ""
                    }`}
                  >
                    <div className="message-meta">
                      <span
                        className={`player-badge ${
                          isOrangeTeam(m.team) ? "orange" : ""
                        }`}
                      >
                        {m.sender}
                      </span>
                      <span>
                        {m.kind}
                        {m.directive?.to ? ` → ${m.directive.to}` : ""}
                      </span>
                    </div>
                    <p>{m.text}</p>
                    <small>
                      {m.suppressed
                        ? "Suppressed · communication disabled"
                        : `Delivered at event ${
                            m.delivered_at ?? "not recorded"
                          }`}
                    </small>
                  </div>
                ))}
                {!f.messages.length ? (
                  <p className="chart-note">
                    No teammate messages recorded at this event.
                  </p>
                ) : null}
                {disabledCommsTeams.length ? (
                  <p className="chart-note" style={{ marginTop: "15px" }}>
                    Teammate communication is disabled for team{" "}
                    {disabledCommsTeams.join(", ")}. Captain calls are a
                    separate feature.
                  </p>
                ) : null}
              </>
            ) : (
              <>
                {[
                  [
                    "Possession before",
                    f.resolution?.possession_before
                      ? `${f.resolution.possession_before.possession_id} · ${f.resolution.possession_before.team}`
                      : "—",
                  ],
                  [
                    "Possession after",
                    f.resolution?.possession_after
                      ? `${f.resolution.possession_after.possession_id} · ${f.resolution.possession_after.team}`
                      : "—",
                  ],
                  [
                    "Referee call",
                    title(
                      f.referee?.decision?.foul_type ||
                        f.referee?.decision?.violation_type ||
                        f.referee?.decision?.call ||
                        "Not recorded"
                    ),
                  ],
                  ["Offender", f.referee?.decision?.offender || "—"],
                  [
                    "Cited rules",
                    (f.referee?.decision?.rule_ids_cited || []).join(", ") ||
                      "None",
                  ],
                  [
                    "Referee status",
                    f.referee?.failure_code ||
                      f.referee?.rejection_reason ||
                      "No recorded failure",
                  ],
                ].map(([k, v]) => (
                  <div key={k} className="outcome-row">
                    <span>{k}</span>
                    <strong>{v}</strong>
                  </div>
                ))}
                {(f.resolution?.scoring_events || []).map((e, idx) => (
                  <div
                    key={idx}
                    className="callout"
                    style={{ marginTop: "12px" }}
                  >
                    Team {e.team} +{e.points} · {title(e.source)}
                  </div>
                ))}
                {(f.resolution?.turnovers || []).map((e, idx) => (
                  <div
                    key={idx}
                    className="callout warning"
                    style={{ marginTop: "12px" }}
                  >
                    Turnover · {e.player || e.team} · {title(e.reason)}
                  </div>
                ))}
                <details className="raw-detail">
                  <summary>Recorded resolution</summary>
                  <pre>{JSON.stringify(f.resolution || {}, null, 2)}</pre>
                </details>
                <details className="raw-detail">
                  <summary>Referee reply &amp; retrieved rules</summary>
                  <pre>
                    {JSON.stringify(
                      {
                        retrieved: f.referee?.retrieved_chunk_ids,
                        reply: f.referee?.raw_output,
                        failure: f.referee?.parse_error,
                      },
                      null,
                      2
                    )}
                  </pre>
                </details>
              </>
            )}
          </div>
        </aside>
      </div>

      <div className="section-heading">
        <h2>Game moments</h2>
        <span className="muted" style={{ fontSize: "10px" }}>
          Scores, turnovers &amp; referee calls
        </span>
      </div>
      <div id="event-moments" className="event-buttons">
        {moments.length ? (
          moments.map(({ f: mf, i }) => (
            <button
              key={mf.event_idx}
              className={`event-chip ${i === frameIndex ? "active" : ""}`}
              data-frame={i}
              onClick={() => {
                pausePlayback();
                goFrame(i);
              }}
            >
              <small>{mf.event_idx}</small>
              {eventTitle(mf, game.frames, i)}
            </button>
          ))
        ) : (
          <p className="chart-note">
            No scoring, turnover or referee-call moments recorded.
          </p>
        )}
      </div>

      <div
        id="toast"
        role="status"
        aria-live="polite"
        className={toastMsg ? "visible" : ""}
      >
        {toastMsg || ""}
      </div>
    </>
  );
}

