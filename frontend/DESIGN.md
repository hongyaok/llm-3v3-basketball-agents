# DESIGN.md — Courtside (Multi-Agent 3x3 Basketball Research Observatory)

## Phase 0: Brief
- **Subject:** COURTSIDE — Multi-Agent Cooperation and Adaptation in Competitive 3v3 Basketball (DSA4213 Group 16 Research Project: Damien Ang Wei Hao, Davin Hong Zheng Long, Koh Hong Yao, Peng Rui Biao, Xavier Ang Chin How, Rachel Oh).
- **Audience:** Academic reviewers, sports analytics researchers, AI multi-agent researchers, and coaches exploring how natural-language coordination shapes fast-paced competitive decision-making.
- **Job of the site:** Serve as both an interactive research monograph explaining *why* this testbed was created (from the DSA4213 proposal) and an exploratory telemetry command desk that routes visitors directly to their chosen task: comparing all 3 ablation studies side by side, inspecting experiment statistics, scrubbing possession-level 3v3 court replays, auditing the 32-game library, exploring the 6-stage tick architecture, or downloading raw CSV artifacts.
- **Constraints:**
  1. Remove the website logo completely (pure typographic Swiss identity).
  2. Provide an interactive landing page where visitors can choose what they want to do on the site and get routed directly to the right location.
  3. Integrate core elements of the DSA4213 Group Project Proposal PDF (motivation, research question, the 3 separated layers: LLM intent, non-LLM logistic resolution engine, and FIBA 3x3 RAG Referee, plus the 4 team configurations A–D and 7 formal evaluation metrics).
  4. Do not alter any core data pipeline, statistical pooling, paired bootstrap calculation, or replay state logic; preserve 100% of existing functionality.

---

## Phase 1: Concept

### Concept Card
```
Idea:        A coach's courtside telemetry desk where natural-language agent cognition meets deterministic half-court physics.
Metaphor:    Swiss sports timing console & tactical clipboard (FIBA 3x3 12-second shot clock, 15x11m half-court grid, XML decision tags).
Signature:   Interactive "Tactical Command Deck" on the landing page: visitors select their intent (or filter by ablation & game seed) with live telemetry preview cards and instant routing, paired with an interactive 3-Layer System Anatomy switcher.
Emotion:     Precision, clarity, and kinetic tension — like pausing game film at a decisive pick-and-roll tick.
Motion verb: "Snap and lock" — elements slide along grid hairlines and lock into place with cubic-bezier(0.165, 0.84, 0.44, 1), labels roll cleanly inside clipped frames, and court vectors pulse gently at rest.
Screenshot:  The asymmetric editorial hero pairing giant Switzer display type with the live interactive Command Deck and a breathing 15x11m half-court tactical diagram.
```

---

## Phase 2: Art Direction System

### Palette
- `ground` (`--paper`): `#F3F3EC` — Warm archival telemetry paper
- `surface` (`--card`): `#FAFBF7` / `#FFFFFF` — Crisp tactical sheet
- `ink` (`--ink`): `#10211C` — Deep courtside forest-obsidian (passes AAA on ground)
- `muted` (`--muted`): `#4F6159` — Slate-pine secondary ink (passes AA > 5.2:1 on ground)
- `line` (`--line`): `#D8DFD5` — Structural grid hairline
- `accent` (`--green`): `#1E6B4F` — Baseline emerald (primary condition A)
- `signal` (`--lime`): `#CEEE9E` — Shot-clock phosphor lime (highlight & active indicators on dark ink)
- `counter` (`--orange`): `#C85A28` — Ablation variant burnt sienna (variant condition B/C/D)

### Typography
- **Display & UI (`--f-sans`):** **Switzer** (400, 500, 600, 700, 400i) — Swiss neo-grotesk with tight negative tracking (`-0.035em` to `-0.045em`) on headlines and clean legibility at 12–16px UI sizes.
- **Editorial Accent (`--f-serif`):** **Zodiak** (400, 400i) — Contemporary high-contrast serif used selectively for the research question pull-quote, mathematical formulas, and italicized thesis emphasis.
- **Data & Telemetry (`--f-mono`):** **JetBrains Mono** (400, 500, 600) — Tabular numerals (`tabular-nums`), XML agent tags (`<ACTIONS>`, `<c>[tactic]`, `memory_ref="M03"`), seed IDs, and shot-clock readouts.

### Fluid Type Scale
- `--t-hero`: `clamp(2.5rem, 1.4rem + 3.6vw, 4.75rem)` (`line-height: 0.94`, `letter-spacing: -0.04em`)
- `--t-xl`: `clamp(1.85rem, 1.2rem + 2.2vw, 3.1rem)` (`line-height: 1.02`, `letter-spacing: -0.035em`)
- `--t-l`: `clamp(1.35rem, 1.1rem + 0.9vw, 1.85rem)` (`line-height: 1.15`, `letter-spacing: -0.025em`)
- `--t-body`: `clamp(0.95rem, 0.92rem + 0.2vw, 1.0625rem)` (`line-height: 1.55`)

### Micro-interactions & Motion Language
- **Buttons & Primary CTAs:** Clipped label roll or directional fill flood with `cubic-bezier(0.165, 0.84, 0.44, 1)`, plus arrow nudge (`translate: 4px 0`).
- **Command Deck Intent Cards:** Tactile hairline border highlight, index number illumination, and live route preview pill that shifts on hover/focus-visible.
- **Navigation Links:** Clean indicator bar and crisp typographic contrast without any decorative SVG logo clutter.
- **Reduced Motion:** All animations and transitions disabled cleanly under `@media (prefers-reduced-motion: reduce)` with clear underline/fill states preserved.

