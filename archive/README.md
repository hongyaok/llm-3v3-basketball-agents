# Archive

Historical scripts, notebooks and run artifacts kept out of the active tree so
the repository top level reads cleanly. **Nothing here is imported by `src/`,
`tests/`, or the frontend build.** Deleting this directory breaks no test and
no command.

The workstream plan (WS0 → WS7) left one-off harnesses behind at each stage.
Once the unified CLI (`bball run-experiment`) and `bball3x3.runner` landed,
those earlier harnesses were superseded. The logs from the PRE_WS7 era are
kept for provenance, not for reproduction.

## Inventory

### `scripts/` — superseded one-off harnesses

| File | What it did | Why archived | Superseded by |
|---|---|---|---|
| `pre_ws7_full_game.py` | Played one full game to termination with live LLM players **and** a live LLM referee, using in-memory config overrides, then wrote an offline validation bundle (`metrics.json`, `possessions.json`, `referee_audit.json`, `run_manifest.json`). | Pre-integration gate check. The referee wiring now lives in the runner itself. | `bball run-experiment` + `bball export` / `bball stats` |
| `live_smoke_pre_ws7.py` | 5-event live smoke game with an in-memory LLM-referee override. Verified the API key and basic wiring. | Same gate, smaller scope. | `python scripts/llm_smoke.py` |
| `run_llm_game.py` | Ran a game prefix with `LocalEmbedder` and either fake or live players; exercised the WS4 shared-memory wiring against `run_llm_game()`. | Development wiring proof. | `python -m bball3x3.runner.game` |

The three archived scripts insert `../src` on `sys.path`, so they still run from
the repository root if restored — see *Restoring* below.

### `notebooks/` — pre-integration notebook

| File | What it was |
|---|---|
| `pre_ws7_full_game_test.ipynb` | The "Run All" acceptance notebook from `PRE_WS7.md` Appendix A: embedder warm-up, retriever load, 30-event smoke cell, then a full game cell. Its blueprint is now the CLI. Never part of the graded submission. |

### `README_pre_rewrite.md` — previous root README

The 262-line README from before the 2026-10-29 rewrite: setup options, the
referee-index walkthrough, transcript/export/stats/plot usage. Kept because the
new README is shorter and drops some low-level detail that is still accurate —
notably the rulebook-index internals and the `retrieval_gold.jsonl` labelling
mechanics. Useful for recovering exact prose once the rewrite is committed and
`git show HEAD:README.md` no longer points at the old version.

### `runs/` — historical run artifacts

| Path | Size | What it is |
|---|---|---|
| `abl_comms_v1_runs/` | 145 MB | 20 JSONL game logs (`s101`–`s110`, A and B) from the **earlier 10-seed** communication-ablation run. **Still version-controlled.** |
| `abl_comms_v1_results/` | 885 KB | The matching export (`games.csv`, `teams.csv`, `possessions.csv`, `stats.json`, three comparison PNGs, `manifest.mf`). **Still version-controlled.** |
| `pre_ws7/` | 11 MB | Eight timestamped smoke/game runs from 2026-10-23 (`smoke`, `game`, `notebook_live`, plus one `fake_gate_seed101` validation bundle). |
| `pre_ws7_smoke/` | 28 MB | Fake-policy, fault-injection, resume and multiplayer-sweep logs. |
| `harness/` | 24 KB | One prompt-harness report (`report.json`, `report.md`) from hash `5571df15044f`. |
| `game_101.jsonl`, `game_11.jsonl` | 5.4 MB | Ad-hoc single-game logs with no experiment ID. |
| `nb_llm_try*.jsonl`, `nb_llm_try.ckpt.json` | 224 KB | Notebook tryout logs and one checkpoint. |

**The final results are not here.** The reported experiment set is in
[`../results/`](../results/) as compressed archives (`abl_captain_v1.zip`,
`abl_comms_v1.zip`, `abl_memory_v1.zip`, `pilot_v1_runs.zip`,
`seeds_106_110.zip`), and those are what the frontend build reads. The 20 logs
under `abl_comms_v1_runs/` cover seeds 101–110 from an older run; the reported
comms analysis uses seeds 106–110.

## Restoring something

The files are in their original relative layout, so a move back is enough:

```bash
# a script
mv archive/scripts/pre_ws7_full_game.py scripts/

# the comms logs, if you want them under runs/ again
mv archive/runs/abl_comms_v1_runs runs/
```

If the item is version-controlled (`abl_comms_v1_runs/`,
`abl_comms_v1_results/`, the three scripts, the notebook), prefer `git mv` so
the history follows the file rather than recording a delete plus an add.

## Version-control status

Two different situations live in this directory:

1. **Tracked** — `abl_comms_v1_runs/`, `abl_comms_v1_results/`, the three
   `scripts/*.py`, and `notebooks/pre_ws7_full_game_test.ipynb`. These were
   moved with `git mv`; their history is intact.
2. **Local only** — `runs/pre_ws7/`, `runs/pre_ws7_smoke/`, `runs/harness/`,
   `runs/game_*.jsonl`, `runs/nb_llm_try*`. These were previously swept into
   version control by a blanket `!runs/` rule in `.gitignore` even though they
   are development scratch. `.gitignore` now excludes them, so they stay on
   disk but are no longer committed. Nothing was deleted.

To reclaim the 145 MB that `abl_comms_v1_runs/` occupies in git history while
keeping the files locally:

```bash
git rm -r --cached archive/runs/abl_comms_v1_runs
echo "archive/runs/abl_comms_v1_runs/" >> .gitignore
```

The files remain on disk and the compressed equivalent stays in
`../results/abl_comms_v1.zip`.
