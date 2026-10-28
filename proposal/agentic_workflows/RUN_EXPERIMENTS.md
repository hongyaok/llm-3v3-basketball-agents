# Run Experiments

## Done

- Model picked: `mistralai/mistral-small-3.2-24b-instruct` for players and referee (see `MODEL_SELECTION.md`).
- `configs/llm.yaml` set up for experiments: cache off, $10 budget cap per experiment.
- Experiment runner added: `bball run-experiment`. It plays every seed twice so each team starts with the ball once, and resumes if stopped.
- Short test run on real API: logs valid, no parse or referee failures.

## Next

Run these in order. Check the pilot results before starting the ablations.

| Order | Config | Matchup | Games | Est. cost |
|---|---|---|---|---|
| 1 | `pilot.yaml` | A_full vs A_full | 6 | ~$2.40 |
| 2 | `ablation_comms.yaml` | A_full vs no comms | 20 | ~$8 |
| 3 | `ablation_captain.yaml` | A_full vs no captain | 20 | ~$8 |
| 4 | `ablation_memory.yaml` | A_full vs no memory writing | 20 | ~$8 |

## How to run

Setup (once):

```bash
git fetch
git switch ws7
git pull
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,rag]"
```

Add `.env` file in the repo root with the API key.

```
OPENROUTER_API_KEY=<key>
```

Check, then run:

```bash
bball run-experiment configs/experiments/pilot.yaml --dry-run
bball run-experiment configs/experiments/pilot.yaml
```

The dry run should list 6 games and costs nothing. For the ablations, swap in their config file. If it crashes, run the same command again. Finished games are skipped.

Logs and `manifest.json` are written to `runs/<experiment_id>/`, e.g. `runs/pilot_v1/`. This folder is gitignored. Results must be saved and shared separately for analysis.
