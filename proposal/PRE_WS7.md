# PRE-WS7 Final Integration Test — Implementation Plan

> **Status: PLAN ONLY. No implementation this turn.**
> This document is the sole artifact produced now. No `.ipynb` was created,
> no source file was modified, no config was changed, and no game was run.
> The complete notebook is specified here as **Appendix A (blueprint)** and will be
> materialised as `proposal/pre_ws7_full_game_test.ipynb` only after your review.
> Models in `configs/` are immutable for this work.

**Decisions confirmed 2026-10-22 (your answers, recorded):**

1. This turn writes only `PRE_WS7.md`, with the full cell-by-cell notebook blueprint inside it. No `.ipynb` yet.
2. "Complete game" means a **full FIBA 3x3 game to termination** — 600 s clock **or** first to 21, plus overtime (first to 2 in OT). Not a bounded smoke prefix.
3. Referee for the final test is the **LLM referee live**, using the models already set in `configs/llm.yaml`. Rule-based is not acceptable as the final gate.
4. Notebook lives in `proposal/`; game logs, checkpoints, and traces land under `runs/pre_ws7/<timestamp>_seed_<seed>/`.

---

## 1. Purpose and scope

### 1.1 What "connect everything and do one final test" means

WS1–WS6 are each reported done. What has **not** yet been demonstrated in one run is:

```
configs (frozen) → 6x LLMPlayer (WS3) → EngineSession (WS1) → contact (WS1)
  → LLMReferee + RAG (WS5) → rules/OT/fatigue (WS1) → comms/captain/memory/CS (WS4)
  → WS6 JSONL log → WS6 validation + metrics + transcript
```

The final test proves that chain works **in a single real game, to a valid terminal state,
with the configured LLM referee judging every event**, and hands WS7 a replayable artifact.

### 1.2 Definition of done (pre-WS7 gate)

1. One full game completes via the public LLM path with `game_complete == True` and a valid `game_end` record (`WIN_SCORE`, `CLOCK_EXPIRED`, or `OT_WIN`).
2. Every decision event carries a WS6 referee record produced through the **LLM referee path** (`judge_with_trace` → `as_log_record`), including `query`, `retrieved_chunk_ids`, `raw_output`, `model`, token/cost/latency, and `REF_PARSE_FAIL` where applicable.
3. The saved JSONL passes `read_game_log()` + `validate_possessions()` with zero unexplained failures, and `compute_game_metrics()` runs.
4. Parse-failure and IAR/SIR rates are measured and reported (targets from the plan: parse-fail < 2%, IAR < 5%, SIR = 0 — measured, not asserted).
5. `git diff -- configs/` is empty after the run. Model slugs were consumed, never edited.
6. Artifacts exist under `runs/pre_ws7/<run_id>/` and are listed in a run manifest WS7 can consume.

### 1.3 Non-goals (explicit)

- No changes to model slugs, temperatures, token limits, or any value in `configs/llm.yaml`. (Section 5 explains how `referee.enabled` is overridden **in memory only**.)
- No redesign of WS1–WS6 APIs beyond the one documented adapter (Section 6).
- No WS7 experiment harness, no multi-seed ablations, no stats/plots findings.
- No display work beyond `display.enabled: false`. Frames never enter metrics.
- No BasketWorld parity in this gate (WS7 Phase 1 owns it, methods-only).

---

## 2. Current-state inventory (as found in this repo)

Per-workstream entry points with real paths. This is the ground truth the notebook must build on.

| WS | Contributes | Canonical modules | Public entry | Status / note |
|---|---|---|---|---|
| WS0 | Schemas, config loaders | `src/bball3x3/schemas/state.py`, `schemas/agent.py`, `schemas/messages.py`, `schemas/memory.py`, `schemas/referee.py`, `schemas/log.py`, `src/bball3x3/config.py` | `load_llm_config()`, `load_simulation_config()`, `load_roster_config()`, `load_initial_memory_config()` | Stable. `LLMRefereeConfig` enforces `temperature==0.0`, `output_format=="xml"`, `top_k_rules==3`. |
| WS1 | Engine source of truth | `src/bball3x3/engine/session.py` (`EngineSession`), `engine/loop.py` (`play_heuristic_game`), `engine/actions.py`, `resolvers.py`, `contact.py`, `rules.py`, `clock.py`, `invariants.py`, `rng.py`, `court.py` | `EngineSession(seed, config, abilities_map).step(proposals)` | Done. FIBA 3x3: 600 s / 21 pts / 12 s shot clock / bonus 7 & 10 / OT first-to-2. `loop.py` already bridges the sync referee (`_judge_referee_event`, `_apply_referee_call`) with objective-violation rejection. |
| WS2 | LLM infra | `src/bball3x3/llm/client.py` (`OpenRouterClient`), `llm/base.py` (`LLMBackend`, `LLMResponse`), `llm/cache.py`, `llm/budget.py`, `llm/repair.py` | `await backend.complete(messages, params, response_format)` | Done. Semaphore, tenacity retries, SQLite cache, budget stop, RPM token bucket, `QuotaExceededError` (non-retryable), `finish_reason` tracking. |
| WS3 | Player agents + prompts + async driver | `src/bball3x3/agents/observation.py`, `prompting.py`, `prompts/*.j2`, `xml_io.py`, `filtering.py`, `llm_player.py` (`LLMPlayer.decide`), `adapter.py`, `context.py`, `memory/personal.py`, `runner/llm_game.py` (`run_llm_game`) | `await run_llm_game(llm, path, seed, llm_config, embedder, ...)` with checkpoint/resume | Done except **one gap** (Section 6): `run_llm_game` currently writes a placeholder `RefereeRecord(query="rule-based review")` and never calls the LLM referee. Players, prompts, XML/JSON, repair, t→t+1 delivery, checkpoint `.ckpt.json` all exist. |
| WS4 | Comms / captain / shared memory / CS | `src/bball3x3/coordination/`, `src/bball3x3/memory/` (incl. `embeddings.py` `LocalEmbedder`), `agents/context.py` (`SimpleCoordinationView`) | `SimpleCoordinationView(initial_memory, captains, active_players, embedder, threshold)`; `coord_view.record_event(e, kept_map, flags)` | Done. Window 2 events / 6 msgs / 200 chars. `memory_write=False` suppresses writes. Similarity τ default 0.80 (provisional — calibrate before freeze, but **not** in this gate). `scripts/run_llm_game.py` proves the `LocalEmbedder` + `run_llm_game` wiring with `FakeLLM`. |
| WS5 | Referee + RAG | `src/bball3x3/referee/llm_referee.py` (`LLMReferee.judge_with_trace`), `referee/sync_adapter.py` (`SyncLLMReferee`), `referee/retriever.py` (`RuleRetriever`), `referee/index.py`, `referee/rule_referee.py`, `referee/validation.py` | `retriever.retrieve(state, top_k=3)`; `await referee.judge_with_trace(state)`; `SyncLLMReferee(referee).judge(state)` | Decision layer done and validated on fixtures. Index exists: `data/rules/chunks.jsonl` + `embeddings.npy` + `index_manifest.json` (95 chunks post-audit; revised 22/26 hit@3, 26/26 category eligibility; baseline 14/26 retained in docs). **Not yet wired into `run_llm_game`.** Wired into `runner/game.py::run_logged_game` (heuristic path) via `SyncLLMReferee`. |
| WS6 | Logging / metrics / analysis | `src/bball3x3/logging/event_log.py`, `analysis/log_reader.py`, `possessions.py`, `metrics.py`, `qualitative.py`, `exports.py`, `stats.py`, `plots.py`, `src/bball3x3/cli.py` (`bball transcript|export|stats|plots`) | `read_game_log(path)`, `validate_possessions(game)`, `compute_game_metrics(game)`, `render_possession_transcript(game, pid)` | Log contract landed. `runner/game.py` writes contracted logs (verified on `runs/game_101.jsonl` regulation, `runs/game_11.jsonl` OT). `runner/llm_game.py` writes the same record family. Remaining WS6 note (model-terms/RNG-draw/position enrichment inside resolutions) is replay-phase polish, not a gate blocker. |

Supporting facts:

- Configs: `configs/llm.yaml` (players + referee + embeddings + runtime — **read-only**), `configs/simulation.yaml` (court/rules/coefficients), `configs/teams/roster.yaml` (sample 3-player roster, captain P1), `configs/teams/initial_memory.yaml` (game plan + 2 scouting notes), `configs/experiments/pilot.yaml` (A_full vs A_full, seeds 101–103), `configs/display.yaml` (`enabled: false`, `mode: "off"`).
- Rulebook PDF present: `data/rules/fiba-3x3-basketball-rules-full-version.pdf`.
- Scripts: `scripts/run_llm_game.py` (fake/live prefix runner, `--max-events 20` default), `scripts/llm_smoke.py`, `scripts/prompt_harness.py`, `scripts/validate_referee_retrieval.py`, `scripts/validate_rule_referee.py`.
- CLI: `bball build-index|transcript|export|stats|plots` (`src/bball3x3/cli.py`).
- Prior full-LLM artifacts: `runs/nb_llm_try.jsonl` + `.ckpt.json` exist (prefix runs, not full games).

---

## 3. Interface contract matrix (where integration bugs hide)

| Edge | Producer → Consumer | Exact shape | Owner of validation |
|---|---|---|---|
| Config load | `config.py` → notebook/runner | `LLMConfig` (`players.model`, `referee.{enabled,backend,model,temperature,max_tokens,top_k_rules}`, `embeddings.{backend,model}`, `runtime.{max_concurrent_requests,max_requests_per_minute,cache,budget}`) | `config.py` Pydantic; notebook asserts slugs equal the file values and never writes |
| Observation | `agents/observation.py::build_observation(state, pid, coordination, personal_memory, flags, is_captain, decision_event_idx)` → `LLMPlayer` | `Observation` → rendered Code-1 text logged as `DecisionRecord.observation_text` (hash = SHA-256 of text) | `observation.py`; WS6 rejects hash mismatch |
| Player call | `LLMPlayer.decide(obs)` → `complete_with_repair` → `xml_io.parse_response` | `DecisionResult(output, kept, suppressed, observation_text, raw_attempts, responses, prompt_hash)`; one `DecisionRecord` per decision regardless of repairs | `llm_player.py` + `adapter.py`; fatal parse → `PARSE_FAIL` remap; API failure/`BudgetExceeded` → abort, never fake `PARSE_FAIL` |
| Coordination | `DecisionResult.kept` → `SimpleCoordinationView.record_event` | `MessageRecord(delivered_at=e+1)`, `CaptainCallRecord`, `MemoryProposalRecord`/`MemoryWriteRecord`, `CSProposalRecord`/`CSWriteRecord`; suppressed items logged with `suppressed=True` | WS4 stores; WS6 excludes invalid `memory_ref` from MAUR but retains originals |
| Engine step | `decision_to_proposal(pid, result)` → `EngineSession.step(proposals)` | `dict[pid, ActionProposal]` → payload (`event_idx, prev, state, legalized, remaps, actions, event, holder, handler_action, contact_detected, finished, end_reason`) | `engine/actions.py::remap_invalid_action` (IAR + `invalid_reason`); `invariants.collect_violations` (SIR) |
| Referee state | `engine/contact.py::build_referee_state(prev, state, event, contact)` → referee | `RefereeState(game, players, ball, current_event, contact_event)` | `contact.py` annotates; referee judges every state |
| Referee decision | `LLMReferee.judge_with_trace(state)` → engine apply → log | `LLMRefereeResult(decision, query, retrieved_chunk_ids, raw_output, failure_code, parse_error, model, tokens, cost, latency)` → `as_log_record(event_idx)` | `llm_referee.parse_referee_xml` (strict 7-attr XML, cited IDs ⊆ retrieved, offender ∈ state, objective violations rejected); `loop.py::_judge_referee_event` second-guards engine-owned calls |
| Logging | runner → `EventLogger` JSONL | Order: `game_start` → per event (6× `decision`, `message`s, `captain_call`s, memory/CS records, `referee`, `resolution`, `invariant_violation`s, `state`, `possession_end`s) → `game_end` | `schemas/log.py` + `logging/event_log.py`; `read_game_log` strict-reads |
| Analysis | JSONL → `analysis/*` | `PossessionTracker` (offensive rebound ≠ new possession; FTs stay in foul possession), metrics (PPP/MAAR/CCAR/CSSR/MAUR/IAR/SIR/referee rate) | `possessions.py`, `metrics.py` |

Known shape mismatches / gaps the final test must catch (not fix silently):

1. **`run_llm_game` has no referee parameter.** It cannot satisfy "LLM referee every state" without the Section 6 adapter. This is the principal integration risk.
2. **`run_logged_game` (heuristic path) already does LLM-referee bridging** via `SyncLLMReferee` on a persistent per-game loop thread. The notebook must reuse that exact bridge pattern, not invent a second one.
3. `DecisionRecord` in the LLM path requires `observation_text`, tokens, cost, latency; the heuristic path synthesises `raw_output` from proposals. The final game must exercise the LLM-shaped records.
4. `LLMRefereeConfig` validation is strict — any notebook that passes a hand-built referee config with `temperature != 0` or `top_k_rules != 3` will raise. The notebook must pass through `llm_cfg.referee` untouched.

---

## 4. End-to-end data/control flow (one decision event)

```
1. state (GameState, event_idx=e)
2. build 6 observations (A1–A3, B1–B3; role BALL_HANDLER/OFF_BALL/DEFENSE/REBOUND;
   + t-1/t-2 msgs + captain call + personal/shared/CS + Code-2 instruction)
3. asyncio.gather(6 × LLMPlayer.decide)   [parallel; semaphore 12; RPM ≤ 18/min]
4. filtering.apply_flags per team (comms/captain/memory_write; Team B captain path preserved)
5. log 6 DecisionRecords + Message/CaptainCall/Memory/CS proposal records
6. coord_view.record_event → t+1 visibility; write Memory/CS write records
7. personal_memories.update (templated, no LLM)
8. EngineSession.step: legalize → resolve handler → screens → off-ball → defense
   → detect_contact → advance clock → fatigue → shot-clock check → invariants
9. build_referee_state → RuleRetriever.retrieve (category route → cosine top-3)
   → LLMReferee.judge_with_trace → strict parse (NONE + REF_PARSE_FAIL on malformed)
   → _judge_referee_event guard → apply_referee_decision (code mutates state; referee never does)
10. log referee + resolution + violations + state + possession ends
11. next event or game_end (score/clock/OT check) → close SyncLLMReferee loop
```

Concurrency model: 6 player calls parallel per event; **1 serial referee call on the critical path** per event. No two events overlap. Referee runs on its own persistent asyncio loop (`SyncLLMReferee`) so the sync engine thread blocks deterministically per event.

Walked example (possession p0007, A offense): A1 `DRIVE RIGHT` vs B1 `DEFEND`; A2 `CUT → LEFT_CORNER` on A1's `[action to=A2]` directive from prior event; A3 `SCREEN`; B2 `HELP_PAINT`; contact `BODY_CONTACT_DRIVE` annotates; query `"DRIVE; contact=True; BODY_CONTACT_DRIVE between A1 (…) and B1 (…) …"`; retriever routes `blocking_charging` (+`team_fouls`/`free_throws` if fouls ≥ 6); referee returns `<REFEREE_DECISION call="FOUL" … rules="R33.8,…"/>` or `NONE`; engine applies FTs/possession per `rules.py`; invariant check; all records written with `event_idx` linkage.

---

## 5. Constraints and invariants (non-negotiable for this gate)

1. **Config models immutable.** The notebook loads `configs/llm.yaml`, `simulation.yaml`, `teams/roster.yaml`, `teams/initial_memory.yaml` via `config.py` loaders and asserts the resolved slugs. No write to `configs/`, no hardcoded model names/endpoints/keys in code. `git diff -- configs/` must be empty at the end.
2. **`referee.enabled` handling without editing the file.** `configs/llm.yaml` currently ships `referee.enabled: false, backend: rule_based`. The final test requires the LLM backend. The notebook therefore loads the file unchanged, then constructs an **in-memory copy** with `enabled=True, backend="llm"` (model/temperature/max_tokens/top_k unchanged) and logs both the file fingerprint and the runtime override explicitly in `game_start.config_snapshot` and the run manifest. This is an override, not a config edit. If you prefer zero overrides of any kind, say so — then the prerequisite is a human flipping those two keys before the run, which the plan records as a manual pre-step rather than notebook behavior.
3. **Engine is authoritative.** The referee returns a ruling; only `rules.py` / `session.py` mutate score, clock, possession, fouls, FTs. Assert `score_after == score_before + scoring_events` every event in validation.
4. **Secrets hygiene.** `OPENROUTER_API_KEY` from env only. Never printed, never logged, never committed. Raw LLM prompts/responses are logged for audit but the key never appears in them.
5. **Determinism where possible, honesty where not.** Seeded RNG (`GameRNG.from_seed(seed)`), config hash, prompt hashes, model slug, code commit recorded per game. Temperature > 0 players means exact replay is not guaranteed — checkpoint + full trace is the reproducibility story, not bit-identical reruns.
6. **Clean-kernel linearity.** The notebook runs top-to-bottom with a single `CFG` dict (`MODE, SEED, MAX_EVENTS, OUT_DIR, RESUME`) and no hidden state.
7. **Graded-env safety.** No `matplotlib`/`pillow`/`gymnasium` imports in the game path (per standing convention they may be absent). Display stays `off`. Analysis cells degrade gracefully.

---

## 6. Gap analysis: what "connect everything" actually requires

The only structural gap found: **`runner/llm_game.py::run_llm_game` does not accept or call a referee.**

- `runner/game.py::run_logged_game` → supports `referee: Referee | LLMReferee`, builds `SyncLLMReferee(LLMReferee(backend, retriever, llm_cfg.referee))` when `llm_config.referee.enabled and backend=="llm"`, threads `referee_trace`/`referee_query`/`referee_decision` through `play_heuristic_game`'s event payload, and logs via `trace.as_log_record`.
- `runner/llm_game.py::run_llm_game` → has `llm, embedder, similarity_threshold, checkpoint/resume` but **no `referee`/`rule_retriever`/`rule_index_dir` params** and writes a synthetic `RefereeRecord(query="…rule-based review", decision=RefereeDecision())`.

Therefore the implementation phase (not this turn) must do **exactly one** of:

- **Option A (recommended):** extend `run_llm_game` with optional `referee` / `llm_backend_for_referee` / `rule_retriever` params mirroring `run_logged_game`, drive per-event `build_referee_state → SyncLLMReferee.judge → apply` through the existing `EngineSession` payload path, and log via `last_result.as_log_record`. Smallest new code, reuses the proven bridge.
- **Option B:** notebook-side loop that calls `EngineSession.step` directly and interposes the referee itself. Larger, duplicates `run_llm_game` logging — avoid unless `run_llm_game` proves unchangeable.

Either way: no WS1–WS6 redesign, one adapter, fully logged. If the implementer finds any other interface break, it is documented in Section 12 style and fixed minimally — never bundled with unrelated refactors.

Also required but trivial: pass the configured `LocalEmbedder(cfg.embeddings.model)` (already proven in `scripts/run_llm_game.py`) so WS4 similarity merging is live, not exact-match.

---

## 7. Work breakdown with implementation gates

| Phase | Work (future) | Expected output | Gate (stop/go) |
|---|---|---|---|
| G0 Preflight | Env check: Python ≥ 3.11, `uv sync` state, `OPENROUTER_API_KEY` present, `data/rules/*` checksums valid, `pytest -q -m "not live"` green, `ruff` clean, `git status` clean, record commit hash | Preflight report | GO only if suite green and index manifest verifies; else stop |
| G1 Retrieval sanity | `scripts/validate_referee_retrieval.py` on the checked-in index (expect 22/26 hit@3 per audit; baseline 14/26 documented) | Retrieval report | GO if ≥ revised baseline; any regression stops the gate |
| G2 Adapter | Implement Section 6 Option A; add `referee` params to `run_llm_game`; keep FakeLLM path working | Diff ≤ ~100 lines + tests | GO if FakeLLM full-prefix game still passes strict log reader with IAR=0/PARSE_FAIL=0 |
| G3 Notebook construction | Materialise Appendix A as `proposal/pre_ws7_full_game_test.ipynb` (jupytext-free plain `.ipynb`, matching `proposal/` convention of markdown plans + one notebook) | Notebook file, never executed yet | GO if `jupyter nbconvert --to notebook --execute --dry-run` parses and `ruff` equivalent cells lint |
| G4 Live smoke | Short live prefix (`MAX_EVENTS=20–40`, seed 101) with players + LLM referee | Prefix JSONL + checkpoint | GO if decisions/referee/message/captain records present, no exception, cost/latency sane |
| G5 Full game | Full termination run, seed 101 (then optionally 102), `resume=True`, display off | Complete JSONL + `game_end` | GO only if `game_complete`, possession accounting validates, every event has a referee record |
| G6 Post-game validation | `read_game_log`, `validate_possessions`, `compute_game_metrics`, transcript of 2–3 possessions, export smoke | Metrics + transcript excerpts | GO if no `incomplete`/`insufficient_evidence` surprises beyond documented causes |
| G7 Handover | Manifest + artifact bundle under `runs/pre_ws7/` | WS7-ready package (Section 11) | GO if clean-kernel "Run All" reproduces the validation section from the saved JSONL without new LLM calls |

Cost/time guardrails for G4–G5: per plan §8, ~1,700 player calls + ~280 referee calls per full game; on `:free` models cost is $0 but **quota is the binding constraint** (free-tier ~20 req/min, 1,000 req/day). The notebook therefore sets `max_concurrent_requests=12`, RPM ≤ 18, per-call `timeout_s=45`, SQLite cache **on** for this gate, checkpoint every event, and `QuotaExceededError` aborts cleanly to resume the next window. Wall-clock estimate 20–60 min for a full game depending on referee latency; the notebook enforces a wall-clock cap and fails loud on timeout rather than hanging.

---

## 8. Final test procedure (what the notebook will do)

1. **Preflight cell:** assert Python, imports, `OPENROUTER_API_KEY` exists (presence only), index files + manifest checksums, config files load, `git diff -- configs/` empty at start.
2. **Config echo (read-only):** print resolved `players.model`, `referee.model`, `embeddings.model`, RPM/concurrency, roster captain/slots, simulation win/clock/shot-clock. Assert referee model slug equals the file value; assert in-memory referee override is the only delta.
3. **Component construction:** `LocalEmbedder` warm-up (`embedder("Basketball coordination")`), `RuleRetriever("data/rules", expected_model=cfg.embeddings.model)`, `OpenRouterClient(cfg)` (one shared backend for players; referee reuses it or a second instance — implementation choice, logged), `LLMReferee(backend, retriever, llm_cfg.referee_override)`, `SyncLLMReferee` per game with `close()` in `finally`.
4. **Smoke (live, bounded):** `MAX_EVENTS=20`, seed 101 → assert ≥ 1 referee `FOUL`/`VIOLATION`/`NONE` record per event, messages delivered at `t+1`, memory/CS proposal records present.
5. **Full game (live, to termination):** `MAX_EVENTS=2000`, seed 101, `resume=True`, `experiment_id="pre_ws7"`, `game_id="pre_ws7_s101"`, `replicate_id="seed_101"`, both teams `A_full` (`comms/captain/memory_write: true`) so every channel is exercised. No early stop except quota/timeout abort (which resumes, not passes).
6. **Offline validation from the saved JSONL only** (no new LLM calls): strict read, possession validation, metrics, transcript, export smoke, referee audit (call distribution, `REF_PARSE_FAIL` rate, citation grounding, objective-violation rejection count).

---

## 9. Acceptance criteria (assertions, not eyeballing)

Full-game gate (seed 101):

- `game_complete is True`; `game_end.end_reason ∈ {WIN_SCORE, CLOCK_EXPIRED, OT_WIN}` consistent with `final_score` and clock/OT rules.
- `read_game_log` succeeds; `validate_possessions`: every possession closed, final points reconcile with `game_end`, offensive rebounds did not fork possessions, FT points attributed to the foul possession.
- Record coverage: 6 `decision` records per event; ≥ 1 `referee` record per event with non-empty `query`, `retrieved_chunk_ids` (len ≤ 3, each ∈ index), `model == cfg.referee.model`, `raw_output` present; `state` per event with `constraints_checked == [1..20]`; `game_start` carries `config_hash`, `prompt_hashes`, `model_slug`, roster, initial memory.
- Referee audit: `REF_PARSE_FAIL` rate reported; every non-`NONE` call cites ≥ 1 retrieved ID and names an in-state offender; zero engine-objective calls originated from the referee (guard counters in `loop.py` path / equivalent in `llm_game` adapter).
- Quality signals reported (not fudged): parse-fail rate, IAR by reason, SIR count (must be 0), referee call rate, tokens/cost/latency totals, events/possessions/score.
- Reproducibility: `config_hash` stable across resume; checkpoint removed on clean finish; `git diff -- configs/` still empty; manifest records commit, package versions, seed, run ID, wall-clock.
- Negative-path coverage (at least one of, via existing hooks — supplements, never replaces the real game): `FaultInjectingPolicy` prefix shows `PARSE_FAIL` → remap → game continues; malformed referee XML fixture yields `NONE` + `REF_PARSE_FAIL` without mutating state.

---

## 10. Test matrix

| # | Test | Mode | Pass condition |
|---|---|---|---|
| T1 | Unit + property suite (`pytest -m "not live"`) | Offline | Green |
| T2 | Retrieval validation (`validate_referee_retrieval.py`) | Offline, local MiniLM | 22/26 hit@3, 26/26 category eligibility (no regression from audit) |
| T3 | FakeLLM full-prefix (`LegalXMLPolicy`, 20–50 events) | Offline LLM-shape | Strict reader passes, IAR=0, PARSE_FAIL=0 |
| T4 | Fault-injection prefix (10% malformed) | Offline | PARSE_FAIL rate ≈ injection ± repair, game continues |
| T5 | Live smoke prefix (20–40 events, LLM players + LLM referee) | Live | All record types present, no exception, cost/latency logged |
| T6 | **Full live game to termination (seed 101)** | Live | Section 9 all green — **the gate** |
| T7 | Offline re-validation from saved JSONL (read/possessions/metrics/transcript/export) | Offline | Passes with zero new LLM calls |
| T8 | Resume test (kill/resume or quota-abort path on a prefix) | Offline/live-infra | Checkpoint resumes without duplicate events or hash drift |

---

## 11. Artifacts and WS7 handover

Notebook (future): `proposal/pre_ws7_full_game_test.ipynb` — single "Run All" from a clean kernel is the acceptance path.

Run directory (per full game): `runs/pre_ws7/<YYYYMMDD_HHMMSS>_seed_<seed>/` containing:

- `game.jsonl` (the authoritative log) + `game.ckpt.json` (removed on clean finish; retained if aborted)
- `run_manifest.json` (run ID, seed, commit, package versions, config fingerprints + explicit referee-override delta, model slugs, prompt hashes, index manifest hashes, events/possessions/score/end_reason, parse/IAR/SIR/referee rates, tokens/cost/latency, wall-clock, quota pauses)
- `metrics.json` (`compute_game_metrics().to_dict()`), `possessions.json` (validation output)
- `transcripts/` (2–3 possessions via `render_possession_transcript`, e.g. first, a foul, the closing run)
- `referee_audit.json` (per-event: query, categories, chunk IDs, call, citations, REF_PARSE_FAIL reason if any, objective-rejection flag)
- `export_smoke/` (one `bball export` of this single game, proving WS7 can consume it) — `stats`/`plots` on one game are not findings, only pipeline proof

WS7 handover checklist: artifact paths, how to replay offline (`read_game_log` → metrics/transcript/export without keys), known limitations (free-model dependence, τ=0.80 provisional, model-terms enrichment pending), measured cost/latency, and the first three WS7 steps (freeze prompts/configs → pilot seeds → main ablations).

---

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| `run_llm_game` referee gap larger than expected | Option A adapter only; G2 gate blocks G4 until FakeLLM path re-passes |
| Free-tier RPM (20/min) / daily 1k cap stalls a ~2k-call game | RPM bucket 18, concurrency 12, cache on, per-event checkpoint, clean quota-abort + `resume=True`; full game may span windows — planned, not failure |
| Referee on every event dominates wall-clock / over-calls | Fast cheap referee model (already configured); temp 0; no-contact fixture set guards false-call rate; excerpts capped at 3 |
| Malformed XML from players or referee | `complete_with_repair` (1 re-ask) → `PARSE_FAIL`/`REF_PARSE_FAIL` → engine remap / `NONE`; never silently repaired into a call; rates reported |
| Prompt-length drift across ablations | Disabled sections render `none`, never removed (WS3/WS4 contract) |
| OneDrive path locking / long paths | All writes inside repo (`runs/pre_ws7/`), `encoding="utf-8"`, never overwrite an existing dir, checkpoint-then-rename pattern already in runner |
| Accidental config edit | Loader-only access; pre + post `git diff -- configs/` assertions; override held in memory and logged as a delta |
| Silent success (exceptions swallowed) | No bare `except: pass` in notebook or adapter; `SyncLLMReferee.close()` in `finally`; provider failures propagate; only malformed decisions fall back |
| Secrets in artifacts | Key never logged; manifest records key *presence*, never value; raw traces contain prompts/responses only |
| Graded-env missing deps | No `matplotlib`/render imports in game path; analysis cells guard optional imports |

---

## 13. Assumptions and open questions (post-review)

Assumptions recorded (from your 2026-10-22 answers): blueprint-only this turn; full-termination game; LLM referee live via in-memory enablement (models untouched); `proposal/` + `runs/pre_ws7/` timestamped layout.

Questions for your review before materialisation:

1. Confirm the **in-memory `referee.enabled/backend` override** approach, or do you want the two keys flipped in `configs/llm.yaml` by hand first (still no model change)? The notebook will implement whichever you choose — it will not do both.
2. Seed 101 for the gate game is assumed (matches `pilot.yaml` and prior `runs/game_101.jsonl`). Confirm, or name another seed.
3. Both teams `A_full` for the gate (exercises every channel). Confirm — the alternative is A_full vs a Team-B/C/D ablation, which belongs to WS7, not this gate.
4. Is the τ=0.80 similarity threshold frozen for this run, or should the notebook take it from wherever WS4 left it without comment? (No calibration work is planned in this gate either way.)
5. May the G2 adapter touch `runner/llm_game.py` + tests only, or must even that wait for a separate approval? Currently assumed permitted as the implementation phase's first step.

---

## Appendix A — Future notebook blueprint (`proposal/pre_ws7_full_game_test.ipynb`)

> Not created or executed this turn. This blueprint is normative: the future `.ipynb`
> must implement these cells in order, each idempotent and re-runnable, "Run All" clean-kernel green.

**Cell 0 — Markdown: title, scope, non-goals.** States plan-only provenance (`PRE_WS7.md`), frozen-model rule, full-termination + live-referee acceptance, artifact layout.

**Cell 1 — Environment preflight (code).**
Check `sys.version ≥ 3.11`, imports (`bball3x3.*`, `numpy`, `openai`, `sentence_transformers` lazily), `OPENROUTER_API_KEY` presence (boolean only), repo root via `pathlib` (OneDrive-safe), `data/rules/{chunks.jsonl,embeddings.npy,index_manifest.json}` exist. Print commit hash (`git rev-parse HEAD`) and `git status --porcelain` (must be clean or explicitly listed).

**Cell 2 — Config load, read-only + echo (code).**
`load_llm_config()`, `load_simulation_config()`, `load_roster_config()`, `load_initial_memory_config()`. Print players/referee/embeddings model slugs, referee `temperature/max_tokens/top_k_rules`, runtime RPM/concurrency, roster slots/captain, win/clock/shot-clock/bonus. Assert: `players.model` and `referee.model` equal the file values (no hardcoded slugs in the notebook — compare against `yaml.safe_load` of the same files); `referee.temperature==0.0`, `top_k_rules==3`, `output_format=="xml"`. Build `ref_cfg_live = llm_cfg.referee.model_copy(update={"enabled": True, "backend": "llm"})` **in memory**; record `{"file": <sha256 of llm.yaml>, "override": {"enabled": false→true, "backend": "rule_based→llm"}}` for the manifest. (If Q1 resolves to manual flip, this cell instead asserts `enabled is True` and records no override.)

**Cell 3 — Imports + constructors (code).**
`OpenRouterClient`, `RuleRetriever`, `LLMReferee`, `SyncLLMReferee`, `LocalEmbedder`, `run_llm_game` (post-G2 signature with referee params), `read_game_log`, `validate_possessions`, `compute_game_metrics`, `render_possession_transcript`. Instantiate embedder + warm-up call, retriever with `expected_model=cfg.embeddings.model`, shared `OpenRouterClient(cfg)`.

**Cell 4 — Run constants (code).**
Single `CFG = {"SEED": 101, "MAX_EVENTS": 2000, "OUT_DIR": "runs/pre_ws7/<timestamp>_seed_101", "EXPERIMENT_ID": "pre_ws7", "GAME_ID": "pre_ws7_s101", "RESUME": True}`. `OUT_DIR` must not exist; create it. Display forced off.

**Cell 5 — Live smoke prefix (code, live).**
`await run_llm_game(llm=backend, path=OUT_DIR/"smoke.jsonl", seed=CFG["SEED"], llm_config=cfg_with_live_referee, embedder=embedder, referee_bridge=True, max_events=30, checkpoint+resume)`. Assert ≥ 30 events or game end, 6 decisions/event, 1 referee record/event with model/cost fields. Print tokens/cost/latency. (This cell burns the first live calls; abort here on any exception.)

**Cell 6 — Full game to termination (code, live).**
`await run_llm_game(... path=OUT_DIR/"game.jsonl", max_events=2000, ...)` with `SyncLLMReferee` lifecycle owned by the runner/adapter and closed in `finally`. Prints running `result` dict (`events, score, game_complete, end_reason, iar, parse_failure_rate, total_cost_usd`). Quota abort → cell reports `RESUME_REQUIRED` with checkpoint path; re-run continues without losing progress.

**Cell 7 — Offline strict validation (code, no LLM).**
`game = read_game_log(OUT_DIR/"game.jsonl")`; `poss = validate_possessions(game)`; `metrics = compute_game_metrics(game)`. Assert Section 9 (closure, reconciliation, coverage, referee grounding, SIR==0). Print score, events, possessions, PPP snapshot, parse/IAR/SIR/referee-call rates.

**Cell 8 — Transcripts + referee audit (code, no LLM).**
Render opening, one foul/scoring, and closing possessions (`render_possession_transcript`); build `referee_audit.json` (query → categories → chunk IDs → call → citations → failure codes); assert every non-`NONE` cites retrieved IDs and every event has exactly one referee record.

**Cell 9 — Export smoke + manifest (code, no LLM).**
`build_experiment_tables([game.jsonl]) → write_experiment_tables(export_smoke/)`; write `metrics.json`, `possessions.json`, `run_manifest.json` (Section 11 fields + `git diff -- configs/` empty proof). List `OUT_DIR` tree.

**Cell 10 — Markdown: verdict + WS7 handover.**
Pass/fail table vs Section 9, measured numbers pasted from Cell 7/9 outputs, known limitations, artifact paths, suggested WS7 first steps. Final line: `PRE_WS7 GATE: PASS | FAIL (reason)`.

Execution contract: Cells 7–10 must pass from the saved JSONL alone (airplane-mode test). Cells 5–6 are the only live cells. No cell after Cell 6 may call any LLM.
