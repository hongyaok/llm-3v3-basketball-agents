import type { GameReplay, ReplayFrame, TeamId } from "./types";
import { title } from "./format";

export interface TurnoverDetail {
  reason: string;
  team: TeamId;
  victim: string;
  stealer: string | null;
  newHolder: string | null;
  newTeam: TeamId;
  message: string;
  subtext: string;
}

export function formatTurnoverDetail(
  frame: ReplayFrame,
  beforeFrame?: ReplayFrame
): TurnoverDetail | null {
  const turnover = frame.resolution?.turnovers?.[0];
  if (!turnover) return null;
  const victim =
    turnover.player ||
    beforeFrame?.state?.ball?.holder ||
    `Team ${turnover.team}`;
  const newHolder = frame.state.ball.holder || null;
  const newTeam: TeamId =
    frame.state.offense || (turnover.team === "A" ? "B" : "A");
  const reason = turnover.reason || "TURNOVER";

  if (reason === "STEAL" || reason === "STRIP") {
    const stealer =
      newHolder ||
      (victim ? frame.resolution?.involved_opponents?.[victim]?.[0] : null) ||
      null;
    const message =
      stealer && victim
        ? `Turnover: ${stealer} stole ball from ${victim}`
        : stealer
        ? `Turnover: ${stealer} stole ball`
        : `Turnover: ${victim} lost ball`;
    const subtext = `${
      reason === "STRIP" ? "Strip steal" : "Steal"
    } · Possession to Team ${newTeam}${
      newHolder && newHolder !== stealer ? ` (${newHolder})` : ""
    }`;
    return {
      reason,
      team: turnover.team,
      victim,
      stealer,
      newHolder,
      newTeam,
      message,
      subtext,
    };
  }

  if (reason === "OOB_TURNOVER") {
    return {
      reason,
      team: turnover.team,
      victim,
      stealer: null,
      newHolder,
      newTeam,
      message: `Turnover: ${victim} out of bounds`,
      subtext: `Out of bounds · Possession to Team ${newTeam}${
        newHolder ? ` (${newHolder})` : ""
      }`,
    };
  }

  if (reason === "SHOT_CLOCK") {
    return {
      reason,
      team: turnover.team,
      victim,
      stealer: null,
      newHolder,
      newTeam,
      message: `Turnover: ${victim} shot clock violation`,
      subtext: `Shot clock expired · Possession to Team ${newTeam}${
        newHolder ? ` (${newHolder})` : ""
      }`,
    };
  }

  if (reason === "OFFENSIVE_FOUL") {
    const offender = frame.referee?.decision?.offender || victim;
    const fouled = frame.referee?.decision?.fouled_player;
    return {
      reason,
      team: turnover.team,
      victim: offender,
      stealer: fouled || null,
      newHolder,
      newTeam,
      message: `Turnover: ${offender} offensive foul${
        fouled ? ` on ${fouled}` : ""
      }`,
      subtext: `Offensive foul · Possession to Team ${newTeam}${
        newHolder ? ` (${newHolder})` : ""
      }`,
    };
  }

  if (reason === "REFEREE_VIOLATION") {
    const offender = frame.referee?.decision?.offender || victim;
    const vType = title(
      frame.referee?.decision?.violation_type || "violation"
    ).toLowerCase();
    return {
      reason,
      team: turnover.team,
      victim: offender,
      stealer: null,
      newHolder,
      newTeam,
      message: `Turnover: ${offender} ${vType} violation`,
      subtext: `Referee violation · Possession to Team ${newTeam}${
        newHolder ? ` (${newHolder})` : ""
      }`,
    };
  }

  return {
    reason,
    team: turnover.team,
    victim,
    stealer: null,
    newHolder,
    newTeam,
    message: `Turnover: ${victim} · ${title(reason)}`,
    subtext: `Possession to Team ${newTeam}${
      newHolder ? ` (${newHolder})` : ""
    }`,
  };
}

export interface ShotEventDescriptor {
  kind: "score" | "miss" | "rebound" | "turnover";
  actor: string;
  team: TeamId;
  points?: number;
  source?: string;
  assistBy?: string | null;
  nextRebounder?: string | null;
  missedShooter?: string | null;
  isOffensiveRebound?: boolean;
  victim?: string | null;
  stealer?: string | null;
  turnoverReason?: string | null;
  message: string;
  subtext: string;
}

export function describeShotEvent(
  game: GameReplay,
  frameIndex: number
): ShotEventDescriptor | null {
  if (frameIndex <= 0 || frameIndex >= game.frames.length) return null;
  const frame = game.frames[frameIndex];
  const prev = game.frames[frameIndex - 1];
  const shot = frame.resolution?.shots?.[0];
  const scoreEvent = frame.resolution?.scoring_events?.[0];

  // 1. Made shot (field goal or free throw)
  if ((shot && shot.made) || (!shot && scoreEvent)) {
    const team: TeamId =
      shot?.team || scoreEvent?.team || frame.state.offense || "A";
    const actor =
      shot?.shooter ||
      frame.referee?.decision?.fouled_player ||
      prev?.state.ball.holder ||
      `Team ${team}`;
    const points = scoreEvent?.points ?? 1;
    const source = scoreEvent?.source || "FIELD_GOAL";
    const assistBy = shot?.assist_by || null;
    const pointWord = points === 1 ? "point" : "points";
    const message = `${actor} scored ${points} ${pointWord}`;
    const subtext =
      source === "FREE_THROW"
        ? `Team ${team} +${points} · Free throw`
        : assistBy
        ? `Team ${team} +${points} · Assisted by ${assistBy}`
        : `Team ${team} +${points} · ${title(source)}`;
    return {
      kind: "score",
      actor,
      team,
      points,
      source,
      assistBy,
      message,
      subtext,
    };
  }

  // 2. Missed shot
  if (shot && !shot.made) {
    const actor = shot.shooter;
    const team = shot.team;
    const isLoose = frame.state.ball.status === "LOOSE";
    const nextFrame = game.frames[frameIndex + 1];
    const nextRebounder = isLoose
      ? nextFrame?.state.ball.holder || null
      : null;
    const turnoverDetail = formatTurnoverDetail(frame, prev);
    const message = `${actor} Missed`;
    const subtext = isLoose
      ? nextRebounder
        ? `Rebound next · ${nextRebounder}`
        : "Loose ball at the rim"
      : turnoverDetail
      ? turnoverDetail.message
      : "Shot missed";
    return {
      kind: "miss",
      actor,
      team,
      nextRebounder,
      message,
      subtext,
    };
  }

  // 3. Rebound immediately following a missed-shot loose ball
  if (prev?.state.ball.status === "LOOSE" && frame.state.ball.holder) {
    const actor = frame.state.ball.holder;
    const team: TeamId =
      frame.state.players[actor]?.team || frame.state.offense || "A";
    const prevShot = prev.resolution?.shots?.[0];
    const missedShooter = prevShot?.shooter || null;
    const isOffensiveRebound = prevShot ? prevShot.team === team : false;
    const message = `${actor} Rebound`;
    const subtext = `${
      isOffensiveRebound ? "Offensive" : "Defensive"
    } rebound${missedShooter ? ` · after ${missedShooter} miss` : ""}`;
    return {
      kind: "rebound",
      actor,
      team,
      missedShooter,
      isOffensiveRebound,
      message,
      subtext,
    };
  }

  // 4. Turnover (steal, strip, out of bounds, shot clock, offensive foul, etc.)
  const turnoverDetail = formatTurnoverDetail(frame, prev);
  if (turnoverDetail) {
    return {
      kind: "turnover",
      actor: turnoverDetail.stealer || turnoverDetail.victim,
      team: turnoverDetail.team,
      victim: turnoverDetail.victim,
      stealer: turnoverDetail.stealer,
      turnoverReason: turnoverDetail.reason,
      message: turnoverDetail.message,
      subtext: turnoverDetail.subtext,
    };
  }

  return null;
}

export interface FoulCallDescriptor {
  foulType: string;
  offender: string | null;
  offenderTeam: TeamId | null;
  fouledPlayer: string | null;
  rules: string[];
  tag: string;
  message: string;
  subtext: string;
}

export function describeFoulCall(
  game: GameReplay,
  frameIndex: number
): FoulCallDescriptor | null {
  if (frameIndex <= 0 || frameIndex >= game.frames.length) return null;
  const frame = game.frames[frameIndex];
  const decision = frame.referee?.decision;
  if (!decision || decision.call !== "FOUL") return null;

  const foulType = decision.foul_type || "FOUL";
  const offender = decision.offender || null;
  const fouledPlayer = decision.fouled_player || null;
  const rules = decision.rule_ids_cited || [];
  const offenderTeam: TeamId | null =
    (offender && frame.state.players[offender]?.team) ||
    (offender?.startsWith("A")
      ? "A"
      : offender?.startsWith("B")
      ? "B"
      : null);

  const foulLabel = title(foulType).toLowerCase();
  const tag =
    foulType === "OFFENSIVE_FOUL"
      ? "REFEREE · OFFENSIVE FOUL"
      : foulType === "DEFENSIVE_FOUL"
      ? "REFEREE · DEFENSIVE FOUL"
      : "REFEREE · FOUL";

  const message = offender
    ? `${offender} ${foulLabel}${fouledPlayer ? ` on ${fouledPlayer}` : ""}`
    : `${title(foulType)}${fouledPlayer ? ` on ${fouledPlayer}` : ""}`;

  const parts: string[] = [];
  if (offenderTeam && frame.state.team_fouls) {
    parts.push(`Team ${offenderTeam} fouls: ${frame.state.team_fouls[offenderTeam]}`);
  }
  const ftScore = frame.resolution?.scoring_events?.find(
    (s) => s.source === "FREE_THROW"
  );
  if (ftScore) {
    parts.push(`Free throw +${ftScore.points}`);
  } else if (frame.resolution?.turnovers?.length) {
    const newTeam: TeamId =
      frame.state.offense || (offenderTeam === "A" ? "B" : "A");
    parts.push(`Possession to Team ${newTeam}`);
  } else if (frame.state.offense) {
    parts.push(`Team ${frame.state.offense} retains ball`);
  }
  if (rules.length) {
    parts.push(rules.join(", "));
  }

  return {
    foulType,
    offender,
    offenderTeam,
    fouledPlayer,
    rules,
    tag,
    message,
    subtext: parts.join(" · ") || "Referee foul call",
  };
}

export function eventTitle(
  frame: ReplayFrame,
  frames?: ReplayFrame[],
  frameIdx?: number
): string {
  if (frame.event_idx === 0) return "Opening possession";
  let resolvedIdx = frameIdx;
  if (resolvedIdx === undefined && frames) {
    resolvedIdx = frames.indexOf(frame);
  }
  const before =
    frames && resolvedIdx !== undefined
      ? frames[Math.max(0, resolvedIdx - 1)]
      : undefined;

  const shot = frame.resolution?.shots?.[0];
  const scores = frame.resolution?.scoring_events || [];
  if (scores.length) {
    const s = scores[0];
    const shooter =
      shot?.shooter ||
      frame.referee?.decision?.fouled_player ||
      before?.state?.ball?.holder;
    if (shooter) {
      return `${shooter} scored ${s.points} ${
        s.points === 1 ? "point" : "points"
      }`;
    }
    return scores
      .map(
        (sc) =>
          `${sc.team} +${sc.points} ${
            sc.source === "FREE_THROW" ? "free throw" : "points"
          }`
      )
      .join(" · ");
  }

  if (shot && !shot.made) {
    return `${shot.shooter} Missed`;
  }

  if (before?.state?.ball?.status === "LOOSE" && frame.state.ball.holder) {
    return `${frame.state.ball.holder} Rebound`;
  }

  const turnoverDetail = formatTurnoverDetail(frame, before);
  if (turnoverDetail) {
    return turnoverDetail.message;
  }

  const call = frame.referee?.decision;
  if (call && call.call && call.call !== "NONE") {
    return title(call.foul_type || call.violation_type || call.call);
  }
  const holder = before?.state?.ball?.holder;
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
  const shotDesc = describeShotEvent(game, index);
  if (shotDesc) {
    return shotDesc.actor;
  }
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
  kind: "score" | "miss" | "rebound" | "turnover" | "call" | "action";
  text: string;
}

export function eventCues(
  game: GameReplay,
  frame: ReplayFrame,
  index: number
): EventCue[] {
  if (index === 0) return [];
  const cues: EventCue[] = [];
  const shotDesc = describeShotEvent(game, index);
  if (shotDesc) {
    cues.push({
      kind: shotDesc.kind,
      text: shotDesc.message,
    });
  } else {
    for (const score of frame.resolution?.scoring_events || []) {
      cues.push({
        kind: "score",
        text: `Team ${score.team} +${score.points} · ${title(score.source)}`,
      });
    }
  }
  if (shotDesc?.kind !== "turnover" && frame.resolution?.turnovers?.length) {
    const detail = formatTurnoverDetail(frame, game.frames[index - 1]);
    if (detail) {
      cues.push({
        kind: "turnover",
        text: detail.message,
      });
    }
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

