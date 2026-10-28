import type { StudyMeasures } from "../../src/lib/types";

export const METRIC_ENTRIES: Array<[string, [string, string, boolean]]> = [
  ["ppp", ["Points per possession", "Points scored / completed possessions", false]],
  ["maar", ["Message alignment", "Actions aligned with teammate messages", true]],
  ["ccar", ["Captain alignment", "Actions aligned with captain directives", true]],
  ["cssr", ["Strategy selection", "Tactic calls using a valid coordination strategy", true]],
  ["maur", ["Memory usage", "Decisions referencing shared memory", true]],
  ["grounded_maur", ["Grounded memory usage", "Memory references grounded in context", true]],
  ["iar", ["Invalid actions", "Invalid proposed actions / all decisions; lower is better", true]],
  [
    "coordination_conflict_rate",
    ["Coordination conflicts", "Same-zone coordination conflicts", true],
  ],
];

export const LABELS: Record<string, string> = {
  A_full: "Full system",
  A_full_B: "Full system (Side B)",
  B_no_comm: "No communication",
  C_no_captain: "No captain",
  D_read_only: "Read-only memory",
};

export const FEATURES: Record<string, string> = {
  comms: "Communication",
  captain: "Captain",
  memory_write: "Memory updates",
};

export const FEATURE_ORDER = ["comms", "captain", "memory_write"] as const;

export const INCLUDED_SEEDS = new Set([
  "101",
  "102",
  "103",
  "106",
  "107",
  "108",
  "109",
  "110",
]);

export const MATCHUP_MEASURES: Record<string, StudyMeasures> = {
  A_full_B: {
    primary: ["ppp", "maar", "ccar", "maur", "cssr"],
    context: [],
    adaptation: ["ppp", "maur", "cssr"],
    note:
      "Mirror control experiment: both physical teams (A and B) run the Full System " +
      "configuration across paired first-possession seeds.",
  },
  B_no_comm: {
    primary: ["ppp", "maar"],
    context: ["ccar"],
    adaptation: ["ppp", "maur", "cssr"],
    note:
      "Message alignment applies to the communicating condition. " +
      "Captain alignment remains useful context for both conditions.",
  },
  C_no_captain: {
    primary: ["ppp", "ccar"],
    context: [],
    adaptation: ["ppp"],
    note:
      "Captain alignment applies only where captain directives are enabled. " +
      "Strategy selection is not evaluated for the no-captain condition.",
  },
  D_read_only: {
    primary: ["ppp", "maur", "cssr"],
    context: [],
    adaptation: ["maur", "cssr", "ppp"],
    note:
      "The read-only condition can reference initial memory but cannot write " +
      "new memory or strategies. Interpret its strategy selection with that constraint.",
  },
};

