import type { GameReplay, ReplayFrame } from "./types";
import { title } from "./format";

export function eventTitle(
  frame: ReplayFrame,
  frames?: ReplayFrame[],
  frameIdx?: number
): string {
  if (frame.event_idx === 0) return "Opening possession";
  const scores = frame.resolution?.scoring_events || [];
  if (scores.length) {
    return scores
      .map(
        (s) =>
          `${s.team} +${s.points} ${
            s.source === "FREE_THROW" ? "free throw" : "points"
          }`
      )
      .join(" · ");
  }
  const call = frame.referee?.decision;
  if (call && call.call && call.call !== "NONE") {
    return title(call.foul_type || call.violation_type || call.call);
  }
  const turnover = frame.resolution?.turnovers?.[0];
  if (turnover) {
    return `${turnover.team} · ${title(turnover.reason)}`;
  }
  let resolvedIdx = frameIdx;
  if (resolvedIdx === undefined && frames) {
    resolvedIdx = frames.indexOf(frame);
  }
  const before =
    frames && resolvedIdx !== undefined
      ? frames[Math.max(0, resolvedIdx - 1)]?.state
      : undefined;
  const holder = before?.ball?.holder;
  const action = holder ? frame.resolution?.actions?.[holder] : undefined;
  if (action) {
    return `${holder} · ${title(action)}`;
  }
  return frame.state.ball.status === "LOOSE"
    ? "Loose-ball phase"
    : "Resolved event";
}

export function possessionFrameIndex(game: GameReplay, id: string): number {
  if (game.possessions[0]?.possession_id === id) return 0;
  const after = game.frames.findIndex(
    (f) => f.resolution?.possession_after?.possession_id === id
  );
  if (after >= 0) return after;
  const possession = game.possessions.find((p) => p.possession_id === id);
  if (!possession) return -1;
  return game.frames.findIndex(
    (f) =>
      f.event_idx >= Number(possession.start_event_idx) &&
      f.state.offense === possession.physical_team
  );
}

export function activePossessionId(
  game: GameReplay,
  frame: ReplayFrame,
  frameIndex: number
): string {
  if (frameIndex === 0) return game.possessions[0]?.possession_id || "";
  const after = frame.resolution?.possession_after?.possession_id;
  if (after) return after;
  const event = frame.event_idx;
  const matched = [...game.possessions]
    .reverse()
    .find(
      (p) =>
        p.physical_team === frame.state.offense &&
        Number(p.start_event_idx) <= event &&
        (!p.end_event_idx || Number(p.end_event_idx) >= event)
    );
  return matched?.possession_id || "";
}

export function momentKinds(
  frame: ReplayFrame
): Array<"score" | "turnover" | "call"> {
  const kinds: Array<"score" | "turnover" | "call"> = [];
  if (frame.resolution?.scoring_events?.length) kinds.push("score");
  if (frame.resolution?.turnovers?.length) kinds.push("turnover");
  if (frame.referee?.decision?.call && frame.referee.decision.call !== "NONE") {
    kinds.push("call");
  }
  return kinds;
}

export function eventActor(
  game: GameReplay,
  frame: ReplayFrame,
  index: number
): string | null {
  if (index === 0) return null;
  const before = game.frames[index - 1]?.state?.ball?.holder;
  if (frame.resolution?.scoring_events?.length) {
    const act = before ? frame.resolution?.actions?.[before] : undefined;
    return before && act && ["SHOOT", "FREE_THROW"].includes(act)
      ? before
      : null;
  }
  const turnover = frame.resolution?.turnovers?.find((item) => item.player);
  if (turnover?.player) return turnover.player;
  const call = frame.referee?.decision;
  if (call?.call && call.call !== "NONE" && call.offender) {
    return call.offender;
  }
  return before && frame.resolution?.actions?.[before] ? before : null;
}

export interface EventCue {
  kind: "score" | "turnover" | "call" | "action";
  text: string;
}

export function eventCues(
  game: GameReplay,
  frame: ReplayFrame,
  index: number
): EventCue[] {
  if (index === 0) return [];
  const cues: EventCue[] = [];
  for (const score of frame.resolution?.scoring_events || []) {
    cues.push({
      kind: "score",
      text: `Team ${score.team} +${score.points} · ${title(score.source)}`,
    });
  }
  for (const turnover of frame.resolution?.turnovers || []) {
    cues.push({
      kind: "turnover",
      text: `Turnover ${turnover.player || turnover.team} · ${title(
        turnover.reason
      )}`,
    });
  }
  const call = frame.referee?.decision;
  if (call?.call && call.call !== "NONE") {
    cues.push({
      kind: "call",
      text: `${title(call.foul_type || call.violation_type || call.call)}${
        call.offender ? ` · ${call.offender}` : ""
      }`,
    });
  }
  if (!cues.length) {
    const actor = eventActor(game, frame, index);
    const action = actor ? frame.resolution?.actions?.[actor] : undefined;
    if (actor && action) {
      cues.push({
        kind: "action",
        text: `${actor} · ${title(action)}`,
      });
    }
  }
  return cues;
}

