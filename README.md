# LLM 3×3 Basketball Agents

Six LLM players. One deterministic engine. One rulebook-grounded referee.

**DSA4213 Natural Language Processing · Group 16**

![Courtside research dashboard](docs/screenshots/01-landing.png)

## Pick where to start

| I want to… | Go to | Time |
|---|---|---|
| See the results without installing anything | [§6 Experiments and results](#6-experiments-and-results) | 2 min |
| Run one game end to end | [§2 Quickstart](#2-quickstart) | ~15 min |
| Re-run an ablation study | [§7 Commands](#7-command-reference) | ~$5 in model spend |
| Read the design reasoning | [`proposal/`](proposal/) | 30 min |
| Understand the simulation engine | [`src/bball3x3/engine/README.md`](src/bball3x3/engine/README.md) | 20 min |

Everything below is either a table or a numbered step. Nothing requires reading in order.

---

## 1. What this is

A research testbed for **multi-agent cooperation and adaptation** in competitive
FIBA 3×3 basketball.

The research question:

> How do structured teammate communication, captain-led tactical calls, and shared
> team memory affect cooperation and adaptation among LLM agents in a competitive
> 3v3 basketball environment?

The design decision that shapes everything: **LLMs only propose intent.** Six LLM
agents emit a natural-language action proposal each tick. A single-threaded,
seeded, non-LLM engine resolves every physical outcome — shots, passes, drives,
rebounds, fouls, fatigue, clock — and commits the next state. No LLM decides
whether a shot goes in. This makes runs reproducible (same seed, same game),
cheap to audit, and immune to a hallucinated score.

Three subsystems sit on top of that base:

| Subsystem | What it does |
|---|---|
| **Coordination** | Teammate messages, a captain who issues tactic calls as directives, and shared team memory with similarity merging |
| **Referee** | Retrieves the top-3 relevant clauses from the indexed FIBA 3×3 rulebook (RAG) and grounds each foul/violation judgement in them |
| **Analysis** | Possession reconstruction, 9 metrics plus a per-game box score, paired-seed statistics, adaptation plots, replay |

![System architecture](docs/screenshots/05-architecture.png)

---

## 2. Quickstart

Prerequisites: **Python 3.11+**, [uv](https://docs.astral.sh/uv/) (recommended) or
`pip`, and an [OpenRouter](https://openrouter.ai/keys) API key.

### 1. Install — 2 min

```bash
uv venv
uv sync --extra dev --extra rag
```

<details>
<summary>Without uv</summary>

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -e ".[dev,rag]"
```
</details>

`rag` is only needed to build or query the rulebook index. Everything else runs
without it.

### 2. Add your API key — 1 min

Create `.env` in the repository root:

```
OPENROUTER_API_KEY=sk-or-v1-...
```

`.env` is gitignored. The CLI loads it automatically; `configs/llm.yaml` names the
variable via `provider.api_key_env`.

### 3. Check the rulebook index — 3 min, one time

The PDF and its index are already committed, so this is optional. Run it only if
you replace the PDF or change the embedding model:

```bash
uv run --extra rag bball build-index
```

Verify the committed index is intact:

```bash
uv run --extra rag python scripts/validate_referee_retrieval.py
```

### 4. Play one game — ~3 min, ~$0.50

```bash
uv run --extra rag python -m bball3x3.runner.game \
  --llm-config configs/llm.yaml \
  --rule-index-dir data/rules \
  --seed 101 \
  --path runs/demo/game.jsonl
```

Writes one JSONL log: every decision, message, captain call, referee ruling and
state snapshot.

### 5. Read what happened — 10 s

```bash
# human-readable transcript of one possession
uv run bball transcript runs/demo/game.jsonl p0001

# tables, then statistics, then plots (each needs a directory that does not exist yet)
uv run bball export runs/demo-export runs/demo/game.jsonl
uv run bball stats  runs/demo-export runs/demo-stats.json
uv run bball plots  runs/demo-export runs/demo-plots
```

### 6. Open the dashboard — 3 min

```bash
cd frontend
npm install
npm run build      # also rebuilds public/data from ../results/*.zip
npm run start      # http://localhost:3000
```

---

## 3. Repository map

| Path | What lives there |
|---|---|
| `src/bball3x3/engine/` | Deterministic simulation: court, clock, actions, resolvers, FIBA rules, 20 invariants. **Has its own [README](src/bball3x3/engine/README.md).** |
| `src/bball3x3/agents/` | Observation builder, Jinja prompts, XML parsing, action legalisation, heuristic + random baselines |
| `src/bball3x3/llm/` | OpenRouter client, retries, repair passes, budget caps, disk cache, fake policies for tests |
| `src/bball3x3/coordination/` | Captain tactic calls, message channels, shared coordination store |
| `src/bball3x3/memory/` | Personal memory, shared memory, embeddings, similarity merging, counter-strategy store |
| `src/bball3x3/referee/` | Rulebook indexer, retriever, rule-based referee, LLM referee, validation suites |
| `src/bball3x3/runner/` | `game.py` (one logged game), `experiment.py` (seeded paired runs), `llm_game.py` |
| `src/bball3x3/analysis/` | Log reading, possessions, metrics, exports, statistics, plots, transcripts |
| `src/bball3x3/schemas/` | Frozen Pydantic records — state, actions, logs, messages, referee, memory |
| `configs/` | `llm.yaml` (models, budget), `simulation.yaml` (every physics coefficient), `experiments/*.yaml`, `teams/*.yaml` |
| `data/rules/` | FIBA 3×3 rulebook PDF + 95 indexed clauses + 384-dim embeddings + manifest |
| `tests/` | 58 files, 522 tests |
| `frontend/` | "Courtside" Next.js 15 dashboard: comparisons, cross-study tables, game library, court replay, architecture page |
| `results/` | Source-of-truth result archives (compressed game logs + exports) |
| `runs/` | Where **new** experiments write. Empty by design. |
| `scripts/` | Validation and build helpers (see [§7](#7-command-reference)) |
| `proposal/` | Project proposal, system architecture page, workstream design docs |
| `archive/` | Historical scripts and pre-integration logs — see [§10](#10-documentation-and-archive) |
| `docs/screenshots/` | The images in this README |

---

## 4. How a game runs

One tick = one decision event. Six stages per tick:

| Stage | What happens | Code |
|---|---|---|
| 01 | Build one observation per player (positions, clock, scores, legal actions, recent messages) | `agents/observation.py` |
| 02 | Six LLM calls in parallel return XML proposals + rationale | `agents/llm_player.py`, `agents/adapter.py` |
| 03 | Store teammate messages; captain issues a tactic call with directives | `coordination/` |
| 04 | Engine legalises proposals, resolves physics, applies FIBA rules, checks invariants, commits | `engine/` |
| 05 | Referee retrieves 3 rulebook clauses and rules FOUL / VIOLATION / NONE | `referee/` |
| 06 | Validated shared-memory update | `memory/` |

Inside stage 04 the engine order is fixed: **LEGALIZE → RESOLVE → APPLY RULES →
COMMIT**, with 20 invariants checked before the commit. Any violation is logged
as a State Inconsistency Rate (SIR) event; in tests it raises.

Invalid proposals never crash the game. They are remapped to a spec-defined
fallback (`HOLD`, `SPOT_UP`, `DEFEND`, `BOX_OUT`) and counted in the Invalid
Action Rate (IAR), with the reason recorded.

Rules implemented: 600 s regulation, 12 s shot clock, first to 21, overtime to
+2, team-foul ladder (7th–9th → 2 FT, 10th+ → 2 FT + possession), automatic
clear behind the arc, 15 × 11 m grid with a 6.75 m arc.

---

## 5. What is measured

| Metric | Definition | Direction |
|---|---|---|
| **PPP** | Points scored / completed possessions | higher |
| **MAAR** — message alignment | Actions aligned with teammate messages | higher |
| **CCAR** — captain alignment | Actions aligned with captain directives | higher |
| **CCR** — coordination conflicts | Team-events where two teammates' executed actions hit the same court zone, over team-events with at least two zone-targeted actions | **lower** |
| **MAUR** — memory usage | Decisions referencing shared memory | higher |
| **Grounded MAUR** | Memory references that are actually grounded in context | higher |
| **CSSR** — strategy selection | Tactic calls using a valid coordination strategy | higher |
| **IAR** — invalid actions | Invalid proposals / all decisions | **lower** |
| **SIR** — state inconsistency | Invariant violations / state transitions | **lower** |

Four **per-game counting stats** sit beside the rates: passes, assists,
rebounds, turnovers. They are counts, not rates, so they carry no evidence
status. The dashboard derives them from the saved JSONL logs:

| Stat | Counted as |
|---|---|
| Pass | One executed `PASS` action, credited to the passer's team |
| Assist | A made shot in the replay event right after a teammate's pass |
| Rebound | A loose ball gathered — one `LOOSE → HELD` transition, credited to whoever picks it up |
| Turnover | One logged turnover entry, credited to the team that lost the ball |

Two rules that matter when reading the tables:

1. **Every rate keeps its numerator, denominator and evidence status.** A rate
   that cannot be computed is `not_applicable`, `insufficient_evidence` or
   `incomplete` — never a silent zero. A gated rate with a non-zero denominator
   is still reported: CSSR without a captain is a real 305/398, not `N/A`.
2. **Paired seeds are the primary inference.** Each seed is played twice with the
   first possession swapped; the two are averaged before a seed-cluster bootstrap
   (95% CI) and a two-sided Wilcoxon test. Possession-level models are
   exploratory only.

---

## 6. Experiments and results

**36 games · 8 seeds · 11,750 events · 2,473 possessions · $19.88 model spend.**

Every table below also renders at [`/comparisons`](frontend/) under *All four
studies, side by side* — same numbers, rebuilt from `results/seeds_106_110.zip`.

**The bottom line.** No ablation separates from its control at 5%. The mirror
control — identical configuration on both sides — produces a **+0.131** PPP gap,
larger than any treatment effect measured here. What did move exactly as
designed is the mechanism check: every metric that should switch off, switched
off.

### What was run

| # | Study | A (Full system) | B | Seeds | Games |
|---|---|---|---|---|---|
| 1 | `pilot_v1` | Full system | **Full system (Side B)** — mirror control | 101–103 | 6 |
| 2 | `abl_comms_v1` | comms ✓ captain ✓ memory ✓ | **No communication** | 106–110 | 10 |
| 3 | `abl_captain_v1` | comms ✓ captain ✓ memory ✓ | **No captain** | 106–110 | 10 |
| 4 | `abl_memory_v1` | comms ✓ captain ✓ memory ✓ | **Read-only memory** | 106–110 | 10 |

### Points per possession

| Study | Seeds | Pooled PPP (A / B) | Paired ΔPPP | 95% CI | p | Wins A / B |
|---|---|---|---|---|---|---|
| Control (mirror) | 3 | 0.620 / 0.478 | **+0.131** | −0.081 to +0.404 | 0.750 | 4 / 2 |
| Communication | 5 | 0.405 / 0.448 | **−0.057** | −0.269 to +0.114 | 1.000 | 4 / 6 |
| Captain | 5 | 0.429 / 0.427 | **+0.028** | −0.194 to +0.234 | 1.000 | 5 / 5 |
| Memory updates | 5 | 0.422 / 0.559 | **−0.143** | −0.281 to −0.006 | 0.313 | 2 / 8 |

Three things to take from that table:

1. **Every p-value is above 0.05.** Five paired seeds buy very little.
2. **The memory interval excludes zero, but p = 0.313.** Read the interval and
   the test together, never one alone.
3. **The control's +0.131 is the largest effect in the table.** Both sides ran
   the same configuration, so at this sample size that is noise.

### Coordination and adaptation

| Study | MAAR | CCAR | CCR | MAUR | CSSR |
|---|---|---|---|---|---|
| Control (mirror) | 26.13% / 25.61% | 27.62% / 23.73% | 45.01% / 36.30% | 24.38% / 22.10% | 90.89% / 95.33% |
| Communication | 26.67% / N/A | 28.96% / 23.80% | 36.06% / 40.10% | 26.49% / 30.69% | 96.25% / 96.70% |
| Captain | 25.93% / 24.84% | 27.75% / N/A | 43.64% / 45.49% | 23.57% / 24.49% | 92.58% / 76.63% |
| Memory updates | 24.70% / 31.48% | 26.64% / 31.96% | 41.11% / 42.70% | 23.41% / 15.52% | 95.73% / 0.00% |

First value is the full system, second is the comparison condition. `N/A`
appears only where a condition had no opportunities in scope: no messages to
align to, no directives to follow.

What each row shows:

1. **Memory updates — the mechanism check passes.** MAUR 23.41% → 15.52%, CSSR
   95.73% → 0.00%. Read-only memory keeps the store but can never select a
   stored tactic.
2. **Communication — talking helps spacing.** CCR 36.06% → 40.10% without it:
   more same-zone overlap when nobody can call a teammate off. CCR is
   lower-is-better.
3. **Captain — strategy selection falls, everything else holds.** CSSR 92.58% →
   76.63%: without a captain, tactic calls still happen but fewer name a stored
   counter-strategy. MAAR, MAUR and CCR barely shift.
4. **CCR is the noisiest metric here.** The mirror control reads 45.01% vs
   36.30% with one configuration on both sides. Treat small CCR gaps as noise.

> The per-game export tags the no-captain CSSR cells `not_applicable`, because
> no captain issued those calls. The calls themselves still happen — 305 of 398
> named a visible strategy — so the pool reports 76.63% rather than `N/A`.

### Box score and system validity

Per-game counts, read straight off the saved logs:

| Study | Passes / game | Assists / game | Rebounds / game | Turnovers / game |
|---|---|---|---|---|
| Control (mirror) | 77.8 / 74.3 | 8.5 / 7.7 | 13.3 / 10.0 | 13.2 / 15.5 |
| Communication | 94.4 / 65.3 | 7.1 / 5.6 | 19.9 / 14.3 | 18.9 / 16.2 |
| Captain | 93.8 / 95.8 | 7.0 / 7.9 | 18.9 / 14.0 | 20.4 / 17.3 |
| Memory updates | 106.9 / 65.2 | 7.1 / 7.8 | 20.5 / 15.4 | 18.7 / 11.4 |

Validity, same order:

| Study | IAR (A / B) | SIR |
|---|---|---|
| Control (mirror) | 1.33% / 1.79% | 0.00% |
| Communication | 1.72% / 0.91% | 0.00% |
| Captain | 1.55% / 1.20% | 0.00% |
| Memory updates | 1.34% / 2.05% | 0.00% |

**Zero invariant violations across 11,750 transitions**, IAR between 0.9% and
2.1%. A clean SIR only means the physics stayed consistent, so the referee's
rulebook grounding is checked separately by the retrieval validation in §7.

### Reproducing these numbers

```bash
uv run --extra rag bball run-experiment configs/experiments/ablation_comms.yaml
uv run bball export runs/abl_comms_v1       results/abl_comms_v1-export
uv run bball stats  results/abl_comms_v1-export results/abl_comms_v1-stats.json
uv run bball plots  results/abl_comms_v1-export results/abl_comms_v1-plots
```

Then rebuild the dashboard, which recounts the box score from the same logs:

```bash
cd frontend && npm run data
```

![All four ablations side by side](docs/screenshots/02-comparisons.png)

![Communication ablation overview](docs/screenshots/03-experiment-overview.png)

![Court replay with decisions and referee evidence](docs/screenshots/04-replay-court.png)

> **Seeds.** The YAML files list seeds `101–110`. The reported ablations use
> **106–110 only** (the five seeds with complete A/B pairs); seeds 101–103 are
> the control. Running a config as-is therefore plays 20 games, not the 10
> reported here — filter by seed before comparing.

> **Cost.** `configs/llm.yaml` caps spend at `$10.00` per experiment
> (`runtime.budget.max_usd_per_experiment`, line 41). A full 20-game run can
> exceed that; the cap stops the run rather than overspending.

---

## 7. Command reference

### `bball` — installed CLI

| Command | Purpose |
|---|---|
| `bball build-index` | Extract rulebook clauses + embeddings. `--backend hash` for the offline fallback, `--force` to replace |
| `bball run-experiment <config.yaml>` | Play every seed twice with swapped first possession; resumes unfinished games. `--dry-run` lists games without calling a model |
| `bball transcript <log> <possession-id>` | Human-readable possession: observations, messages, calls, actions, rationales, memory refs, referee calls |
| `bball export <new-dir> <log…>` | `games.csv`, `teams.csv`, `possessions.csv`, `manifest.json`. Refuses to overwrite |
| `bball stats <export-dir> <out.json>` | Paired seed bootstrap + Wilcoxon; exploratory possession models |
| `bball plots <export-dir> <new-dir>` | PPP / MAUR / CSSR adaptation curves + manifest |

### `scripts/`

| Script | Purpose |
|---|---|
| `validate_rule_referee.py` | Rule-referee decision accuracy on labelled fixtures (offline) |
| `validate_referee_retrieval.py` | Retrieval hit@3 + category recall on 26 labelled states (offline). Baseline 14/26 → 22/26 after the category audit |
| `prompt_harness.py` | 20 fixed scenarios → prompt-quality report. `--fake` for offline |
| `llm_smoke.py` | One live decision against OpenRouter. `--fake` for offline |
| `model_selection.py` | Short live games per candidate model with a hard spend cap |
| `build_frontend_results.py` | Rebuilds `frontend/results/` from `results/` with a parity check. Called by `npm run sync-results` |

### Changing the model

Two places in **`configs/llm.yaml`**:

- **line 10** — `players.model` — the six players
- **line 24** — `referee.model` — the LLM referee

Both are currently `mistralai/mistral-small-3.2-24b-instruct`. To use the
deterministic referee instead, set `referee.enabled: false` (line 22) or
`referee.backend: rule_based` (line 23).

---

## 8. Tests and lint

```bash
uv run pytest          # 522 tests, ~4 min (includes a 1,000-game fuzz run)
uv run ruff check .
```

Current state: **522 passed**, ruff clean. The suite covers court geometry,
clock, the 20 invariants, resolvers, rules, prompts, XML repair, budget and cache,
retrieval, metrics, statistics, exports, plots, and a frontend parity check.

Live API tests are marked `live` and skipped by default: `uv run pytest -m live`.

---

## 9. AI use declaration

Declared for transparency, in the spirit of the DSA4213 academic-integrity rules.

**LLMs are part of the artefact.** The six player agents and the LLM referee are
the object of study, not a development shortcut. Every experiment calls
`mistralai/mistral-small-3.2-24b-instruct` through OpenRouter; token counts, cost,
latency and raw replies are logged per decision in `runs/`.

**LLMs were used as a development tool.** AI coding assistants were used to draft
and refactor implementation code, write tests, and produce documentation during
this project. All such output was reviewed, run, and accepted or rejected by the
team. 

**This README was written with AI assistance**

**Human-owned contributions:** the research question and proposal, the
experimental design (conditions, seeds, paired first-possession design, metric
definitions), the choice and interpretation of the statistical tests, the
simulation and rules specification, and every conclusion drawn in §6.

---

## 10. Documentation and archive

| Document | Contents |
|---|---|
| [`proposal/DSA4213 Group Project Proposal.pdf`](proposal/DSA4213%20Group%20Project%20Proposal.pdf) | The graded proposal |
| [`proposal/agentic_workflows/IMPLEMENTATION_PLAN.md`](proposal/agentic_workflows/IMPLEMENTATION_PLAN.md) | The WS0–WS7 workstream plan, deliverables and gates |
| [`proposal/agentic_workflows/WS6_LOG_CONTRACT.md`](proposal/agentic_workflows/WS6_LOG_CONTRACT.md) | Every log record and its timing |
| [`proposal/agentic_workflows/WS6_DESCRIPTIVE_METRICS.md`](proposal/agentic_workflows/WS6_DESCRIPTIVE_METRICS.md) | Metric numerators, denominators and evidence statuses |
| [`proposal/agentic_workflows/WS5_RETRIEVAL_AUDIT.md`](proposal/agentic_workflows/WS5_RETRIEVAL_AUDIT.md) | Retrieval baseline, every miss, every mapping correction |
| [`proposal/agentic_workflows/MODEL_SELECTION.md`](proposal/agentic_workflows/MODEL_SELECTION.md) | Why this model, with measured cost and latency |
| [`proposal/agentic_workflows/README_WS4.md`](proposal/agentic_workflows/README_WS4.md) | Coordination and memory design |
| [`archive/README.md`](archive/README.md) | What was archived and why, plus how to restore it |
| [`frontend/README.md`](frontend/README.md) | Dashboard internals and Vercel deployment |

`archive/` holds superseded PRE_WS7 harnesses, the pre-integration notebook and
historical run logs. Nothing in `src/`, `tests/` or `frontend/` imports from it,
so it is safe to delete.

---

## Licence and attribution

Coursework for DSA4213 (National University of Singapore), Group 16. FIBA 3×3
rules text is quoted for referee grounding under academic fair use; see
[`third_party/BASKETWORLD_ATTRIBUTION.md`](third_party/BASKETWORLD_ATTRIBUTION.md)
for third-party attribution.
