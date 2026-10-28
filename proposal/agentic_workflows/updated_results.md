# Updated Results (Seeds 106–110) and Foul Popup: Implementation Plan

Status: **plan only. No code has been changed yet.**

## 1. Goals

1. Swap the frontend dataset (overview, games library, comparisons, plots, downloads, replays) over to the **new results**, using **seeds 106–110 only**.
2. Add a **foul popup** to the replay court view. It should work like the existing score banner (`+2 PTS`).

---

## 2. Findings: what changed in `results/`

### 2.1 New archives (untracked) and removed archives (deleted in the working tree)

| New archive | Layout | Contents |
|---|---|---|
| `abl_captain_v1.zip` | `export/<game_id>.jsonl` + `manifest.mf` | s106–s110, A and B (10 logs) |
| `abl_memory_v1.zip` | `export/<game_id>.jsonl` + `manifest.mf` | s106–s110, A and B (10 logs) |
| `abl_comms_v1.zip` | `export/<game_id>.jsonl` + `manifest.mf` | **s107–s110 only** (8 logs). **s106 is missing** |
| `primary_s104_110.zip` | `primary_s104_110/<exp>/{export,plots,stats.json}` + `manifest.mf` | Summary tables for **s104–s110** (14 games per experiment) |

Deleted: the 16 old per-seed log zips (`abl_*_v1_s10X.zip`) and `interim_31games.zip`. Copies of the old ones still exist in `frontend/results/` and in git `HEAD`.

### 2.2 What is different from the old structure

- **Log zips are now one per experiment, not one per seed.** Logs now sit under an `export/` folder, and each zip has an extra `manifest.mf` file. [build-data.ts](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/frontend/scripts/build-data.ts#L151-L162) already keys logs by `basename(entry)` and skips non-`.jsonl` entries, so this part parses as-is.
- **The summary covers seeds 104–110, not the 106–110 you asked for.** `games.csv`, `teams.csv` and `possessions.csv` can be filtered by seed. But `stats.json` (bootstrap/Wilcoxon over 7 seeds), `plots/adaptation.csv` and the comparison PNGs were **computed over 7 seeds**. Filtering the rows alone would leave the overview and comparison numbers out of step with the game list.
- **Comms s106 logs are missing from the new comms zip.** I checked the old `abl_comms_v1_s106.zip` (still in `frontend/results/` and git `HEAD`) against the new summary rows. It is the same run: same `config_hash` `739fea14…`, final scores 2–12 (A) and 22–9 (B), and end reasons match. So it can supply the s106 comms replays.
- **The JSONL schema is unchanged** (same record types and `game_start` keys), so [replay.ts](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/frontend/scripts/lib/replay.ts) needs no changes.
- **The `games.csv` columns are unchanged** compared with `interim_31games`.
- **Pipeline blockers:**
  - [`buildDataFromDirectory`](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/frontend/scripts/build-data.ts#L82-L358) accepts **exactly one** summary zip.
  - [sync-results.ts](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/frontend/scripts/sync-results.ts) copies **every** `results/*.zip` with no filtering.
  - Copying the raw uploads directly would pull in s104/s105 rows, and any leftover old zips would cause duplicate-log errors.

### 2.3 Referee calls in the new logs (all 28 games, seeds 106–110)

| Call | Same-frame outcome | Count |
|---|---|---|
| `FOUL / OFFENSIVE_FOUL` | turnover `OFFENSIVE_FOUL` | 189 |
| `FOUL / DEFENSIVE_FOUL` | nothing else (ball retained, team foul) | 77 |
| `FOUL / OFFENSIVE_FOUL` | missed shot + turnover | 26 |
| `FOUL / OFFENSIVE_FOUL` | **made field goal** + turnover | 22 |
| `FOUL / DEFENSIVE_FOUL` | **free-throw score** | 11 |
| `FOUL / OFFENSIVE_FOUL` | no turnover | 7 |
| `VIOLATION / STALLING` | turnover `REFEREE_VIOLATION` | 2 |

Today a foul only shows as a small `call` cue badge, plus a `TURNOVER` banner when it is offensive. Defensive fouls (88 events) get **no popup at all**. A foul often lands on the same frame as a score, so the foul popup has to be able to **sit alongside** the score banner.

---

## 3. Part A: data pipeline (seeds 106–110 only)

### Recommended approach: rebuild the summary bundle from the raw logs for 106–110

The repo's own analysis CLI ([cli.py](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/src/bball3x3/cli.py#L138-L195): `bball export`, `bball stats`, `bball plots`) can regenerate tables, stats and plots from the JSONL logs. This keeps stats, plots and the game list consistent at 5 paired seeds (10 games) per experiment.

#### A1. New script `scripts/build_frontend_results.py` (Python, run via `uv run`)

Inputs come from `results/`. The script is deterministic and the seed set is configurable (`--seeds 106-110`, default 106–110).

1. **Collect logs.** Extract `export/*.jsonl` from `abl_{captain,comms,memory}_v1.zip`. Keep only `game_id`s matching `_s(106|107|108|109|110)_[AB]$`. Add `abl_comms_v1_s106_{A,B}.jsonl` from the legacy archive (see open question Q2).
2. **Check completeness.** Fail if any experiment has fewer than 10 logs (5 seeds × A/B), or if a duplicate `game_id` is found.
3. **Regenerate per experiment** into a temp dir laid out as `results_s106_110/<exp>/`:
   - `bball export <exp>/export <logs…>` (defaults: `--window 1`, complete games only, the same as the uploaded manifest)
   - `bball stats <exp>/export <exp>/stats.json` (defaults: baseline `A_full`, analysis seed `4213`, 10 000 replicates, the same as the uploaded `stats.json`)
   - `bball plots <exp>/export <exp>/plots`
4. **Parity check against the upload.** For every 106–110 game, the regenerated `games.csv`, `teams.csv` and `possessions.csv` rows must equal the matching rows in `primary_s104_110.zip`, comparing all columns except volatile ones if any (e.g. `code_commit`). Per-game rows don't depend on other seeds, so they should match exactly. Abort on mismatch.
5. **Write the frontend bundle** to `frontend/results/`. First delete the old `abl_*_s10X.zip` and `interim_31games.zip` there. Then write:
   - `results_s106_110.zip`: the summary, in the same `<root>/<exp>/…` layout as `interim_31games.zip`, so `build-data.ts` reads it without changes
   - `abl_captain_v1_s106_110.zip`, `abl_comms_v1_s106_110.zip`, `abl_memory_v1_s106_110.zip`: flat `<game_id>.jsonl` logs (10 each)
   - `CHECKSUMS.sha256`, regenerated

> [!NOTE]
> The raw uploads in `results/` stay untouched as the source of truth. Only the filtered bundle is committed to `frontend/results/`, which is what Vercel builds from.

#### A2. Pipeline guards in [build-data.ts](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/frontend/scripts/build-data.ts)

- Add `INCLUDED_SEEDS = [106,107,108,109,110]` in [constants.ts](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/frontend/scripts/lib/constants.ts) as a safety net. Throw if any `games.csv` row or log has a seed outside the set, so stale archives can never leak in silently.
- Remove the **fallback that copies `../results/*.zip`** ([L44–L62](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/frontend/scripts/build-data.ts#L44-L62)) and replace it with a clear error: "run `npm run sync-results`". Otherwise the raw uploads (s104/s105 and `primary_s104_110.zip`) would be picked up.
- Bump `PIPELINE_VERSION` to `1.1.0` so the `.stamp` cache is invalidated.

#### A3. [sync-results.ts](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/frontend/scripts/sync-results.ts)

Change `npm run sync-results` to call the Python bundler (`uv run python ../scripts/build_frontend_results.py`) and then copy `system_architecture.html`. It should no longer copy every zip blindly.

#### A4. Hard-coded copy and defaults in the UI

| File | Change |
|---|---|
| [LandingClient.tsx](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/frontend/src/components/LandingClient.tsx) L293 | `3 STUDIES · 31 GAMES` → computed from the catalog (expected **30 games**) |
| LandingClient.tsx L155 | Remove the "+ 1 log-only possession replay" wording, or derive it from data (expected 0 log-only games) |
| LandingClient.tsx L58, L69 | Fallback game `…_s101_A` → first game in the catalog (no hard-coded seed) |
| [GameLibraryClient.tsx](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/frontend/src/components/GameLibraryClient.tsx) L110 | Tooltip naming `interim_31games` → generic "not in the exported summary tables" |
| Any methods or overview copy that mentions "interim" or 31 games | Change to "Seeds 106–110 (5 paired seeds × 3 ablations)" |

#### A5. Tests

- [parity.test.ts](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/frontend/tests/parity/parity.test.ts):
  - `source_zip` → `results_s106_110.zip`
  - `unexported_logs` → `[]`
  - Default replay IDs → `…_s106_A`
  - Replace the "log-only s106_B" test with "s106_B is exported, score 22–9"
- Regenerate [golden.json](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/frontend/tests/parity/golden.json).
- [routes.test.ts](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/frontend/tests/unit/routes.test.ts): change the route lists from s101 to s106, and drop the log-only assumption.
- New test: the catalog has exactly seeds 106–110 in each experiment, with 10 replays each.

---

## 4. Part B: foul popup in the replay view

### B1. Logic: `describeRefereeCall(game, frameIndex)` in [replay-logic.ts](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/frontend/src/lib/replay-logic.ts)

It returns `null` unless `frame.referee.decision.call` is set and is not `NONE`. Otherwise it returns:

```ts
interface RefereeCallDescriptor {
  kind: "foul" | "violation";
  callType: string;          // e.g. OFFENSIVE_FOUL, DEFENSIVE_FOUL, STALLING
  offender: string | null;   // "B1"
  offenderTeam: TeamId | null;  // from frame.state.players[offender].team
  fouledPlayer: string | null;
  rules: string[];           // rule_ids_cited, e.g. ["R33.7"]
  message: string;           // "B1 defensive foul on A1"
  subtext: string;           // consequence, see below
}
```

The subtext depends on what happens in the same frame:

| Situation | Subtext |
|---|---|
| Offensive foul with turnover | `Turnover · Possession to Team B (B2) · R33.7` |
| Defensive foul with free-throw score | `Free throw awarded to A1 · Team B fouls: 4` |
| Defensive foul, nothing else | `Team B fouls: 4 · Team A retains ball` (from `state.team_fouls`) |
| Violation | `Stalling violation · Possession to Team A` |

### B2. Rendering in [ReplayView.tsx](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/frontend/src/components/ReplayView.tsx#L1033-L1055)

- Next to the existing `#shot-banner`, render `#foul-banner`, keyed by `foul-banner-${event_idx}` so the pop animation re-runs on every call, with `role="status"` and `aria-live="polite"`. Contents:
  - Tag: `FOUL · OFFENSIVE`, `FOUL · DEFENSIVE` or `VIOLATION`, with a small whistle glyph
  - Title: `call.message`
  - Subtext: `call.subtext`
- **Stacking:** if a shot banner also shows (made basket, missed shot, free throw), put the foul banner directly **below** it (`top: 12px + shot-banner height`, using a flex column wrapper `.court-banners`) so both stay readable.
- **De-duplication:** when the shot banner would be `kind: "turnover"` with reason `OFFENSIVE_FOUL` or `REFEREE_VIOLATION`, **show only the foul banner**. It already carries the possession change in its subtext, so the call isn't announced twice. Make, miss and rebound banners still show alongside it.
- Playback hold: in `frameDurationMs` ([L590–L596](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/frontend/src/components/ReplayView.tsx#L590-L596)), give foul frames `Math.max(speed, 850)`, the same as scores, so the popup stays up long enough to read during auto-play.
- Optional on-court marker: briefly pulse a ring on the offender's player disc (reuses the `rim-fx-pulse` keyframes) in the referee colour.

### B3. Styling in [replay.css](file:///c:/Users/hongy/OneDrive/Documents/Desktop/llm-3v3-basketball-agents/frontend/src/styles/replay.css#L125-L191)

- `.foul-banner` reuses the `.shot-banner` pill structure and `shot-banner-pop` animation.
- Colour: referee yellow (`#ffd84d`) border and tag on a dark charcoal gradient. This sets it apart from score (green), miss (red), rebound (teal) and turnover (orange).
- `.foul-banner.violation` uses the existing call blue (`#adc5ff`), matching `.event-cue-badge.call`.
- Add `.foul-banner` to the `prefers-reduced-motion` block.

### B4. Tests (vitest)

New `tests/unit/replay-logic.test.ts` with fixture frames for each row of the table in §2.3:

- Offensive foul with turnover
- Defensive foul alone
- Defensive foul with free throw (the score and foul descriptors both exist)
- Offensive foul with made field goal
- Stalling violation
- `NONE` → `null`

It also checks the de-duplication rule.

---

## 5. Verification

1. `uv run python scripts/build_frontend_results.py`: parity check passes, and it prints 10 games per experiment.
2. `cd frontend && npm run data -- --force && npm run typecheck && npm test && npm run build`.
3. Manual browser check (`npm run dev`):
   - The overview, games library and comparisons show 5 seeds and 10 games per experiment, and no s101–s105 entries.
   - Comparison plots and stats render (5 paired seeds).
   - Foul popups on known events:

     | Game | Event | Expected |
     |---|---|---|
     | `abl_captain_v1_s106_A` | #121 | defensive foul, no other banner |
     | `abl_captain_v1_s106_B` | #87 | offensive foul, foul banner replaces turnover banner |
     | `abl_captain_v1_s106_B` | #102 | offensive foul **and** made field goal, banners stacked |
     | `abl_captain_v1_s110_B` | #288 | defensive foul **and** free throw, banners stacked |
     | `abl_memory_v1_s108_A` | #178 | stalling violation |

---

## 6. Open questions

> [!IMPORTANT]
> **Q1: Stats and plots for 106–110.** My recommendation is to regenerate `stats.json`, `adaptation.csv` and the plots from the logs so everything describes the same 5 seeds. The alternative is to only filter the CSV rows and keep the uploaded 7-seed stats and plots, labelled "computed on s104–s110". That is inconsistent, so I don't recommend it. Which do you want?

> [!IMPORTANT]
> **Q2: Comms seed 106 logs.** The new `abl_comms_v1.zip` doesn't contain s106. The old `abl_comms_v1_s106.zip` (deleted in your working tree, still in git `HEAD` and `frontend/results/`) matches the new summary exactly. Should I use it? The alternative is that you re-upload a comms zip that includes s106. If I use it, should I restore it into `results/`, or have the script read it from git history?

> [!NOTE]
> **Q3: Violations.** "Foul called" could also cover the 2 `STALLING` violations. The plan shows them in the same popup with a `VIOLATION` tag and blue styling. Tell me if you want fouls only.

> [!NOTE]
> **Q4: Offensive-foul turnovers.** The plan replaces the existing `TURNOVER` banner with the foul banner on those frames, so the call isn't announced twice. Would you rather show both stacked?

