# llm-3v3-basketball-agents

multi-agent llm simulation for competitive 3v3 basketball (fiba rules).

## setup

### prerequisites
- python 3.11 or higher
- uv (recommended) or pip

### option 1: with uv (fast)

1. create virtual environment:
   ```bash
   uv venv
   ```

2. activate virtual environment:
   - windows (cmd / powershell):
     ```powershell
     .venv\Scripts\activate
     ```
   - linux / macos:
     ```bash
     source .venv/bin/activate
     ```

3. install packages and dev dependencies:
   ```bash
   uv sync --extra dev
   ```

### option 2: with standard venv and pip

1. create virtual environment:
   ```bash
   python -m venv .venv
   ```

2. activate virtual environment:
   - windows (cmd / powershell):
     ```powershell
     .venv\Scripts\activate
     ```
   - linux / macos:
     ```bash
     source .venv/bin/activate
     ```

3. install package in editable mode:
   ```bash
   pip install -e ".[dev]"
   ```

## running tests and linter

run tests:
```bash
uv run pytest
# or if venv is activated: pytest
```

run linter:
```bash
uv run ruff check .
# or if venv is activated: ruff check .
```

## results dashboard and game replay

Courtside is a local front end for the communication-ablation results and saved
games. From the repository root, with the experiment artifacts under
`runs/`, run:

```bash
.venv/bin/bball dashboard
# or:
uv run bball dashboard
```

Open **http://127.0.0.1:8765**. The server reads
`runs/abl_comms_v1_results` and `runs/abl_comms_v1_runs` by default. To select
other locations or a different port:

```bash
uv run bball dashboard --results /path/to/abl_comms_v1_results \
  --runs /path/to/abl_comms_v1_runs --port 8765
```

The results directory can be the downloaded parent folder or the experiment
folder containing `export/games.csv`, `export/teams.csv`,
`export/possessions.csv`, `stats.json`, and `plots/adaptation.csv`. Replay logs
are matched recursively by game ID, so exported paths from another machine
do not need changing. Multiple candidate experiments or duplicate logs are
reported instead of choosing one silently.

- **Overview:** wins, pooled rates, paired seed effects, saved confidence
  intervals and Wilcoxon results, and adaptation curves. Unavailable measures
  keep their evidence status; the paired estimate is distinct from a difference
  of pooled rates.
- **Game library:** search by seed/game, filter by first possession or winner,
  and open any matched replay.
- **Court replay:** play, pause, step, scrub, adjust speed, jump to a possession
  or scoring event, and select a player. Inspect executed actions and rationales,
  teammate messages (including delivery timing and suppression), captain calls,
  resolution evidence and referee decisions. Space toggles playback; arrow keys
  step while focus is outside an interactive control.
- **Methods & data:** experiment configuration, interpretation notes, evidence
  limitations, and downloads of the original result tables/statistics.

Court positions are recorded states after each event. Trails connect saved
previous/current positions; the display does not infer movement between events
or invent shot locations when the log has no shot evidence. Game logs load on
demand. The server binds only to localhost, makes no LLM calls, and leaves source
files untouched. No Node installation or additional dependencies are required.

## referee rulebook index

Place the official 3x3 rulebook PDF at
`data/rules/fiba-3x3-basketball-rules-full-version.pdf`, then run:

```bash
uv run --extra rag bball build-index
```

This extracts numbered referee-relevant clauses into `data/rules/chunks.jsonl`
and aligned, normalized vectors into `data/rules/embeddings.npy`. The
`index_manifest.json` records the PDF hash, embedding backend/model, dimensions,
and category counts. The default backend uses the configured MiniLM semantic
model; its weights may download on first use. For a fully local fallback with
no model dependency, use deterministic lexical hash vectors instead:

```bash
uv run bball build-index --backend hash --force
```

Use the same embedding backend and model for future retrieval queries. The
indexer refuses to replace existing artifacts unless `--force` is supplied.

To retrieve the three most relevant excerpts for a `RefereeState`:

```python
from bball3x3.referee import RuleRetriever

retriever = RuleRetriever("data/rules")  # load once, then reuse for each state
result = retriever.retrieve(referee_state)
print(result.query, result.chunk_ids)
for rule in result.rules:
    print(rule.id, rule.category, rule.score, rule.text)
```

Retrieval filters by event, contact type, and ball status before cosine ranking.
The result includes source PDF pages. The retriever checks index integrity and
uses the same embedding backend/model recorded in the manifest. This is a
standalone retrieval API that the LLM referee also uses during games.

Validate the saved index against independently labelled rule clauses in the
existing 40 referee states:

```bash
uv run --extra rag python scripts/validate_referee_retrieval.py
```

`retrieval_gold.jsonl` labels 26 states for which a specific rule clause is
relevant. The report gives retrieval hit@3 (a labelled state's top three
results contain at least one gold clause), category-filter recall, call-type
breakdown, and per-case misses. Its denominator is the 26 labelled states;
the other 14 remain in the separate decision accuracy and false-call checks.
For the original MiniLM semantic index, the measured baseline is **14/26
hit@3 (53.8%)**, with gold-rule category eligibility of **25/26 (96.2%)**.
After the source-clause/category audit and focused category routing, the same
unchanged labels measure **22/26 hit@3 (84.6%)** and **26/26 category eligibility**.
The original 14/26 remains the baseline; see
[`proposal/WS5_RETRIEVAL_AUDIT.md`](proposal/WS5_RETRIEVAL_AUDIT.md) for every
baseline miss, mapping correction, and the four remaining misses. This is a
retrieval measurement on synthetic states, not a live-game accuracy result.
The command uses the local index and model only; it makes no agent API calls.
First use of the semantic model may download its weights. To evaluate another
index or label set, pass `--index-dir`, `--cases`, or `--gold`.

The asynchronous `LLMReferee` accepts an LLM backend implementing
`complete(messages, params)` and a `RuleRetriever`. Its `judge_with_trace(state)`
returns the effective decision, retrieved rule IDs, raw model reply, parse
status, and request accounting. `judge(state)` returns only the decision.
Malformed or ungrounded XML becomes a `NONE` decision with `REF_PARSE_FAIL` in
the trace; `result.as_log_record(event_idx)` builds a typed WS6 referee record
with the raw reply and failure status. Logged games bridge to the async referee
on one persistent per-game event loop and apply its effective call before
recording the next state. To run one, set `referee.enabled: true` and
`referee.backend: llm` in `configs/llm.yaml`, set `OPENROUTER_API_KEY`, and run:

```bash
uv run --extra rag python -m bball3x3.runner.game \
  --llm-config configs/llm.yaml --rule-index-dir data/rules \
  --path runs/llm_game.jsonl
```

Without `--llm-config`, or when the referee is disabled, games keep the
rule-based referee. The log includes the LLM model, token counts, cost,
latency, retrieved chunk IDs, raw output, and any `REF_PARSE_FAIL` reason.
Provider failures propagate; only malformed decisions fall back to `NONE`.

## possession transcripts

After installing the package, print a possession from a saved JSONL game log:

```bash
uv run bball transcript logs/game.jsonl p0001
# or with the virtual environment activated:
bball transcript logs/game.jsonl p0001
python -m bball3x3 transcript logs/game.jsonl p0001
```

The first argument is a file path; the second is the exact possession ID in
the log. The transcript includes observations, messages, captain calls,
proposed/executed actions, rationales, memory references and mutations,
referee calls, outcomes, and state snapshots. Open possessions in valid
unfinished logs can also be inspected. Unknown possession IDs report the
available IDs.

Decision producers should pass the exact player-facing text as
`DecisionRecord(observation_text=observation_text, ...)`. The schema calculates
`observation_hash` as SHA-256 of its UTF-8 bytes and rejects a supplied hash
that disagrees. Older logs without observation text display `[not recorded]`.
The observation is saved as-is; transcripts do not recreate it from state.

Possession boundary events may appear in adjacent transcripts. Their decisions
belong to the resolution's `possession_before`; scoring entries retain their
own possession IDs. Earlier messages delivered during the selected span and
prior captain-call context are labeled separately. Inferred t+1 delivery is
marked; the recorded observation is the evidence for what a player saw.

## experiment exports

Export one or more saved games into a new directory:

```bash
uv run bball export outputs/ablation-comms logs/game-a.jsonl logs/game-b.jsonl
# or with the environment activated:
bball export outputs/ablation-comms logs/game-a.jsonl logs/game-b.jsonl
```

The command creates `games.csv`, `teams.csv`, `possessions.csv`, and
`manifest.json`. Game and team rows include experiment/game IDs, physical-team
conditions, seed, first-possession replicate, config identity, and metric
counts, rates, and evidence status. Detailed breakdowns and adaptation bins
are JSON columns within the CSV tables. Possession rows include owning
condition, points by team, the owning team's score difference before that
possession, start clock, regulation bin (`q1`–`q5`) or `ot`, and whether the row
is ready for modelling.

By default unfinished games are excluded and named in the manifest. Add
`--include-incomplete` to export them for inspection; open possessions then
have blank outcome fields and are never marked model eligible. Complete games
whose possession accounting fails validation retain game and team rows with
the error and have no possession rows. The output directory must be new; an
existing directory is never overwritten. `--window 2` selects the two-event
robustness window for instruction metrics (default: 1).

## experiment statistics

Analyse an exported experiment without rerunning games:

```bash
uv run bball stats outputs/ablation-comms outputs/ablation-comms-stats.json
```

The JSON reports A-minus-ablation differences for PPP and the exported
coordination/validity rates. Each seed's two opposite-start games are averaged
before a seed-cluster bootstrap (95% interval) and two-sided Wilcoxon test.
Missing or invalid pairs are excluded per metric with reasons. The fixed
bootstrap seed defaults to 4213; change it with `--analysis-seed`.
Possession-level Gaussian random-intercept fits report condition, pre-possession
score difference, time bin, and a condition-by-time interaction. These are
exploratory: paired seed effects are the primary inference. Insufficient or
failed fits are reported in the JSON; the command never overwrites an existing
result file.

## adaptation plots

Render the three planned curves from the same export:

```bash
uv run bball plots outputs/ablation-comms outputs/ablation-comms-plots
```

The new directory contains `adaptation.csv`, `manifest.json`, and one PNG each
for PPP, MAUR and CSSR per comparison. Rates pool valid numerators and
denominators across the two first-possession variants of each eligible seed;
the CSV records exposure and evidence status. Regulation quintiles without
exposure remain blank, not zero. OT appears as a separate point, never joined
to the regulation curve. The manifest records exclusions and bin/attribution
rules. The command will not overwrite an existing directory.
