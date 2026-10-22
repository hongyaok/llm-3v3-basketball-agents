# WS4: Communication, Captain, Shared Memory and Counter-Strategies

## Implemented behavior

- Each team has a private communication channel.
- Messages become visible from the next decision event.
- The communication window covers the preceding two events, with at most
  six delivered messages and 200 characters per message.
- Players do not receive their own messages.
- Only the configured captain can submit captain calls.
- Captain calls persist until replaced; maintain preserves the current call.
- Ordinary teammate tactic suggestions reach the captain through messages.

Shared memory validates opposing-player IDs, categories and nonempty text.
Exact matches merge; an injected embedder also enables cosine-similarity
merging within the same opponent/category group. Merging increases confidence.
Each group holds at most four entries. Overflow removes the lowest-confidence,
oldest entry; a proposal weaker than every existing entry is rejected.
Memory IDs are not reused.

Counter-strategy tables start empty. Matching opponent strategies merge within
the same offense/defense side, preserving the key and updating the counter.
Valid emitted tactic references increment the reference count. References
must identify entries visible before the decision event.

Memory and CS snapshots preserve historical visibility. Writes become visible
at the next event. Proposal acceptance, committed writes and memory evictions
are logged. WS6 excludes invalid memory references from MAUR while retaining
the original references in decision records.

## Ablations

- comms=False disables ordinary messages while retaining captain calls.
- captain=False disables captain calls while retaining ordinary messages.
- memory_write=False prevents memory and CS writes; initial memory remains
  readable and the CS table stays empty.

Use fresh coordination stores for each game.

## Local embeddings

Install:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[embeddings]"
```

The local adapter uses the model configured in configs/llm.yaml, currently
sentence-transformers/all-MiniLM-L6-v2. It runs on CPU and downloads model
weights on first use.

run_llm_game() uses exact matching unless an embedder is supplied.
scripts/run_llm_game.py supplies the configured local embedder.

## Smoke run

Run from the repository root with a new output path:

```powershell
.\.venv\Scripts\python.exe scripts/run_llm_game.py --output outputs/ws4-check/game.jsonl --max-events 20
```

This uses fake players and real local embeddings, with no OpenRouter calls.
The fake policy does not propose memory updates; automated tests separately
exercise memory/CS merging, rejection, eviction and replay.

Adding --live uses OpenRouter players and requires the configured API key.
Fake-player results are pipeline checks, not experiment results.

## Reproducibility

Game metadata records the embedding identity and similarity threshold.
The configuration hash includes those settings. Checkpoint resume rejects
changed configurations or seeds before replacing the existing log.
Older checkpoints without the configuration hash are unsupported.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest -q -m "not live"
.\.venv\Scripts\python.exe -m ruff check .
```

Tests cover channels, captain persistence, flags, memory and CS stores,
event-time reference validity, logging, eviction, and checkpoint replay.

## Remaining experimental validation

The similarity threshold of 0.80 is provisional. Calibrate it against
approximately 50 hand-labelled basketball tendency/strategy pairs before
freezing experiment settings. Record the model, labels, selected threshold
and evaluation results.